import streamlit as st
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# 1. 페이지 설정 (반드시 최상단에 위치)
st.set_page_config(page_title="합성 CXR 판독 도구", layout="wide")

# 2. Google Sheets 연결 함수
def get_google_sheet():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        # st.secrets에 저장된 서비스 계정 키 사용
        # (실제 배포 시 st.secrets 설정이 필요합니다. 로컬 테스트 시 json 파일 경로로 대체 가능)
        creds_dict = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        # 실제 사용할 스프레드시트 이름과 시트 이름으로 변경하세요
        sheet = client.open("labeling_results").sheet1
        return sheet
    except Exception as e:
        # st.error(f"구글 시트 연결 실패: {e}") # 연결 실패 메시지가 너무 자주 뜨면 주석 처리
        return None

# 3. 이미지 파일 리스트 불러오기
@st.cache_data
def load_image_paths(target_folders):
    image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'}
    image_paths = []

    for folder in target_folders:
        if os.path.exists(folder):
            for root, dirs, files in os.walk(folder):
                for file in files:
                    if os.path.splitext(file)[1].lower() in image_extensions:
                        image_paths.append(os.path.join(root, file))
        # else:
        #     st.warning(f"폴더를 찾을 수 없습니다: {folder}") # 불필요한 경고 제거

    return sorted(image_paths)

# --- [NEW] 예시 이미지 경로 함수 ---
# 각 질문 항목에 매칭될 예시 이미지의 경로를 반환하는 함수입니다.
# 실제 이미지 파일이 존재하는 경로로 수정해야 합니다.
def get_example_image_path(question_key):
    # 예시 이미지가 저장된 기본 폴더명 (실제 환경에 맞게 수정 필요)
    # 예: "assets/examples" 또는 "images" 등
    example_images_dir = "images"

    # 질문 키와 이미지 파일명 매핑
    mapping = {
        # Texture
        "marker_error": "texture1.png",
        "density_penetration": "texture2.png",
        "abnormal_gas": "texture3.png",

        # Anatomy
        "vague_boundaries": "anatomy1.png",
        "anterior_ribs": "anatomy2.png",
        "wavy_clavicle": "anatomy3.png",
        "abnormal_organ_shape": "anatomy4.png",
    }

    filename = mapping.get(question_key)
    if filename:
        # 실제 경로 조합
        return os.path.join(example_images_dir, filename)
    return None

