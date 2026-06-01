import streamlit as st
import os
import time
import hashlib
import csv
from pathlib import Path
from datetime import datetime
from PIL import Image

try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
except Exception:
    gspread = None
    ServiceAccountCredentials = None

# =========================================================
# Bilingual helper
# =========================================================
def b(ko: str, en: str) -> str:
    return f"{ko} / {en}"

# =========================================================
# Study / App Config
# =========================================================
APP_VERSION = "M2SMF_EXTERNAL_SYNTH_QA_v1.0"
STUDY_ID = "M2SMF_External_Synthetic_CXR_QA_300"
SHEET_NAME = "M2SMF_external_synth_QA_survey"

READER_CONFIG = {
    "professor_1": {"display_name": "Professor 1", "worksheet_name": "Professor_1"},
    "professor_2": {"display_name": "Professor 2", "worksheet_name": "Professor_2"},
    "professor_3": {"display_name": "Professor 3", "worksheet_name": "Professor_3"},
    "professor_4": {"display_name": "Professor 4", "worksheet_name": "Professor_4"},
}
READER_OPTIONS = list(READER_CONFIG.keys())

# The hidden assignment must be kept from readers. The app uses it internally only.
ASSIGNMENT_PATH_CANDIDATES = [
    "survey_manifests/M2SMF_external_QA_hidden_assignment.csv",
    "M2SMF_external_QA_hidden_assignment.csv",
    "./M2SMF_external_QA_hidden_assignment.csv",
    "/mnt/data/M2SMF_external_QA_hidden_assignment.csv",
]
IMAGE_ROOT_CANDIDATES = [".", "./images", "/mnt/data"]
LOCAL_RESULT_DIR = "local_survey_results"

# Reader-facing sheet intentionally does not include generator/prompt/disease/age/sex.
SHEET_HEADERS = [
    "timestamp",
    "study_id",
    "app_version",
    "reader_id",
    "assignment_id",
    "reader_sequence",
    "blinded_image_id",
    "blinded_filename",
    "case_hash",
    "is_frontal_cxr_like_yesno",
    "quality_score_1to5",
    "release_recommend_yesno",
    "clinical_issue_yesno",
    "downstream_ai_confusion_risk_yesno",
    "artifact_marker_OXN",
    "artifact_density_OXN",
    "artifact_gas_lucency_OXN",
    "artifact_boundaries_OXN",
    "artifact_anterior_ribs_OXN",
    "artifact_wavy_clavicle_OXN",
    "artifact_organ_shape_OXN",
    "artifact_global_quality_fov_crop_OXN",
    "other_flag_yesno",
    "main_rejection_reason",
    "comment",
    "time_spent_sec",
]

ARTIFACTS = [
    {
        "key": "marker",
        "ko": "1) 위치 마커/문자/라벨 이상",
        "en": "1) Marker/text/label artifact",
        "desc_ko": "L/R 마커, 문자, 병원 로고, 표시선, 비현실적 텍스트 또는 라벨이 보임",
        "desc_en": "Visible L/R marker, text, logo, line, non-radiographic label, or unrealistic typography",
    },
    {
        "key": "density",
        "ko": "2) 비현실적 투과도/밀도 artifact",
        "en": "2) Unrealistic density/penetration artifact",
        "desc_ko": "병변처럼 보일 수 있는 비현실적 음영, 얼룩, 과도한 smoothing, 물리적으로 어색한 density",
        "desc_en": "Unrealistic opacity, blotch, over-smoothing, or physically implausible density that could mimic pathology",
    },
    {
        "key": "gas_lucency",
        "ko": "3) 비현실적 gas/lucency pattern",
        "en": "3) Unrealistic gas/lucency pattern",
        "desc_ko": "상복부/하부 흉부의 gas, lucency, diaphragm 아래 음영이 해부학적으로 부자연스러움",
        "desc_en": "Unrealistic gas/lucency around the lower chest/upper abdomen or below the diaphragm",
    },
    {
        "key": "boundaries",
        "ko": "4) 해부학적 경계 불명확/붕괴",
        "en": "4) Vague or collapsed anatomical boundaries",
        "desc_ko": "심장, 종격동, 횡격막, 폐야, 피부/연조직 경계가 흐리거나 구조적으로 붕괴",
        "desc_en": "Blurred or collapsed borders of heart, mediastinum, diaphragm, lungs, skin/soft tissue",
    },
    {
        "key": "anterior_ribs",
        "ko": "5) 전방 늑골 소실/끊김/왜곡",
        "en": "5) Missing/broken/distorted anterior ribs",
        "desc_ko": "전방 늑골이 비현실적으로 사라지거나 끊기거나, 늑골 구조가 병변처럼 왜곡됨",
        "desc_en": "Anterior ribs disappear, break, or distort unrealistically and may mimic or obscure disease",
    },
    {
        "key": "wavy_clavicle",
        "ko": "6) 쇄골 형태 이상",
        "en": "6) Wavy or abnormal clavicle",
        "desc_ko": "쇄골 윤곽이 물결 모양, 울퉁불퉁, 비대칭으로 부자연스러움. 단독으로는 low-quality 결정 근거가 아닐 수 있음",
        "desc_en": "Clavicle contour is wavy, bumpy, or asymmetric. This alone may not define low quality",
    },
    {
        "key": "organ_shape",
        "ko": "7) 장기/심장/종격동/횡격막 형태 이상",
        "en": "7) Abnormal organ, cardiac, mediastinal, or diaphragm shape",
        "desc_ko": "심장, 종격동, 횡격막, 폐야 형태가 해부학적으로 불가능하거나 비현실적",
        "desc_en": "Heart, mediastinum, diaphragm, or lung contour is anatomically impossible or unrealistic",
    },
    {
        "key": "global_quality_fov_crop",
        "ko": "8) 전반적 non-diagnostic 품질/FOV/crop 문제",
        "en": "8) Global non-diagnostic quality, FOV, or crop problem",
        "desc_ko": "폐야/흉곽이 잘리거나, PA CXR로 보기 어렵거나, 전반적 품질 때문에 연구/AI 학습에 부적절",
        "desc_en": "Lung/chest is cropped, image is not a usable PA CXR, or global quality is unsuitable for research/AI training",
    },
]

