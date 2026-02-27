import streamlit as st
import os
import time
import random
import hashlib
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from PIL import Image

# =========================================================
# Bilingual helper (Korean / English)
# =========================================================
def b(ko: str, en: str) -> str:
    return f"{ko} / {en}"

# =========================================================
# Study / App Config (npjDM-friendly)
# =========================================================
APP_VERSION = "M2SMF_QA_SURVEY_v1.0"
STUDY_ID = "M2SMF_Synthetic_CXR_QA"

NUM_RATERS = 4
RATER_OPTIONS = [b("선택", "Select")] + [f"R{i}" for i in range(1, NUM_RATERS + 1)]

# Each rater sees 50 total (25 HQ + 25 LQ) by default
N_HQ_PER_RATER = 25
N_LQ_PER_RATER = 25

# --- Optional (HIGHLY RECOMMENDED for npjDM): Anchor set for inter-rater agreement ---
ENABLE_ANCHOR_SET = True
ANCHOR_HQ = 5
ANCHOR_LQ = 5

# Folder settings
HQ_FOLDERS = ["roentgen_75_440"]  # high quality generation setting (hidden from rater)
LQ_FOLDERS = ["roentgen_10_440"]  # low quality generation setting (hidden from rater)

# Example images folder for artifact guidance
EXAMPLE_IMAGES_DIR = "images"

# Streamlit page
st.set_page_config(
    page_title=b("합성 CXR 품질 평가(QA)", "Synthetic CXR Quality Assessment (QA)"),
    layout="wide"
)

# =========================================================
# Google Sheets
# =========================================================
SHEET_NAME = "M2SMF_survey"
WORKSHEET_INDEX = 0  # sheet1

SHEET_HEADERS = [
    "timestamp",
    "study_id",
    "app_version",
    "rater_id",
    "case_order",
    "case_hash",
    "image_id",
    "source_quality_hidden",
    "quality_score_1to5",
    "release_recommend_yesno",
    "artifact_marker_OXN",
    "artifact_density_OXN",
    "artifact_gas_OXN",
    "artifact_boundaries_OXN",
    "artifact_anterior_ribs_OXN",
    "artifact_wavy_clavicle_OXN",
    "artifact_organ_shape_OXN",
    "other_flag_yesno",
    "comment",
    "time_spent_sec",
]

def get_google_sheet(rater_id: str):
    """
    Rater별 워크시트(탭)에 기록. / Log to each rater worksheet(tab).
    - 탭 이름: R1, R2, R3, R4
    - 없으면 자동 생성 / Auto-create if not exists
    """
    try:
        scope = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        if "gcp_service_account" not in st.secrets:
            return None

        creds_dict = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)

        sh = client.open(SHEET_NAME)

        try:
            ws = sh.worksheet(rater_id)
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet(title=rater_id, rows=2000, cols=len(SHEET_HEADERS))

        return ws
    except Exception as e:
        st.sidebar.error(b("Google Sheet 연결 실패", "Google Sheet connection failed") + f": {e}")
        return None


def ensure_sheet_header(sheet):
    """Create header row if sheet is empty or header mismatch."""
    try:
        values = sheet.get_all_values()
        if len(values) == 0:
            sheet.append_row(SHEET_HEADERS)
            return
        if values[0] != SHEET_HEADERS:
            st.warning(b("⚠️ Google Sheet의 헤더가 현재 앱과 다릅니다. (새 워크시트/새 시트 사용을 권장)",
                         "⚠️ Google Sheet header differs from this app. (Recommended: use a new worksheet/sheet)"))
    except Exception as e:
        st.sidebar.error(b("Google Sheet 연결 실패", "Google Sheet connection failed") + f": {e}")
        return None


