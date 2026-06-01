#!/usr/bin/env python3
"""Analyze inter-reader/cross-validation agreement for the external synthetic CXR QA survey."""
from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
from sklearn.metrics import cohen_kappa_score

BINARY_COLS = [
    "is_frontal_cxr_like_yesno",
    "release_recommend_yesno",
    "clinical_issue_yesno",
    "downstream_ai_confusion_risk_yesno",
]
ARTIFACT_COLS = [
    "artifact_marker_OXN",
    "artifact_density_OXN",
    "artifact_gas_lucency_OXN",
    "artifact_boundaries_OXN",
    "artifact_anterior_ribs_OXN",
    "artifact_wavy_clavicle_OXN",
    "artifact_organ_shape_OXN",
    "artifact_global_quality_fov_crop_OXN",
]
SCORE_COL = "quality_score_1to5"


def normalize_binary(x):
    s = str(x).strip()
    if s.startswith("Yes"):
        return "Yes"
    if s.startswith("No"):
        return "No"
    if s.startswith("Unclear"):
        return "Unclear"
    return np.nan


def normalize_oxn(x):
    s = str(x).strip()
    if s.startswith("O") or "Present" in s:
        return "O"
    if s.startswith("X") or "None" in s:
        return "X"
    if s.startswith("N/A") or "Unable" in s:
        return "N/A"
    return np.nan


def percent_agreement(a: List, b: List) -> float:
    a = pd.Series(a)
    b = pd.Series(b)
    mask = a.notna() & b.notna()
    if mask.sum() == 0:
        return np.nan
    return float((a[mask].values == b[mask].values).mean())


def safe_kappa(a: List, b: List, weights=None) -> float:
    a = pd.Series(a)
    b = pd.Series(b)
    mask = a.notna() & b.notna()
    if mask.sum() == 0:
        return np.nan
    try:
        return float(cohen_kappa_score(a[mask], b[mask], weights=weights))
    except Exception:
        return np.nan


def to_pairs(df: pd.DataFrame) -> pd.DataFrame:
    pair_rows = []
    for gid, g in df.groupby("generated_image_id"):
        if len(g) < 2:
            continue
        rows = list(g.to_dict("records"))
        for r1, r2 in combinations(rows, 2):
            pair_rows.append({
                "generated_image_id": gid,
                "reader_1": r1.get("reader_id"),
                "reader_2": r2.get("reader_id"),
                "assignment_id_1": r1.get("assignment_id"),
                "assignment_id_2": r2.get("assignment_id"),
                "generator_name": r1.get("generator_name"),
                "model_key": r1.get("model_key"),
                "prompt_id": r1.get("prompt_id"),
                "category": r1.get("category"),
                **{f"{c}_1": r1.get(c) for c in [SCORE_COL] + BINARY_COLS + ARTIFACT_COLS},
                **{f"{c}_2": r2.get(c) for c in [SCORE_COL] + BINARY_COLS + ARTIFACT_COLS},
            })
    return pd.DataFrame(pair_rows)


def summarize_pairs(pairs: pd.DataFrame, group_cols=None) -> pd.DataFrame:
    if group_cols is None:
        group_cols = []
    if len(pairs) == 0:
        return pd.DataFrame()

    groups = [("overall", pairs)] if not group_cols else pairs.groupby(group_cols, dropna=False)
    rows = []
    for name, g in groups:
        row = {}
        if group_cols:
            if not isinstance(name, tuple):
                name = (name,)
            for col, val in zip(group_cols, name):
                row[col] = val
        else:
            row["group"] = name
        row["n_pairs"] = len(g)

        s1 = pd.to_numeric(g[f"{SCORE_COL}_1"], errors="coerce")
        s2 = pd.to_numeric(g[f"{SCORE_COL}_2"], errors="coerce")
        row["quality_score_exact_agreement"] = percent_agreement(s1, s2)
        row["quality_score_quadratic_weighted_kappa"] = safe_kappa(s1, s2, weights="quadratic")
        row["quality_score_mean_abs_diff"] = float(np.nanmean(np.abs(s1 - s2))) if len(g) else np.nan

        for c in BINARY_COLS:
            a = g[f"{c}_1"].map(normalize_binary)
            b = g[f"{c}_2"].map(normalize_binary)
            row[f"{c}_agreement"] = percent_agreement(a, b)
            row[f"{c}_kappa"] = safe_kappa(a, b)

        for c in ARTIFACT_COLS:
            a = g[f"{c}_1"].map(normalize_oxn)
            b = g[f"{c}_2"].map(normalize_oxn)
            row[f"{c}_oxn_agreement"] = percent_agreement(a, b)
            row[f"{c}_oxn_kappa"] = safe_kappa(a, b)
            # O vs non-O agreement, useful for clinical artifact presence.
            ao = a.map(lambda x: "O" if x == "O" else ("not_O" if pd.notna(x) else np.nan))
            bo = b.map(lambda x: "O" if x == "O" else ("not_O" if pd.notna(x) else np.nan))
            row[f"{c}_present_agreement"] = percent_agreement(ao, bo)
            row[f"{c}_present_kappa"] = safe_kappa(ao, bo)
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--survey_results_csv", nargs="+", required=True, help="One or more exported Google Sheet/local CSV files.")
    parser.add_argument("--hidden_assignment_csv", default="survey_manifests/M2SMF_external_QA_hidden_assignment.csv")
    parser.add_argument("--output_dir", default="outputs/external_survey_agreement")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for p in args.survey_results_csv:
        results.append(pd.read_csv(p))
    survey = pd.concat(results, ignore_index=True)
    hidden = pd.read_csv(args.hidden_assignment_csv)

    merged = survey.merge(hidden, on="assignment_id", how="left", suffixes=("", "_hidden"))
    merged.to_csv(out_dir / "survey_results_merged_with_hidden_assignment.csv", index=False, encoding="utf-8-sig")

    # Cross-validation pairs are generated_image_id with >=2 ratings.
    pairs = to_pairs(merged)
    pairs.to_csv(out_dir / "cross_validation_rating_pairs.csv", index=False, encoding="utf-8-sig")

    overall = summarize_pairs(pairs)
    by_generator = summarize_pairs(pairs, ["generator_name"])
    by_category = summarize_pairs(pairs, ["category"])
    by_reader_pair = summarize_pairs(pairs, ["reader_1", "reader_2"])

    overall.to_csv(out_dir / "agreement_overall.csv", index=False, encoding="utf-8-sig")
    by_generator.to_csv(out_dir / "agreement_by_generator.csv", index=False, encoding="utf-8-sig")
    by_category.to_csv(out_dir / "agreement_by_category.csv", index=False, encoding="utf-8-sig")
    by_reader_pair.to_csv(out_dir / "agreement_by_reader_pair.csv", index=False, encoding="utf-8-sig")

    summary = {
        "n_total_ratings": int(len(survey)),
        "n_unique_assignments": int(survey["assignment_id"].nunique()),
        "n_unique_generated_images_rated": int(merged["generated_image_id"].nunique()),
        "n_cross_validation_pairs": int(len(pairs)),
    }
    if len(overall):
        summary.update(overall.iloc[0].to_dict())
    with open(out_dir / "agreement_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("Wrote agreement analysis to:", out_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