REJECTION_REASONS = [
    "",
    "No major issue / release acceptable",
    "Non-CXR or not frontal PA CXR-like",
    "Global FOV/crop/non-diagnostic quality problem",
    "Unrealistic density/opacity that could mimic disease",
    "Unrealistic gas/lucency or diaphragm/lower chest problem",
    "Rib/bone anatomy distortion",
    "Cardiac/mediastinal/diaphragm/organ shape distortion",
    "Boundary collapse or blurred anatomy",
    "Marker/text/label artifact only",
    "Multiple artifacts",
    "Other",
]

st.set_page_config(page_title=b("외부 합성 CXR QA 설문", "External Synthetic CXR QA Survey"), layout="wide")

# =========================================================
# Google Sheets and local fallback
# =========================================================
def get_google_sheet(reader_id: str):
    if gspread is None or ServiceAccountCredentials is None:
        return None
    try:
        scope = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        if "gcp_service_account" not in st.secrets:
            return None
        creds_dict = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sh = client.open(SHEET_NAME)
        worksheet_name = READER_CONFIG[reader_id]["worksheet_name"]
        try:
            ws = sh.worksheet(worksheet_name)
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet(title=worksheet_name, rows=1000, cols=len(SHEET_HEADERS))
        return ws
    except Exception as e:
        st.sidebar.error(b("Google Sheet 연결 실패", "Google Sheet connection failed") + f": {e}")
        return None


def ensure_sheet_header(sheet):
    if not sheet:
        return
    try:
        values = sheet.get_all_values()
        if len(values) == 0:
            sheet.append_row(SHEET_HEADERS)
        elif values[0] != SHEET_HEADERS:
            st.warning(
                b(
                    "⚠️ Google Sheet 헤더가 현재 앱과 다릅니다. 새 워크시트 또는 새 시트를 권장합니다.",
                    "⚠️ Google Sheet header differs from this app. A new worksheet/sheet is recommended.",
                )
            )
    except Exception as e:
        st.sidebar.error(b("Google Sheet 헤더 확인 실패", "Google Sheet header check failed") + f": {e}")


def local_result_path(reader_id: str) -> str:
    os.makedirs(LOCAL_RESULT_DIR, exist_ok=True)
    return os.path.join(LOCAL_RESULT_DIR, f"{STUDY_ID}_{reader_id}.csv")


def append_local_result(reader_id: str, row: list):
    path = local_result_path(reader_id)
    new_file = not os.path.exists(path)
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(SHEET_HEADERS)
        writer.writerow(row)


