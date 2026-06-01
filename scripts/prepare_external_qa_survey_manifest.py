#!/usr/bin/env python3
"""
Prepare blinded reader assignments for the M2SMF external synthetic CXR QA survey.

Design:
- 75 prompt scenarios.
- 4 generators: gpt, gemini, roentgen, sana.
- 300 unique generated images.
- 4 readers/professors, 100 ratings each.
- Each reader sees 25 images per generator.
- Each reader has 75 primary ratings + 25 cross-validation duplicate ratings.
- Overall: 300 unique images + 100 duplicate ratings = 400 total ratings.

The generated hidden master file must be kept by the study coordinator only.
Reader-facing worklists should not include generator, prompt, disease, age, or sex.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import random
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import pandas as pd

READERS = ["professor_1", "professor_2", "professor_3", "professor_4"]
READER_DISPLAY = {
    "professor_1": "Professor 1",
    "professor_2": "Professor 2",
    "professor_3": "Professor 3",
    "professor_4": "Professor 4",
}

GENERATORS = [
    {
        "model_key": "gemini",
        "generator_name": "Nano Banana",
        "folder": "gemini",
        "model_version_or_identifier": "gemini-2.5-flash-image / Nano Banana",
    },
    {
        "model_key": "sana",
        "generator_name": "Sana",
        "folder": "sana",
        "model_version_or_identifier": "CheXGenBench Sana CXR generator",
    },
    {
        "model_key": "gpt",
        "generator_name": "ChatGPT Images 2.0",
        "folder": "gpt",
        "model_version_or_identifier": "ChatGPT Images 2.0",
    },
    {
        "model_key": "roentgen",
        "generator_name": "RoentGen-v2",
        "folder": "roentgen",
        "model_version_or_identifier": "RoentGen-v2",
    },
]

# Prompt-ID based categories for the 75 prompts described in the study protocol.
CATEGORY_BY_RANGE = [
    (1, 14, "No acute / normal", "No acute cardiopulmonary abnormality"),
    (15, 26, "Pneumonia / opacity", "Pneumonia / air-space opacity"),
    (27, 34, "Atelectasis / scarring", "Atelectasis / scarring"),
    (35, 42, "Pulmonary edema / vascular congestion", "Pulmonary edema / vascular congestion"),
    (43, 50, "Pleural effusion", "Pleural effusion"),
    (51, 57, "Cardiomegaly", "Cardiomegaly"),
    (58, 61, "Pneumothorax", "Pneumothorax"),
    (62, 65, "Chronic lung disease / interstitial", "Chronic lung disease / interstitial change"),
    (66, 70, "Support device / postoperative hardware", "Support device / postoperative hardware"),
    (71, 75, "Mixed common findings", "Mixed common cardiopulmonary findings"),
]

# Per-generator duplicate prompt targets. Across 4 generators this yields:
# normal 20, pneumonia 16, effusion/edema/atelectasis 12 each, cardiomegaly/support 8 each,
# pneumothorax/chronic/mixed 4 each.
DUPLICATE_TARGET_PER_GENERATOR = {
    "No acute / normal": 5,
    "Pneumonia / opacity": 4,
    "Atelectasis / scarring": 3,
    "Pulmonary edema / vascular congestion": 3,
    "Pleural effusion": 3,
    "Cardiomegaly": 2,
    "Pneumothorax": 1,
    "Chronic lung disease / interstitial": 1,
    "Support device / postoperative hardware": 2,
    "Mixed common findings": 1,
}

PRIMARY_TARGETS_BY_MODEL = {
    # Each reader must end up with 25 per generator. Primary + duplicate = 25.
    # These primary counts sum to 75 per model and 75 per reader across all models.
    "gemini": {"professor_1": 19, "professor_2": 19, "professor_3": 19, "professor_4": 18},
    "sana": {"professor_1": 19, "professor_2": 19, "professor_3": 18, "professor_4": 19},
    "gpt": {"professor_1": 19, "professor_2": 18, "professor_3": 19, "professor_4": 19},
    "roentgen": {"professor_1": 18, "professor_2": 19, "professor_3": 19, "professor_4": 19},
}

LABEL_COLUMNS = [
    "label_pneumonia_or_opacity",
    "label_cardiomegaly",
    "label_pleural_effusion",
    "label_pneumothorax",
    "label_edema",
    "label_atelectasis",
    "label_support_device",
    "label_chronic_lung_disease",
]


def prompt_number(prompt_id: str) -> int:
    m = re.search(r"(\d+)", str(prompt_id))
    if not m:
        raise ValueError(f"Could not parse prompt number from {prompt_id!r}")
    return int(m.group(1))


def infer_category(prompt_id: str) -> Tuple[str, str]:
    n = prompt_number(prompt_id)
    for lo, hi, category, disease in CATEGORY_BY_RANGE:
        if lo <= n <= hi:
            return category, disease
    return "Other", "Other"


def infer_age(prompt: str) -> str:
    m = re.search(r"(\d{1,3})[- ]year[- ]old", str(prompt), flags=re.IGNORECASE)
    return m.group(1) if m else ""


def infer_sex(prompt: str) -> str:
    p = str(prompt).lower()
    if " female" in p or "-old female" in p:
        return "female"
    if " male" in p or "-old male" in p:
        return "male"
    return ""


def labels_for_category(category: str) -> Dict[str, int]:
    labels = {c: 0 for c in LABEL_COLUMNS}
    if category == "Pneumonia / opacity":
        labels["label_pneumonia_or_opacity"] = 1
    elif category == "Atelectasis / scarring":
        labels["label_atelectasis"] = 1
    elif category == "Pulmonary edema / vascular congestion":
        labels["label_edema"] = 1
    elif category == "Pleural effusion":
        labels["label_pleural_effusion"] = 1
    elif category == "Cardiomegaly":
        labels["label_cardiomegaly"] = 1
    elif category == "Pneumothorax":
        labels["label_pneumothorax"] = 1
    elif category == "Chronic lung disease / interstitial":
        labels["label_chronic_lung_disease"] = 1
    elif category == "Support device / postoperative hardware":
        labels["label_support_device"] = 1
    elif category == "Mixed common findings":
        # Mixed examples P071-P075 from the prompt protocol.
        labels["label_pneumonia_or_opacity"] = 1
        labels["label_cardiomegaly"] = 1
        labels["label_pleural_effusion"] = 1
        labels["label_atelectasis"] = 1
    return labels


def read_prompts(prompt_csv: Path) -> List[Dict[str, str]]:
    df = pd.read_csv(prompt_csv)
    if "prompt_id" in df.columns:
        id_col = "prompt_id"
    elif "id" in df.columns:
        id_col = "id"
    else:
        raise RuntimeError("Prompt CSV must include either 'id' or 'prompt_id'.")

    if "annotated_prompt" in df.columns:
        prompt_col = "annotated_prompt"
    elif "canonical_prompt" in df.columns:
        prompt_col = "canonical_prompt"
    elif "prompt" in df.columns:
        prompt_col = "prompt"
    else:
        raise RuntimeError("Prompt CSV must include 'annotated_prompt', 'canonical_prompt', or 'prompt'.")

    prompts = []
    for _, row in df.iterrows():
        pid = str(row[id_col]).strip()
        prompt = str(row[prompt_col]).strip()
        category = str(row.get("category", "")).strip()
        disease = str(row.get("disease_primary", "")).strip()
        if not category or category == "nan":
            category, disease_inferred = infer_category(pid)
            if not disease or disease == "nan":
                disease = disease_inferred
        age = str(row.get("age", "")).strip()
        if not age or age == "nan":
            age = infer_age(prompt)
        sex = str(row.get("sex", "")).strip().lower()
        if not sex or sex == "nan":
            sex = infer_sex(prompt)
        severity = str(row.get("severity", "")).strip()
        if severity == "nan":
            severity = ""
        labels = {c: int(row[c]) if c in row and str(row[c]) not in ["", "nan"] else None for c in LABEL_COLUMNS}
        if any(v is None for v in labels.values()):
            labels = labels_for_category(category)
        prompts.append({
            "prompt_id": pid,
            "prompt_number": prompt_number(pid),
            "generation_prompt": prompt,
            "category": category,
            "disease_primary": disease,
            "age": age,
            "sex": sex,
            "severity": severity,
            **labels,
        })
    prompts = sorted(prompts, key=lambda x: x["prompt_number"])
    if len(prompts) != 75:
        raise RuntimeError(f"Expected 75 prompts, found {len(prompts)}")
    return prompts


def build_generation_rows(prompts: List[Dict[str, str]], image_root: Path) -> List[Dict[str, str]]:
    rows = []
    prompt_by_id = {p["prompt_id"]: p for p in prompts}
    for p in prompts:
        for gen in GENERATORS:
            rel = f"{gen['folder']}/{p['prompt_id']}.png"
            abs_path = image_root / rel
            row = {
                **p,
                **gen,
                "generated_image_id": f"{p['prompt_id']}_{gen['model_key']}",
                "image_relpath": rel,
                "image_path": str(abs_path),
                "image_exists": os.path.exists(abs_path),
            }
            rows.append(row)
    return rows


def choose_duplicate_prompt_ids(prompts: List[Dict[str, str]], seed: int) -> List[str]:
    rng = random.Random(seed)
    by_cat = defaultdict(list)
    for p in prompts:
        by_cat[p["category"]].append(p["prompt_id"])
    chosen = []
    for cat, target in DUPLICATE_TARGET_PER_GENERATOR.items():
        ids = sorted(by_cat.get(cat, []))
        if len(ids) < target:
            raise RuntimeError(f"Category {cat!r} has {len(ids)} prompts, target {target}")
        rng.shuffle(ids)
        chosen.extend(ids[:target])
    if len(chosen) != 25:
        raise RuntimeError(f"Duplicate prompt selection should have 25 prompts, got {len(chosen)}")
    return sorted(chosen, key=prompt_number)


def assign_primary(rows: List[Dict[str, str]], seed: int) -> List[Dict[str, str]]:
    rng = random.Random(seed)
    assignments = []
    for gen in GENERATORS:
        mk = gen["model_key"]
        gen_rows = [r for r in rows if r["model_key"] == mk]
        gen_rows = sorted(gen_rows, key=lambda x: x["prompt_number"])
        # Category-aware shuffle: keep deterministic but avoid monotonically ordered cases per reader.
        rng.shuffle(gen_rows)
        targets = PRIMARY_TARGETS_BY_MODEL[mk].copy()
        reader_cycle = READERS.copy()
        rng.shuffle(reader_cycle)
        reader_idx = 0
        for r in gen_rows:
            # Select a reader with remaining target for this model.
            candidates = [rd for rd in reader_cycle if targets[rd] > 0]
            if not candidates:
                raise RuntimeError(f"No primary target remaining for model {mk}")
            # Greedy choose current candidate to distribute pairings.
            rd = candidates[reader_idx % len(candidates)]
            reader_idx += 1
            targets[rd] -= 1
            assignments.append({**r, "reader_id": rd, "cv_role": "primary"})
        if any(v != 0 for v in targets.values()):
            raise RuntimeError(f"Primary targets not exhausted for {mk}: {targets}")
    return assignments


def assign_duplicates(rows: List[Dict[str, str]], primary_assignments: List[Dict[str, str]], duplicate_prompt_ids: List[str], seed: int) -> List[Dict[str, str]]:
    rng = random.Random(seed + 1000)
    primary_reader_by_image = {a["generated_image_id"]: a["reader_id"] for a in primary_assignments}

    # Duplicate target per reader/model = 25 - primary count for that reader/model.
    primary_counts = defaultdict(int)
    for a in primary_assignments:
        primary_counts[(a["reader_id"], a["model_key"])] += 1
    duplicate_targets_all = {}
    for rd in READERS:
        for gen in GENERATORS:
            mk = gen["model_key"]
            duplicate_targets_all[(rd, mk)] = 25 - primary_counts[(rd, mk)]
            if duplicate_targets_all[(rd, mk)] not in (6, 7):
                raise RuntimeError(f"Unexpected duplicate target for {rd}/{mk}: {duplicate_targets_all[(rd, mk)]}")

    duplicate_assignments = []
    global_pair_counts = defaultdict(int)

    def solve_one_model(mk: str, dup_rows: List[Dict[str, str]], targets_by_reader: Dict[str, int]):
        # Backtracking is robust for 25 images and four readers.
        # Order rows so constrained readers are handled early; random tie breaks preserve reproducibility.
        rows_local = dup_rows[:]
        rng.shuffle(rows_local)
        rows_local.sort(key=lambda r: targets_by_reader.get(primary_reader_by_image[r["generated_image_id"]], 0))
        assigned = []
        pair_counts = defaultdict(int)

        def rec(i: int) -> bool:
            if i == len(rows_local):
                return all(v == 0 for v in targets_by_reader.values())
            r = rows_local[i]
            primary_rd = primary_reader_by_image[r["generated_image_id"]]
            candidates = [rd for rd in READERS if rd != primary_rd and targets_by_reader[rd] > 0]
            if not candidates:
                return False
            # Prefer readers with more remaining quota and balanced reader pairs.
            def key(rd: str):
                pair = tuple(sorted([primary_rd, rd]))
                return (-targets_by_reader[rd], pair_counts[pair], rng.random())
            candidates = sorted(candidates, key=key)
            for rd in candidates:
                targets_by_reader[rd] -= 1
                pair = tuple(sorted([primary_rd, rd]))
                pair_counts[pair] += 1
                assigned.append((r, rd))
                if rec(i + 1):
                    return True
                assigned.pop()
                pair_counts[pair] -= 1
                targets_by_reader[rd] += 1
            return False

        ok = rec(0)
        if not ok:
            raise RuntimeError(f"Could not solve duplicate assignment for model {mk}; remaining targets={targets_by_reader}")
        return assigned, pair_counts

    for gen in GENERATORS:
        mk = gen["model_key"]
        dup_rows = [r for r in rows if r["model_key"] == mk and r["prompt_id"] in set(duplicate_prompt_ids)]
        if len(dup_rows) != 25:
            raise RuntimeError(f"Expected 25 duplicate rows for {mk}, got {len(dup_rows)}")
        targets_by_reader = {rd: duplicate_targets_all[(rd, mk)] for rd in READERS}
        assigned_pairs, pair_counts = solve_one_model(mk, dup_rows, targets_by_reader)
        for pair, n in pair_counts.items():
            global_pair_counts[pair] += n
        for r, rd in assigned_pairs:
            duplicate_assignments.append({**r, "reader_id": rd, "cv_role": "cross_validation_duplicate"})

    return duplicate_assignments

def finalize_assignments(assignments: List[Dict[str, str]], seed: int) -> List[Dict[str, str]]:
    rng = random.Random(seed + 2000)
    all_rows = []
    assignment_counter = 1
    for rd in READERS:
        reader_rows = [a for a in assignments if a["reader_id"] == rd]
        if len(reader_rows) != 100:
            raise RuntimeError(f"{rd} should have 100 assignments, got {len(reader_rows)}")
        by_model = defaultdict(int)
        for r in reader_rows:
            by_model[r["model_key"]] += 1
        for gen in GENERATORS:
            if by_model[gen["model_key"]] != 25:
                raise RuntimeError(f"{rd}/{gen['model_key']} expected 25, got {by_model[gen['model_key']]}")
        rng.shuffle(reader_rows)
        for seq, r in enumerate(reader_rows, start=1):
            blinded_id = f"{rd.replace('professor_', 'R')}_{seq:03d}"
            # Hash is not used to recover metadata, only a short case ID for UI.
            case_hash = hashlib.sha1(f"{rd}:{seq}:{r['generated_image_id']}:M2SMF".encode()).hexdigest()[:10]
            all_rows.append({
                "assignment_id": f"A{assignment_counter:04d}",
                "reader_id": rd,
                "reader_display": READER_DISPLAY[rd],
                "reader_sequence": seq,
                "blinded_image_id": blinded_id,
                "blinded_filename": f"{blinded_id}.png",
                "case_hash": case_hash,
                **r,
                "is_cross_validation_duplicate": 1 if r["cv_role"] == "cross_validation_duplicate" else 0,
                "blinding_note": "Reader-facing UI must not show generator, prompt, disease, age, sex, category, or cross-validation role.",
            })
            assignment_counter += 1
    return all_rows


def write_outputs(assignments: List[Dict[str, str]], generation_rows: List[Dict[str, str]], output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    hidden_path = output_dir / "M2SMF_external_QA_hidden_assignment.csv"
    gen_path = output_dir / "M2SMF_external_generation_manifest_300.csv"
    pd.DataFrame(generation_rows).to_csv(gen_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(assignments).to_csv(hidden_path, index=False, encoding="utf-8-sig")

    # Reader-facing worklist and image copy plans.
    reader_cols = [
        "assignment_id",
        "reader_sequence",
        "blinded_image_id",
        "blinded_filename",
        "is_frontal_cxr_like_yesno",
        "quality_score_1to5",
        "release_recommend_yesno",
        "clinical_issue_yesno",
        "downstream_ai_confusion_risk_yesno",
        "artifact_marker_yesno",
        "artifact_density_yesno",
        "artifact_gas_lucency_yesno",
        "artifact_boundaries_yesno",
        "artifact_anterior_ribs_yesno",
        "artifact_wavy_clavicle_yesno",
        "artifact_organ_shape_yesno",
        "artifact_global_quality_fov_crop_yesno",
        "other_flag_yesno",
        "main_rejection_reason",
        "free_text_comment",
    ]
    for rd in READERS:
        df_rd = pd.DataFrame([a for a in assignments if a["reader_id"] == rd]).sort_values("reader_sequence")
        work = df_rd[["assignment_id", "reader_sequence", "blinded_image_id", "blinded_filename"]].copy()
        for c in reader_cols:
            if c not in work.columns:
                work[c] = ""
        work = work[reader_cols]
        work.to_csv(output_dir / f"{rd}_blinded_worklist.csv", index=False, encoding="utf-8-sig")
        copy = df_rd[["assignment_id", "generated_image_id", "image_path", "image_relpath", "blinded_filename"]].copy()
        copy.to_csv(output_dir / f"{rd}_image_copy_plan.csv", index=False, encoding="utf-8-sig")

    # Summaries.
    df = pd.DataFrame(assignments)
    summaries = {
        "summary_by_reader": df.groupby("reader_id").size().reset_index(name="n"),
        "summary_by_reader_and_model": df.groupby(["reader_id", "model_key", "generator_name"]).size().reset_index(name="n"),
        "summary_by_reader_and_cv_role": df.groupby(["reader_id", "cv_role"]).size().reset_index(name="n"),
        "summary_duplicate_by_model": df[df["is_cross_validation_duplicate"] == 1].groupby(["model_key", "generator_name"]).size().reset_index(name="duplicate_n"),
        "summary_duplicate_by_category": df[df["is_cross_validation_duplicate"] == 1].groupby("category").size().reset_index(name="duplicate_n"),
    }
    for name, sdf in summaries.items():
        sdf.to_csv(output_dir / f"{name}.csv", index=False, encoding="utf-8-sig")

    # README.
    readme = output_dir / "README_external_survey_assignment.md"
    readme.write_text(
        "# M2SMF external synthetic CXR QA survey assignment\n\n"
        "- 75 prompts × 4 generators = 300 unique generated images.\n"
        "- 4 professors × 100 ratings = 400 total ratings.\n"
        "- Each professor evaluates 25 images from each generator.\n"
        "- 100 unique images are independently evaluated by two professors for cross-validation.\n"
        "- Keep `M2SMF_external_QA_hidden_assignment.csv` hidden from readers.\n"
        "- Reader UI should show only blinded image IDs and image files.\n",
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt_csv", default="m2smf_external_prompt_75_input.csv", help="CSV with id/prompt_id and annotated_prompt/canonical_prompt.")
    parser.add_argument("--image_root", default=".", help="Directory containing gpt/, gemini/, roentgen/, sana/ folders.")
    parser.add_argument("--output_dir", default="survey_manifests", help="Output directory for hidden assignment and reader worklists.")
    parser.add_argument("--seed", type=int, default=20260601)
    args = parser.parse_args()

    prompts = read_prompts(Path(args.prompt_csv))
    image_root = Path(args.image_root)
    generation_rows = build_generation_rows(prompts, image_root)
    primary = assign_primary(generation_rows, seed=args.seed)
    duplicate_prompt_ids = choose_duplicate_prompt_ids(prompts, seed=args.seed)
    duplicates = assign_duplicates(generation_rows, primary, duplicate_prompt_ids, seed=args.seed)
    assignments = finalize_assignments(primary + duplicates, seed=args.seed)
    write_outputs(assignments, generation_rows, Path(args.output_dir))

    df = pd.DataFrame(assignments)
    print("Wrote survey assignment files to:", args.output_dir)
    print("Total ratings:", len(df))
    print("Unique generated images:", df["generated_image_id"].nunique())
    print("Duplicate ratings:", int(df["is_cross_validation_duplicate"].sum()))
    print("By reader:")
    print(df.groupby("reader_id").size())
    print("By reader/model:")
    print(df.groupby(["reader_id", "model_key"]).size().unstack(fill_value=0))
    print("By duplicate model:")
    print(df[df["is_cross_validation_duplicate"] == 1].groupby("model_key").size())
    missing = [r for r in generation_rows if not r["image_exists"]]
    if missing:
        print(f"WARNING: {len(missing)} image paths were not found under {image_root}.")
        print("First missing examples:")
        for r in missing[:10]:
            print(" ", r["image_path"])


if __name__ == "__main__":
    main()