def load_processed_image_ids(sheet, rater_id: str):
    """Return a set of image_ids already rated by this rater in this study."""
    processed = set()
    if not sheet:
        return processed
    try:
        rows = sheet.get_all_values()
        if len(rows) <= 1:
            return processed
        header = rows[0]
        idx_study = header.index("study_id") if "study_id" in header else 1
        idx_rater = header.index("rater_id") if "rater_id" in header else 3
        idx_imgid = header.index("image_id") if "image_id" in header else 6

        for row in rows[1:]:
            if len(row) <= max(idx_study, idx_rater, idx_imgid):
                continue
            if row[idx_study] == STUDY_ID and row[idx_rater] == rater_id:
                processed.add(row[idx_imgid])
    except Exception:
        pass
    return processed


# =========================================================
# Image Loading
# =========================================================
@st.cache_data
def load_image_paths(target_folders):
    image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'}
    image_paths = []
    for folder in target_folders:
        if os.path.exists(folder):
            for root, _, files in os.walk(folder):
                for file in files:
                    if os.path.splitext(file)[1].lower() in image_extensions:
                        image_paths.append(os.path.join(root, file))
    return sorted(image_paths)

def make_image_id(image_path: str) -> str:
    folder = os.path.basename(os.path.dirname(image_path))
    fname = os.path.basename(image_path)
    return f"{folder}/{fname}"

def hash_case(image_id: str) -> str:
    return hashlib.sha1(image_id.encode("utf-8")).hexdigest()[:10]


def get_example_image_path(question_key):
    mapping = {
        "marker_error": "texture1.png",
        "density_penetration": "texture2.png",
        "abnormal_gas": "texture3.png",
        "vague_boundaries": "anatomy1.png",
        "anterior_ribs": "anatomy2.png",
        "wavy_clavicle": "anatomy3.png",
        "abnormal_organ_shape": "anatomy4.png",
    }
    filename = mapping.get(question_key)
    if filename:
        return os.path.join(EXAMPLE_IMAGES_DIR, filename)
    return None

@st.cache_data(ttl=3600)
def resize_image_pil(image_path, target_height):
    try:
        img = Image.open(image_path)
        aspect_ratio = img.width / img.height
        new_width = int(target_height * aspect_ratio)
        resized_img = img.resize((new_width, target_height), Image.LANCZOS)
        return resized_img
    except Exception:
        return None


# =========================================================
# Assignment (balanced + blinded)
# =========================================================
def build_case_list_for_rater(hq_paths, lq_paths, rater_id: str):
    """
    Deterministic, disjoint assignment across raters:
      - partition each pool by rater_index using slicing [idx::NUM_RATERS]
      - sample N_HQ_PER_RATER and N_LQ_PER_RATER from each partition
      - shuffle order with a fixed seed for reproducibility
    """
    rater_index = int(rater_id.replace("R", "")) - 1
    rng = random.Random(f"{STUDY_ID}_{APP_VERSION}_{rater_id}")

    hq_partition = hq_paths[rater_index::NUM_RATERS]
    lq_partition = lq_paths[rater_index::NUM_RATERS]

    if len(hq_partition) < N_HQ_PER_RATER or len(lq_partition) < N_LQ_PER_RATER:
        raise RuntimeError(b("이미지 수가 부족합니다. 폴더/이미지 수를 확인하세요.",
                             "Not enough images. Please check folders/image counts."))

    anchors = []
    if ENABLE_ANCHOR_SET:
        anchor_rng = random.Random(f"{STUDY_ID}_{APP_VERSION}_ANCHOR")
        hq_anchor = anchor_rng.sample(hq_paths, ANCHOR_HQ)
        lq_anchor = anchor_rng.sample(lq_paths, ANCHOR_LQ)
        anchor_ids = set([make_image_id(p) for p in (hq_anchor + lq_anchor)])
        for p in hq_anchor:
            anchors.append({"path": p, "source_quality": "HQ"})
        for p in lq_anchor:
            anchors.append({"path": p, "source_quality": "LQ"})
    else:
        anchor_ids = set()

    hq_partition_filtered = [p for p in hq_partition if make_image_id(p) not in anchor_ids]
    lq_partition_filtered = [p for p in lq_partition if make_image_id(p) not in anchor_ids]

    n_hq_unique = N_HQ_PER_RATER
    n_lq_unique = N_LQ_PER_RATER
    if ENABLE_ANCHOR_SET:
        n_hq_unique = max(0, N_HQ_PER_RATER - ANCHOR_HQ)
        n_lq_unique = max(0, N_LQ_PER_RATER - ANCHOR_LQ)

    hq_selected = rng.sample(hq_partition_filtered, n_hq_unique)
    lq_selected = rng.sample(lq_partition_filtered, n_lq_unique)

    cases = []
    for c in anchors:
        cases.append(c)

    for p in hq_selected:
        cases.append({"path": p, "source_quality": "HQ"})
    for p in lq_selected:
        cases.append({"path": p, "source_quality": "LQ"})

    rng.shuffle(cases)
    return cases