# 4. 메인 로직
def main():
    st.title("🖼️ 합성 CXR 정밀 판독")

    # ---------------------------------------------------------
    # 초기 설정 및 데이터 로드
    # ---------------------------------------------------------
    # 작업할 폴더 리스트 (실제 존재하는 폴더명으로 수정 필요)
    target_folders = ["roentgen_10_440", "roentgen_75_440"]

    # 폴더가 실제로 있는지 확인 후 없는 폴더 생성 (테스트 용이성 위함)
    # 실제 운영 환경에서는 이 부분을 제거하고 기존 폴더를 사용하세요.
    for folder in target_folders:
        os.makedirs(folder, exist_ok=True)
    
    # images 폴더도 없다면 생성 (테스트 용)
    os.makedirs("images", exist_ok=True)


    all_images = load_image_paths(target_folders)
    total_images = len(all_images)

    if total_images == 0:
        st.error(f"지정된 폴더들({target_folders})에 이미지가 없습니다. 이미지를 넣어주세요.")
        # 테스트를 위한 가이드
        st.info("💡 테스트 방법: 프로젝트 폴더에 'roentgen_10_440' 폴더를 만들고 그 안에 CXR 이미지를 넣으세요.")
        return

    # 구글 시트 연결 및 처리된 파일 확인
    sheet = get_google_sheet()
    processed_files = set()
    if sheet:
        try:
            existing_data = sheet.get_all_values()
            if len(existing_data) > 1:
                # 3번째 컬럼(인덱스 2)이 이미지 파일명이라고 가정
                processed_files = set(row[2] for row in existing_data[1:])
        except Exception:
            pass
    else:
        # 시트 연결이 안 되어도 로컬 테스트는 가능하게 진행
        # st.warning("구글 시트 연결 없이 로컬 모드로 진행합니다.")
        pass

    # 시작 인덱스 찾기 (이미 처리된 파일 건너뛰기)
    start_index = 0
    for i, img_path in enumerate(all_images):
        img_name = os.path.basename(img_path)
        if img_name not in processed_files:
            start_index = i
            break
        if i == total_images - 1 and img_name in processed_files:
            start_index = total_images

    # 세션 상태 초기화
    if 'current_index' not in st.session_state:
        st.session_state.current_index = start_index
    else:
        # 혹시 모를 인덱스 역행 방지
        st.session_state.current_index = max(st.session_state.current_index, start_index)

    # 완료 처리
    if st.session_state.current_index >= total_images:
        st.success("🎉 모든 이미지 판독이 완료되었습니다. 감사합니다!")
        st.balloons()
        if st.button("처음부터 다시 검토하기 (주의: 시트 데이터는 유지됨)"):
            st.session_state.current_index = 0
            st.rerun()
        return

    # 현재 이미지 정보 로드
    current_idx = st.session_state.current_index
    current_image_path = all_images[current_idx]
    image_name = os.path.basename(current_image_path)
    folder_name = os.path.basename(os.path.dirname(current_image_path))

    # ---------------------------------------------------------
    # UI 상단: 진행률 표시
    # ---------------------------------------------------------
    progress = (current_idx) / total_images
    st.progress(progress)
    # st.caption 대신 컬럼을 써서 양쪽 정렬
    col_prog1, col_prog2 = st.columns([1, 1])
    with col_prog1:
         st.caption(f"진행 상황: **{current_idx + 1}** / {total_images}")
    with col_prog2:
         st.caption(f"현재 폴더: `{folder_name}` | 파일명: `{image_name}`")
    st.divider()

    # ---------------------------------------------------------
    # 메인 레이아웃: 좌우 분할 (1:1 비율)
    # ---------------------------------------------------------
    # 좌측은 메인 이미지, 우측은 입력 폼
    col_main_left, col_main_right = st.columns([1, 1], gap="large")

    # --- [왼쪽 컬럼] 판독 대상 메인 이미지 표시 ---
    with col_main_left:
        st.subheader("판독 대상 이미지")

        # 폴더명에 따른 품질 정보 표시 (예시)
        if "10_440" in folder_name:
            st.warning("⚠️ **Low Quality** 합성 설정")
        elif "75_440" in folder_name:
            st.success("✅ **High Quality** 합성 설정")

        # 메인 이미지 표시
        st.image(current_image_path, use_container_width=True)


    # --- [오른쪽 컬럼] 입력 폼 ---
    with col_main_right:
        st.subheader("📝 합성 판단 근거 입력")

        with st.form(key=f'labeling_form_{image_name}'):

            selected_defects = []

            # ==============================================================================
            # [핵심 수정 부분] 질문 및 예시 이미지 옆으로 나란히 표시하는 함수
            # ==============================================================================
            def add_question_with_example(label_text, internal_key, example_key=None):
                # 폼 내부에서 다시 좌우 컬럼 분할 (비율 조정 가능, 예: [7, 3])
                # vertical_alignment="center"는 스트림릿 최신 버전에서 지원하여 수직 중앙 정렬을 돕습니다.
                q_col, img_col = st.columns([7, 3], vertical_alignment="center")

                with q_col:
                    # [왼쪽] 질문 체크박스
                    if st.checkbox(label_text, key=f"{internal_key}_{image_name}"):
                        selected_defects.append(label_text)

                with img_col:
                    # [오른쪽] 예시 이미지가 있으면 표시
                    if example_key:
                        example_path = get_example_image_path(example_key)
                        # 파일 존재 여부 확인 (없으면 빈 공간 유지)
                        if example_path and os.path.exists(example_path):
                            # 캡션 없이 이미지만 작게 표시
                            st.image(example_path, use_container_width=True)
                        # else:
                        #     # 이미지가 없을 때 대체 텍스트 표시 (선택 사항)
                        #     st.caption("(이미지 없음)")
            # ==============================================================================


            # --- 1. Texture 섹션 ---
            st.markdown("##### **[Texture]**")
            add_question_with_example(
                "1. 위치 마커(L/R) 오류\n(Marker Artifacts)", # 줄바꿈을 넣어 텍스트 영역을 확보
                "q_marker",
                "marker_error"
            )
            add_question_with_example(
                "2. 비현실적 투과도 및 밀도\n(Density & Penetration)",
                "q_density",
                "density_penetration"
            )
            add_question_with_example(
                "3. 위장관/복부 가스 음영 오류\n(Abnormal Gas Pattern)",
                "q_gas",
                "abnormal_gas"
            )

            st.markdown("---") # 구분선

            # --- 2. Anatomy 섹션 ---
            st.markdown("##### **[Anatomy]**")
            add_question_with_example(
                "1. 구조물 경계 모호\n(Vague Boundaries)",
                "q_boundary",
                "vague_boundaries"
            )
            add_question_with_example(
                "2. 전방 늑골(Anterior Ribs) 소실/끊김",
                "q_ribs",
                "anterior_ribs"
            )
            add_question_with_example(
                "3. 쇄골 형태 이상 (Wavy)",
                "q_clavicle",
                "wavy_clavicle"
            )
            add_question_with_example(
                "4. 장기 모양 기형\n(Abnormal Organ Shape)",
                "q_organ_shape",
                "abnormal_organ_shape"
            )

            st.markdown("---") # 구분선

            # --- 3. 기타 및 상세 내역 ---
            st.markdown("##### **[기타 및 상세]**")
            # 기타 항목은 예시 이미지가 없으므로 None 전달
            add_question_with_example("기타 (아래 상세 내용 작성 필요)", "q_other", None)

            st.write("") # 약간의 여백
            detail_note = st.text_area(
                "상세 판독 내용 (Description)",
                height=100,
                placeholder="선택한 항목에 대한 구체적인 위치나 설명을 작성해주세요.\n(예: 우측 상폐야에 비정상적인 음영 패턴 관찰됨.)",
                key=f"note_{image_name}"
            )

            st.markdown("") # 간격 추가
            # 폼 제출 버튼 (전폭 사용)
            submit_button = st.form_submit_button(label="💾 저장하고 다음 이미지로 >", type="primary", use_container_width=True)


        # ---------------------------------------------------------
        # 저장 로직 (폼 바깥에서 처리)
        # ---------------------------------------------------------
        if submit_button:
            # 검증 1: 아무것도 선택하지 않은 경우
            if not selected_defects:
                st.error("⚠️ 최소한 하나 이상의 판단 근거를 선택해야 합니다.")

            # 검증 2: '기타' 선택 후 내용 없는 경우 (체크박스 텍스트에 '기타'가 포함되었는지 확인)
            elif any("기타" in opt for opt in selected_defects) and not detail_note.strip():
                st.error("⚠️ '기타' 항목을 선택하셨습니다. 상세 판독 내용에 사유를 작성해주세요.")

            # 저장 진행
            else:
                # 타임스탬프 생성
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                # 선택된 항목들을 콤마로 연결
                defects_str = ", ".join(selected_defects)

                # 저장할 데이터 행 구성
                row_data = [
                    timestamp,
                    folder_name,
                    image_name,
                    defects_str,
                    detail_note
                ]

                # 구글 시트에 추가 시도
                if sheet:
                    try:
                        sheet.append_row(row_data)
                        st.toast(f"✅ 저장 완료! ({image_name})")
                        # 다음 이미지로 인덱스 증가 및 리런
                        st.session_state.current_index += 1
                        st.rerun()
                    except Exception as e:
                        st.error(f"구글 시트 저장 중 오류 발생: {e}")
                else:
                    # 시트 연결이 안 된 경우 (로컬 테스트 모드)
                    st.warning("⚠️ 구글 시트가 연결되지 않아 데이터가 실제 시트에 저장되지 않았습니다. (테스트 모드)")
                    st.info(f"저장 데이터 미리보기: {row_data}")
                    # 테스트를 위해 다음으로 넘김
                    st.session_state.current_index += 1
                    st.rerun()

if __name__ == "__main__":
    main()