def load_processed_assignment_ids(sheet, reader_id: str):
    processed = set()
    # Google Sheet rows
    if sheet:
        try:
            rows = sheet.get_all_values()
            if len(rows) > 1:
                header = rows[0]
                idx_study = header.index("study_id") if "study_id" in header else 1
                idx_reader = header.index("reader_id") if "reader_id" in header else 3
                idx_assignment = header.index("assignment_id") if "assignment_id" in header else 4
                for row in rows[1:]:
                    if len(row) <= max(idx_study, idx_reader, idx_assignment):
                        continue
                    if row[idx_study] == STUDY_ID and row[idx_reader] == reader_id:
                        processed.add(row[idx_assignment])
        except Exception:
            pass
    # Local fallback rows
    path = local_result_path(reader_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("study_id") == STUDY_ID and row.get("reader_id") == reader_id:
                        processed.add(row.get("assignment_id", ""))
        except Exception:
            pass
    return processed

# =========================================================
# Assignment / image loading
# =========================================================
@st.cache_data
def load_assignment():
    for path in ASSIGNMENT_PATH_CANDIDATES:
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                rows = [row for row in csv.DictReader(f)]
            required_cols = [
                "assignment_id",
                "reader_id",
                "reader_sequence",
                "blinded_image_id",
                "blinded_filename",
                "case_hash",
                "image_relpath",
                "image_path",
                "generated_image_id",
                "prompt_id",
                "model_key",
            ]
            missing = [c for c in required_cols if len(rows) == 0 or c not in rows[0]]
            if missing:
                raise RuntimeError(f"Assignment CSV is missing columns: {missing}")
            return rows, path
    raise FileNotFoundError(
        "Hidden assignment manifest not found. Expected one of: " + ", ".join(ASSIGNMENT_PATH_CANDIDATES)
    )


def resolve_image_path(row: dict) -> str:
    candidates = []
    for key in ["image_path", "image_relpath"]:
        val = row.get(key, "")
        if val:
            candidates.append(val)
            for root in IMAGE_ROOT_CANDIDATES:
                candidates.append(os.path.join(root, val))
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate

    # Fallback: search by folder/name or basename.
    rel = row.get("image_relpath", "")
    basename = os.path.basename(rel or row.get("image_path", ""))
    if basename:
        for root in IMAGE_ROOT_CANDIDATES:
            if not os.path.exists(root):
                continue
            for dirpath, _, filenames in os.walk(root):
                if basename in filenames:
                    candidate = os.path.join(dirpath, basename)
                    norm_candidate = os.path.normpath(candidate).replace("\\", "/")
                    norm_rel = os.path.normpath(rel).replace("\\", "/")
                    if norm_rel and norm_candidate.endswith(norm_rel):
                        return candidate
    return row.get("image_path") or row.get("image_relpath")


@st.cache_data(ttl=3600)
def resize_image_pil(image_path, max_height=960):
    try:
        img = Image.open(image_path).convert("RGB")
        if img.height <= max_height:
            return img
        aspect_ratio = img.width / img.height
        new_width = int(max_height * aspect_ratio)
        return img.resize((new_width, max_height), Image.LANCZOS)
    except Exception:
        return None


def artifact_radio(artifact: dict, case_key: str):
    st.markdown(f"**{b(artifact['ko'], artifact['en'])}**")
    st.caption(b(artifact["desc_ko"], artifact["desc_en"]))
    return st.radio(
        b("선택", "Select"),
        options=[
            b("X(없음)", "X(None)"),
            b("O(있음)", "O(Present)"),
            b("N/A(판단 불가)", "N/A(Unable to judge)"),
        ],
        index=0,
        horizontal=True,
        key=f"artifact_{artifact['key']}_{case_key}",
        label_visibility="collapsed",
    )


def is_select_placeholder(value: str) -> bool:
    return value == b("선택", "Select") or value == ""

# =========================================================
# Main
# =========================================================
def main():
    st.title("🩻 " + b("외부 합성 CXR 품질 보증 설문", "External Synthetic CXR Quality Assurance Survey"))
    st.caption(
        b(
            "본 설문은 Nano Banana, Sana, ChatGPT Images 2.0, RoentGen-v2로 생성된 합성 CXR를 실제 연구/AI 학습 데이터로 사용해도 되는지 평가하기 위한 블라인드 설문입니다.",
            "This blinded survey evaluates whether synthetic CXRs generated by Nano Banana, Sana, ChatGPT Images 2.0, and RoentGen-v2 are suitable for research/AI training.",
        )
    )

    st.sidebar.header(b("참여자 설정", "Participant Setup"))
    reader_id = st.sidebar.selectbox(
        b("평가자 코드", "Reader ID"),
        options=READER_OPTIONS,
        index=0,
        format_func=lambda x: f"{x} - {READER_CONFIG[x]['display_name']}",
    )

    if st.session_state.get("active_reader_id") != reader_id:
        st.session_state["active_reader_id"] = reader_id
        st.session_state["timer_assignment_id"] = None
        st.session_state["case_start_time"] = time.time()
        st.session_state["current_index"] = 0

    consent = st.sidebar.checkbox(b("연구 안내를 읽었습니다.", "I have read the study information."))
    if not consent:
        st.warning(b("설문을 진행하려면 동의 체크가 필요합니다.", "Please check consent to proceed."))
        st.stop()

    st.sidebar.divider()
    st.sidebar.markdown("**" + b("평가 원칙", "Rating Principles") + "**")
    st.sidebar.markdown("- " + b("generator, prompt, 병명, 나이, 성별은 블라인드 처리됩니다.", "Generator, prompt, disease, age, and sex are blinded."))
    st.sidebar.markdown("- " + b("질병 진단 정확도를 평가하는 것이 아니라, 합성 이미지가 연구/AI 학습용으로 안전한지 평가합니다.", "This is not a diagnosis task; evaluate whether the synthetic image is safe for research/AI training."))
    st.sidebar.markdown("- " + b("marker 단독은 임상적으로 중요한 low-quality 근거가 아닐 수 있습니다.", "Marker alone may not constitute clinically meaningful low quality."))
    st.sidebar.markdown("- " + b("병변처럼 보일 수 있는 합성 artifact가 downstream AI를 혼동시킬 위험을 특히 기록해주세요.", "Please specifically note artifacts that could be confused with pathology by downstream AI."))

    try:
        all_rows, assignment_path = load_assignment()
    except Exception as e:
        st.error(b("assignment manifest 로딩 실패", "Assignment manifest loading failed") + f": {e}")
        st.stop()

    assigned_cases = [r for r in all_rows if r.get("reader_id") == reader_id]
    assigned_cases = sorted(assigned_cases, key=lambda x: int(x["reader_sequence"]))
    total_cases = len(assigned_cases)
    if total_cases != 100:
        st.sidebar.warning(b("이 평가자의 케이스 수가 100장이 아닙니다", "This reader does not have exactly 100 cases") + f": {total_cases}")
    else:
        st.sidebar.success(b("할당 케이스", "Assigned cases") + f": {total_cases}")

    sheet = get_google_sheet(reader_id)
    if sheet:
        ensure_sheet_header(sheet)
        st.sidebar.caption(b("Google Sheet 연결됨", "Google Sheet connected") + f": {SHEET_NAME}/{READER_CONFIG[reader_id]['worksheet_name']}")
    else:
        st.sidebar.warning(b("Google Sheet 미연결: local CSV로 저장합니다.", "Google Sheet not connected: saving to local CSV."))
        st.sidebar.caption(local_result_path(reader_id))

    processed_ids = load_processed_assignment_ids(sheet, reader_id)
    start_index = total_cases
    for i, c in enumerate(assigned_cases):
        if c["assignment_id"] not in processed_ids:
            start_index = i
            break
    st.session_state["current_index"] = start_index

    if st.session_state["current_index"] >= total_cases:
        st.success(b("🎉 모든 평가 케이스가 완료되었습니다. 감사합니다!", "🎉 All assigned cases are complete. Thank you!"))
        st.balloons()
        return

    current_idx = st.session_state["current_index"]
    case = assigned_cases[current_idx]
    assignment_id = case["assignment_id"]
    case_hash = case.get("case_hash") or hashlib.sha1(assignment_id.encode()).hexdigest()[:10]
    image_path = resolve_image_path(case)

    if st.session_state.get("timer_assignment_id") != assignment_id:
        st.session_state["timer_assignment_id"] = assignment_id
        st.session_state["case_start_time"] = time.time()

    st.progress(current_idx / max(total_cases, 1))
    col_p1, col_p2, col_p3 = st.columns([1, 1, 1])
    with col_p1:
        st.caption(b("진행", "Progress") + f": **{current_idx + 1} / {total_cases}**")
    with col_p2:
        st.caption(b("블라인드 이미지 ID", "Blinded image ID") + f": `{case['blinded_image_id']}`")
    with col_p3:
        st.caption(f"Case ID: `{case_hash}`")
    st.divider()

    if not image_path or not os.path.exists(image_path):
        st.error(
            b(
                "이미지 파일을 찾지 못했습니다. image_root와 gpt/gemini/roentgen/sana 폴더 위치를 확인해주세요.",
                "Image file not found. Please check image_root and gpt/gemini/roentgen/sana folder paths.",
            )
            + f"\n\n`{image_path}`"
        )
        st.stop()

    col_left, col_right = st.columns([1.05, 0.95], gap="large")

    with col_left:
        st.subheader(b("평가 대상 이미지", "Target Image"))
        img = resize_image_pil(image_path, max_height=1050)
        if img is not None:
            st.image(img, use_container_width=True)
        else:
            st.image(image_path, use_container_width=True)
        st.caption(b("화면에는 generator/prompt/병명/나이/성별이 표시되지 않습니다.", "Generator/prompt/disease/age/sex are intentionally not shown."))

    with col_right:
        st.subheader("📝 " + b("평가 입력", "Rating Form"))
        qa_box = st.container(height=790, border=True)
        with qa_box:
            with st.form(key=f"form_{reader_id}_{assignment_id}"):
                # st.markdown("##### " + b("1) 전반적 사용 가능성", "1) Overall usability"))

                # with st.expander(b("품질 점수 기준 보기", "Show quality score criteria"), expanded=False):
                #     st.markdown(
                #         "- **1**: " + b("비진단적/심한 합성 artifact로 연구·AI 학습 데이터로 사용 부적절", "Non-diagnostic or severe synthetic artifact; unsuitable for research/AI training") + "\n"
                #         "- **2**: " + b("명확한 합성 artifact가 있어 사용 위험", "Clear synthetic artifacts; risky to use") + "\n"
                #         "- **3**: " + b("경계선. 일부는 자연스럽지만 artifact 또는 구조 불일치가 의심", "Borderline; partly natural but suspicious artifacts or structural inconsistency") + "\n"
                #         "- **4**: " + b("대부분 자연스럽고 연구·AI 학습에 사용 가능해 보임", "Mostly natural and appears usable for research/AI training") + "\n"
                #         "- **5**: " + b("실제 PA CXR와 구별이 어렵고 전반적으로 매우 자연스러움", "Very hard to distinguish from real PA CXR; highly natural overall")
                #     )

                # is_frontal = st.selectbox(
                #     b("A) 이 이미지는 frontal PA CXR처럼 보입니까?", "A) Does this look like a frontal PA CXR?"),
                #     options=[b("선택", "Select"), "Yes", "No", "Unclear"],
                #     index=0,
                #     key=f"frontal_{assignment_id}",
                # )
                # quality_score = st.selectbox(
                #     b("B) 합성 CXR 품질 점수", "B) Synthetic CXR quality score"),
                #     options=[b("선택", "Select"), "1", "2", "3", "4", "5"],
                #     index=0,
                #     key=f"quality_{assignment_id}",
                # )
                # release = st.selectbox(
                #     b("C) 실제 연구/AI 학습 데이터로 사용 가능하다고 보십니까?", "C) Suitable for real research/AI training data?"),
                #     options=[b("선택", "Select"), "Yes", "No"],
                #     index=0,
                #     key=f"release_{assignment_id}",
                # )
                # clinical_issue = st.selectbox(
                #     b("D) 임상적으로 중요한 합성 artifact 또는 비진단적 품질 문제가 있습니까?", "D) Clinically meaningful synthetic artifact or non-diagnostic quality issue?"),
                #     options=[b("선택", "Select"), "Yes", "No", "Unclear"],
                #     index=0,
                #     key=f"clinical_issue_{assignment_id}",
                # )
                # downstream_risk = st.selectbox(
                #     b(
                #         "E) downstream AI가 병변 표현과 합성 artifact를 혼동할 위험이 있다고 보십니까?",
                #         "E) Risk that downstream AI could confuse synthetic artifact with pathology?",
                #     ),
                #     options=[b("선택", "Select"), "Yes", "No", "Unclear"],
                #     index=0,
                #     key=f"downstream_risk_{assignment_id}",
                # )

                st.markdown("---")
                st.markdown("##### " + b("2) Artifact checklist", "2) Artifact checklist"))
                st.caption(b("각 항목을 O/X/N/A로 평가해주세요.", "Rate each item as O/X/N/A."))
                artifact_values = {}
                for art in ARTIFACTS:
                    artifact_values[art["key"]] = artifact_radio(art, assignment_id)
                    st.markdown("")

                st.markdown("---")
                # st.markdown("##### " + b("3) 주요 사유와 코멘트", "3) Main reason and comment"))
                # other_flag = st.selectbox(
                #     b("기타 부자연스러움이 있습니까?", "Any other unnatural finding?"),
                #     options=[b("선택", "Select"), "Yes", "No"],
                #     index=0,
                #     key=f"other_{assignment_id}",
                # )
                # main_reason = st.selectbox(
                #     b("주요 reject/review 사유", "Main reject/review reason"),
                #     options=REJECTION_REASONS,
                #     index=0,
                #     key=f"reason_{assignment_id}",
                # )
                # comment = st.text_area(
                #     b("코멘트 — 부자연스러운 부위/이유를 짧게 기록", "Comment — brief location/reason"),
                #     height=90,
                #     placeholder=b("예: 우측 하폐야 음영이 병변처럼 보이지만 해부학적으로 부자연스러움.", "e.g., Right lower lung opacity looks pathology-like but anatomically unnatural."),
                #     key=f"comment_{assignment_id}",
                # )
                confirm_all_checked = st.checkbox(
                    b("위 8개 artifact 항목을 모두 확인했습니다.", "I have reviewed all 8 artifact items."),
                    key=f"confirm_{assignment_id}",
                )
                submit = st.form_submit_button(b("💾 저장하고 다음으로", "💾 Save & Next"), type="primary", use_container_width=True)

        if submit:
            errors = []
            if is_select_placeholder(is_frontal):
                errors.append(b("frontal PA CXR 여부를 선택해주세요.", "Please select whether this is a frontal PA CXR."))
            if is_select_placeholder(quality_score):
                errors.append(b("품질 점수(1–5)를 선택해주세요.", "Please select a quality score."))
            if is_select_placeholder(release):
                errors.append(b("연구/AI 학습 데이터 사용 가능 여부를 선택해주세요.", "Please select suitability for research/AI training."))
            if is_select_placeholder(clinical_issue):
                errors.append(b("clinical issue 여부를 선택해주세요.", "Please select clinical issue status."))
            if is_select_placeholder(downstream_risk):
                errors.append(b("downstream AI 혼동 위험 여부를 선택해주세요.", "Please select downstream AI confusion risk."))
            if is_select_placeholder(other_flag):
                errors.append(b("기타 부자연스러움 여부를 선택해주세요.", "Please select other-flag status."))
            if not main_reason:
                errors.append(b("주요 reject/review 사유를 선택해주세요.", "Please select the main reject/review reason."))
            if (other_flag == "Yes" or main_reason == "Other") and not comment.strip():
                errors.append(b("기타/Other인 경우 코멘트를 작성해주세요.", "If Other is selected, please write a comment."))
            if not confirm_all_checked:
                errors.append(b("artifact 8개 항목 확인 체크가 필요합니다.", "Please confirm all 8 artifact items were reviewed."))

            if errors:
                for e in errors:
                    st.error("⚠️ " + e)
            else:
                elapsed = max(0.0, time.time() - st.session_state.get("case_start_time", time.time()))
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                row = [
                    timestamp,
                    STUDY_ID,
                    APP_VERSION,
                    reader_id,
                    assignment_id,
                    str(case["reader_sequence"]),
                    case["blinded_image_id"],
                    case["blinded_filename"],
                    case_hash,
                    is_frontal,
                    quality_score,
                    release,
                    clinical_issue,
                    downstream_risk,
                    artifact_values["marker"],
                    artifact_values["density"],
                    artifact_values["gas_lucency"],
                    artifact_values["boundaries"],
                    artifact_values["anterior_ribs"],
                    artifact_values["wavy_clavicle"],
                    artifact_values["organ_shape"],
                    artifact_values["global_quality_fov_crop"],
                    other_flag,
                    main_reason,
                    comment.strip(),
                    f"{elapsed:.2f}",
                ]
                saved_to_sheet = False
                if sheet:
                    try:
                        sheet.append_row(row)
                        saved_to_sheet = True
                    except Exception as e:
                        st.error(b("Google Sheet 저장 중 오류. local CSV에도 저장합니다.", "Google Sheet save failed. Saving to local CSV as backup.") + f": {e}")
                append_local_result(reader_id, row)
                if saved_to_sheet:
                    st.toast(b("✅ 저장 완료", "✅ Saved") + f" ({current_idx + 1}/{total_cases})")
                else:
                    st.toast(b("✅ local CSV 저장 완료", "✅ Saved to local CSV") + f" ({current_idx + 1}/{total_cases})")
                st.rerun()


if __name__ == "__main__":
    main()