# =========================================================
# UI Helpers
# =========================================================
def artifact_radio(label_title_ko, label_title_en, description_ko, description_en, key_prefix, example_key=None):
    """
    Collect O/X/N/A per artifact item.
    """
    try:
        q_col, img_col = st.columns([7, 3], vertical_alignment="top")
    except TypeError:
        q_col, img_col = st.columns([7, 3])

    with q_col:
        st.markdown(f"**{b(label_title_ko, label_title_en)}**")
        if description_ko or description_en:
            st.caption(b(description_ko, description_en))

        choice = st.radio(
            b("선택", "Select"),
            options=[
                b("X(없음)", "X(None)"),
                b("O(있음)", "O(Present)"),
                b("N/A(판단 불가)", "N/A(Unable to judge)"),
            ],
            index=0,
            horizontal=True,
            key=key_prefix,
            label_visibility="collapsed"
        )

    with img_col:
        if example_key:
            example_path = get_example_image_path(example_key)
            if example_path and os.path.exists(example_path):
                resized = resize_image_pil(example_path, target_height=90)
                if resized:
                    st.image(resized, use_container_width=False)

    return choice


# =========================================================
# Main
# =========================================================
def main():
    st.title("🧪 " + b("합성 CXR 품질 평가(QA) 설문", "Synthetic CXR Quality Assessment (QA) Survey"))
    st.caption(b("본 설문은 진단(CADx)이 아니라 합성데이터의 공유/학습 적합성(QA)을 평가하기 위한 것입니다.",
                 "This survey is NOT for diagnosis (CADx). It evaluates the suitability of synthetic data for sharing/training (QA)."))

    # --- Sidebar: rater select + consent ---
    st.sidebar.header(b("참여자 설정", "Participant Setup"))
    rater_id = st.sidebar.selectbox(b("평가자 코드", "Rater ID"), options=RATER_OPTIONS, index=0)

    if rater_id == b("선택", "Select"):
        st.info(b("왼쪽 사이드바에서 평가자 코드를 선택해주세요.",
                  "Please select your rater ID from the left sidebar."))
        st.stop()

    # ✅ FIX 1: Detect rater change & reset per-rater session state
    if st.session_state.get("active_rater_id") != rater_id:
        st.session_state["active_rater_id"] = rater_id
        st.session_state["timer_case_idx"] = None
        st.session_state["case_start_time"] = time.time()

    consent = st.sidebar.checkbox(b("연구 안내를 읽었습니다.", "I have read the study information."))
    if not consent:
        st.warning(b("설문을 진행하려면 동의 체크가 필요합니다.",
                     "You must check consent to proceed."))
        st.stop()

    st.sidebar.divider()
    st.sidebar.markdown("**" + b("평가 원칙", "Rating Principles") + "**")
    st.sidebar.markdown("- " + b("질병 유무를 판독하는 설문이 아닙니다.", "This is not a disease detection/diagnosis task."))
    st.sidebar.markdown("- " + b("오로지 **합성 흔적/현실감/공유·학습 적합성** 관점에서 평가해주세요.",
                                 "Please rate ONLY based on **synthetic artifacts/realism/suitability for sharing & training**."))
    st.sidebar.markdown("- " + b("이미지 출처(HQ/LQ)는 표시되지 않습니다(블라인드).",
                                 "The source (HQ/LQ) is hidden (blinded)."))

    # Load images
    for folder in HQ_FOLDERS + LQ_FOLDERS + [EXAMPLE_IMAGES_DIR]:
        os.makedirs(folder, exist_ok=True)

    hq_paths = load_image_paths(HQ_FOLDERS)
    lq_paths = load_image_paths(LQ_FOLDERS)

    if len(hq_paths) == 0 or len(lq_paths) == 0:
        st.error(b("HQ/LQ 폴더에 이미지가 없습니다. 폴더 경로 및 파일을 확인해주세요.",
                   "No images found in HQ/LQ folders. Please check folder paths/files."))
        st.stop()

    # Build assignment
    try:
        assigned_cases = build_case_list_for_rater(hq_paths, lq_paths, rater_id)
    except Exception as e:
        st.error(b("케이스 할당 실패", "Case assignment failed") + f": {e}")
        st.stop()

    total_cases = len(assigned_cases)

    # Google Sheet
    sheet = get_google_sheet(rater_id)
    if sheet:
        ensure_sheet_header(sheet)
        st.sidebar.success(b("연결됨", "Connected") + f": {sheet.spreadsheet.title} / {sheet.title}")

    processed_ids = load_processed_image_ids(sheet, rater_id)

    # Find first unprocessed index
    start_index = total_cases
    for i, c in enumerate(assigned_cases):
        img_id = make_image_id(c["path"])
        if img_id not in processed_ids:
            start_index = i
            break

    # ✅ FIX 2: Always set current_index to start_index (computed per rater from sheet)
    st.session_state["current_index"] = start_index

    # Done?
    if st.session_state["current_index"] >= total_cases:
        st.success(b("🎉 모든 배정 케이스 평가가 완료되었습니다. 감사합니다!",
                     "🎉 You have completed all assigned cases. Thank you!"))
        st.balloons()
        return

    # Current case
    current_idx = st.session_state["current_index"]
    case = assigned_cases[current_idx]
    image_path = case["path"]
    image_id = make_image_id(image_path)
    case_hash = hash_case(image_id)

    # Timer init per case
    if st.session_state.get("timer_case_idx") != current_idx:
        st.session_state.timer_case_idx = current_idx
        st.session_state.case_start_time = time.time()

    # Progress UI
    st.progress(current_idx / total_cases)
    col1, col2 = st.columns([1, 1])
    with col1:
        st.caption(b("진행", "Progress") + f": **{current_idx + 1} / {total_cases}**")
    with col2:
        st.caption(f"Case ID: `{case_hash}`")
    st.divider()

    col_left, col_right = st.columns([1, 1], gap="large")

    with col_left:
        st.subheader(b("평가 대상 이미지", "Target Image"))
        st.image(image_path, use_container_width=True)

    with col_right:
        st.subheader("📝 " + b("평가 입력 (QA 목적)", "Rating Form (QA purpose)"))

        qa_box = st.container(height=720, border=True)

        with qa_box:
            with st.form(key=f"form_{rater_id}_{case_hash}"):

                with st.expander(b("품질 점수 기준(1–5) 보기", "Show quality score criteria (1–5)"), expanded=False):
                    st.markdown(
                        "- **" + b("1점(매우 낮음)", "1 (Very Low)") + "**: " + b("합성 흔적/비현실성이 뚜렷하여 데이터로 쓰기 어려움",
                                                                                    "Obvious synthetic artifacts/unrealism; hard to use as data") + "\n"
                        "- **" + b("2점(낮음)", "2 (Low)") + "**: " + b("인공적인 흔적이 자주 보여 품질이 낮다고 판단",
                                                                      "Frequent artificial artifacts; low quality") + "\n"
                        "- **" + b("3점(보통/애매)", "3 (Borderline)") + "**: " + b("일부는 자연스럽지만 일부는 의심/불일치(경계선)",
                                                                                  "Some parts look natural, others suspicious/inconsistent") + "\n"
                        "- **" + b("4점(높음)", "4 (High)") + "**: " + b("대부분 자연스럽고 데이터로 활용 가능해 보임",
                                                                       "Mostly natural; appears usable for data") + "\n"
                        "- **" + b("5점(매우 높음)", "5 (Very High)") + "**: " + b("실제와 구별이 매우 어렵고 전반적으로 매우 자연스러움",
                                                                                 "Very hard to distinguish from real; highly natural overall")
                    )

                quality_score = st.selectbox(
                    b("A) 합성 CXR 품질 점수 (1–5)", "A) Synthetic CXR quality score (1–5)"),
                    options=[b("선택", "Select"), "1", "2", "3", "4", "5"],
                    index=0,
                    key=f"quality_{case_hash}",
                )

                release = st.selectbox(
                    b("B) 데이터 공유/학습에 사용 가능(Release 추천) 여부",
                      "B) Suitable for sharing/training (Release recommendation)"),
                    options=[b("선택", "Select"), "Yes", "No"],
                    index=0,
                    key=f"release_{case_hash}",
                )

                st.markdown("---")
                st.markdown("##### **" + b("C) 합성 흔적(artifact) 체크리스트 (O/X/N/A)",
                                         "C) Synthetic artifact checklist (O/X/N/A)") + "**")
                st.caption(b("각 항목은 ‘있음(O) / 없음(X) / 판단 불가(N/A)’ 중 하나를 선택해주세요.",
                             "For each item, choose one: Present (O) / None (X) / Unable to judge (N/A)."))

                a_marker = artifact_radio(
                    "1) 위치 마커(L/R) 오류 (Marker Artifacts)",
                    "1) Incorrect position marker (L/R) (Marker Artifacts)",
                    "L/R 마커 반전, 위치 이상, 글자 형태 부자연스러움 등",
                    "Reversed L/R, abnormal placement, unnatural typography, etc.",
                    key_prefix=f"art_marker_{case_hash}",
                    example_key="marker_error"
                )
                a_density = artifact_radio(
                    "2) 비현실적 투과도/밀도 (Density & Penetration)",
                    "2) Unrealistic density/penetration (Density & Penetration)",
                    "얼룩, 물리적으로 어색한 밀도 표현(예: 뼈가 가장 하얗게 보이지 않음 등)",
                    "Blotches or physically implausible density (e.g., bones not appearing as the whitest structure)",
                    key_prefix=f"art_density_{case_hash}",
                    example_key="density_penetration"
                )
                a_gas = artifact_radio(
                    "3) 위장관/복부 가스 음영 오류 (Abnormal Gas Pattern)",
                    "3) Abnormal GI/abdominal gas shadow (Abnormal Gas Pattern)",
                    "하부 흉부/상복부 음영이 비현실적(가스/음영 패턴 이상)",
                    "Unrealistic lower chest/upper abdomen shadow (abnormal gas/opacities)",
                    key_prefix=f"art_gas_{case_hash}",
                    example_key="abnormal_gas"
                )

                st.markdown("---")

                a_boundary = artifact_radio(
                    "4) 구조물 경계 모호 (Vague Boundaries)",
                    "4) Vague structural boundaries (Vague Boundaries)",
                    "피부/장기/뼈 윤곽 경계가 전반적으로 흐리거나 붕괴",
                    "Overall blurred/collapsed outlines of skin/organs/bones",
                    key_prefix=f"art_boundary_{case_hash}",
                    example_key="vague_boundaries"
                )
                a_ribs = artifact_radio(
                    "5) 전방 늑골 소실/끊김 (Anterior Ribs)",
                    "5) Missing/broken anterior ribs (Anterior Ribs)",
                    "후방 늑골은 보이는데 전방 늑골이 약하거나 끊김",
                    "Posterior ribs visible but anterior ribs are weak/discontinuous",
                    key_prefix=f"art_ribs_{case_hash}",
                    example_key="anterior_ribs"
                )
                a_clavicle = artifact_radio(
                    "6) 쇄골 형태 이상 (Wavy clavicle)",
                    "6) Abnormal clavicle shape (Wavy clavicle)",
                    "쇄골 라인이 울퉁불퉁/물결 모양으로 부자연스러움",
                    "Clavicle line looks bumpy/wavy and unnatural",
                    key_prefix=f"art_clavicle_{case_hash}",
                    example_key="wavy_clavicle"
                )
                a_organ = artifact_radio(
                    "7) 장기 모양 기형 (Abnormal Organ Shape)",
                    "7) Abnormal organ contour (Abnormal Organ Shape)",
                    "심장/횡격막 등 장기 윤곽 자체가 비현실적",
                    "Unrealistic contours of heart/diaphragm, etc.",
                    key_prefix=f"art_organ_{case_hash}",
                    example_key="abnormal_organ_shape"
                )

                st.markdown("---")

                other_flag = st.selectbox(
                    b("D) 기타(위 항목 외의 부자연스러움) 존재 여부",
                      "D) Other unnatural findings (not listed above)"),
                    options=[b("선택", "Select"), "Yes", "No"],
                    index=0,
                    key=f"other_{case_hash}",
                )

                comment = st.text_area(
                    b("E) (선택) 코멘트 1줄 — 부자연스러운 부위/이유를 짧게 기록",
                      "E) (Optional) One-line comment — location/reason of unnaturalness"),
                    height=90,
                    placeholder=b("예: 우측 상폐야 경계가 비정상적으로 뭉개짐. / L 마커가 비정상적으로 왜곡됨.",
                                  "e.g., Right upper lung boundary is unnaturally blurred. / L marker is distorted."),
                    key=f"comment_{case_hash}",
                )

                confirm_all_checked = st.checkbox(
                    b("위 7개 artifact 항목을 모두 확인했습니다.",
                      "I have reviewed all 7 artifact items above."),
                    key=f"confirm_{case_hash}"
                )

                submit = st.form_submit_button(
                    b("💾 저장하고 다음으로", "💾 Save & Next"),
                    type="primary",
                    use_container_width=True
                )

        # Save logic (outside form)
        if submit:
            errors = []
            if quality_score == b("선택", "Select"):
                errors.append(b("품질 점수(1–5)를 선택해주세요.", "Please select a quality score (1–5)."))
            if release == b("선택", "Select"):
                errors.append(b("Release 추천(Yes/No)을 선택해주세요.", "Please select Release recommendation (Yes/No)."))
            if other_flag == b("선택", "Select"):
                errors.append(b("기타 여부(Yes/No)를 선택해주세요.", "Please select Other flag (Yes/No)."))
            if (other_flag == "Yes") and (not comment.strip()):
                errors.append(b("'기타=Yes'인 경우 코멘트를 1줄 작성해주세요.",
                                "If 'Other=Yes', please write a one-line comment."))
            if not confirm_all_checked:
                errors.append(b("artifact 7개 항목 확인 체크가 필요합니다.",
                                "Please confirm you reviewed all 7 artifact items."))

            if errors:
                for e in errors:
                    st.error("⚠️ " + e)
            else:
                elapsed = max(0.0, time.time() - st.session_state.get("case_start_time", time.time()))
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                source_quality = case["source_quality"]  # hidden label

                row = [
                    timestamp,
                    STUDY_ID,
                    APP_VERSION,
                    rater_id,
                    str(current_idx + 1),
                    case_hash,
                    image_id,
                    source_quality,
                    quality_score,
                    release,
                    a_marker,
                    a_density,
                    a_gas,
                    a_boundary,
                    a_ribs,
                    a_clavicle,
                    a_organ,
                    other_flag,
                    comment.strip(),
                    f"{elapsed:.2f}",
                ]

                if sheet:
                    try:
                        sheet.append_row(row)
                        st.toast(b("✅ 저장 완료", "✅ Saved") + f" (Case {current_idx + 1}/{total_cases})")
                        # current_index will be recomputed from sheet on rerun
                        st.rerun()
                    except Exception as e:
                        st.error(b("구글 시트 저장 중 오류", "Error while saving to Google Sheet") + f": {e}")
                else:
                    st.warning(b("⚠️ 구글 시트가 연결되지 않았습니다(테스트 모드).",
                                 "⚠️ Google Sheet not connected (test mode)."))
                    st.info(b("저장 데이터 미리보기", "Preview saved row") + f":\n{row}")
                    st.rerun()


if __name__ == "__main__":
    main()
