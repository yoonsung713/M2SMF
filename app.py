import streamlit as st
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# 1. 페이지 설정
st.set_page_config(page_title="합성 CXR 판독 도구", layout="wide")

# 2. Google Sheets 연결 함수
def get_google_sheet():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        # st.secrets에 저장된 서비스 계정 키 사용
        creds_dict = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        # 실제 사용할 스프레드시트 이름과 시트 이름으로 변경하세요
        sheet = client.open("labeling_results").sheet1 
        return sheet
    except Exception as e:
        st.error(f"구글 시트 연결 실패: {e}")
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
        else:
            st.warning(f"폴더를 찾을 수 없습니다: {folder}")
            
    return sorted(image_paths)

# --- [NEW] 예시 이미지 경로 함수 ---
# 각 질문 항목에 매칭될 예시 이미지의 경로를 반환하는 함수입니다.
# 실제 이미지 파일이 존재하는 경로로 수정해야 합니다.
def get_example_image_path(question_key):
    example_images_dir = "example_images" # 예시 이미지가 저장된 폴더명
    
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
        return os.path.join(example_images_dir, filename)
    return None

# 4. 메인 로직
def main():
    st.title("🖼️ 합성 CXR 정밀 판독")
    
    # 작업할 폴더 리스트
    target_folders = ["roentgen_10_440", "roentgen_75_440", "images"]
    all_images = load_image_paths(target_folders)
    total_images = len(all_images)
    
    if total_images == 0:
        st.error("지정된 폴더들에 이미지가 없습니다.")
        return

    # 구글 시트 연결 및 처리된 파일 확인
    sheet = get_google_sheet()
    processed_files = set()
    if sheet:
        try:
            existing_data = sheet.get_all_values()
            if len(existing_data) > 1:
                processed_files = set(row[2] for row in existing_data[1:]) 
        except Exception:
            pass
    else:
        return 

    # 시작 인덱스 찾기
    start_index = 0
    for i, img_path in enumerate(all_images):
        img_name = os.path.basename(img_path)
        if img_name not in processed_files:
            start_index = i
            break
        if i == total_images - 1 and img_name in processed_files:
            start_index = total_images

    if 'current_index' not in st.session_state:
        st.session_state.current_index = start_index
    else:
        st.session_state.current_index = max(st.session_state.current_index, start_index)

    # 완료 처리
    if st.session_state.current_index >= total_images:
        st.success("모든 이미지 판독이 완료되었습니다. 감사합니다!")
        st.balloons()
        return

    # 현재 이미지 정보 로드
    current_idx = st.session_state.current_index
    current_image_path = all_images[current_idx]
    image_name = os.path.basename(current_image_path)
    folder_name = os.path.basename(os.path.dirname(current_image_path))

    # 진행률 표시
    progress = (current_idx) / total_images
    st.progress(progress)
    st.caption(f"진행 상황: {current_idx + 1} / {total_images} | 폴더: {folder_name}")

    # ---------------------------------------------------------
    # 레이아웃: 좌우 분할 (1:1)
    # ---------------------------------------------------------
    col_left, col_right = st.columns([1, 1])

    # --- 왼쪽 컬럼: 판독 대상 이미지 표시 ---
    with col_left:
        if folder_name == "roentgen_10_440":
            st.warning("⚠️ **Low Quality** 합성 이미지")
        elif folder_name == "roentgen_75_440":
            st.success("✅ **High Quality** 합성 이미지")
        
        st.image(current_image_path, caption=image_name, use_container_width=True)

    # --- 오른쪽 컬럼: 입력 폼 ---
    with col_right:
        st.subheader("📝 합성 판단 근거")
        with st.form(key=f'labeling_form_{image_name}'):
            
            selected_defects = []

            # --- [NEW] 질문 및 예시 이미지 표시 함수 ---
            # 질문 텍스트, 내부 키값, 예시 이미지 키값을 받아 화면에 표시하는 헬퍼 함수
            def add_question_with_example(label_text, internal_key, example_key=None):
                # 질문 체크박스
                if st.checkbox(label_text, key=f"{internal_key}_{image_name}"):
                    selected_defects.append(label_text)
                
                # 예시 이미지가 있으면 확장형(expander)으로 표시
                if example_key:
                    example_path = get_example_image_path(example_key)
                    if example_path and os.path.exists(example_path):
                        with st.expander("📷 예시 이미지 보기"):
                            st.image(example_path, caption=f"예시: {label_text}", use_container_width=True)
                    # else:
                    #     st.caption("※ 예시 이미지를 준비 중입니다.") # 필요 시 주석 해제

            # --- 1. Texture ---
            st.markdown("###### **[Texture]**")
            add_question_with_example(
                "1. 위치 마커(L/R) 오류 (Marker Artifacts)",
                "q_marker",
                "marker_error"
            )
            add_question_with_example(
                "2. 비현실적 투과도 및 밀도 (Density & Penetration)",
                "q_density",
                "density_penetration"
            )
            add_question_with_example(
                "3. 위장관/복부 가스 음영 오류 (Abnormal Gas Pattern)",
                "q_gas",
                "abnormal_gas"
            )

            st.divider()

            # --- 2. Anatomy ---
            st.markdown("###### **[Anatomy]**")
            add_question_with_example(
                "1. 구조물 경계 모호 (Vague Boundaries)",
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
                "4. 장기 모양 기형 (Abnormal Organ Shape)",
                "q_organ_shape",
                "abnormal_organ_shape"
            )

            st.divider()
            
            # --- 3. 기타 ---
            add_question_with_example("기타 (아래 상세 내용 작성 필요)", "q_other")

            st.markdown("###### **상세 판독 (Description)**")
            detail_note = st.text_area(
                "상세 내용 작성",
                height=100,
                placeholder="예: 우측 상폐야에 비정상적인 음영 패턴 관찰됨.",
                key=f"note_{image_name}",
                label_visibility="collapsed"
            )
            
            st.markdown("") # 간격 추가
            submit_button = st.form_submit_button(label="저장 후 다음 >", type="primary", use_container_width=True)

    # ---------------------------------------------------------
    # 저장 로직 (폼 바깥에서 처리)
    # ---------------------------------------------------------
    if submit_button:
        # 1. 아무것도 선택하지 않은 경우
        if not selected_defects:
            st.error("⚠️ 최소한 하나 이상의 항목을 선택해야 합니다.")

        # 2. '기타' 선택 후 내용 없는 경우
        elif any("기타" in opt for opt in selected_defects) and not detail_note.strip():
            st.error("⚠️ '기타' 항목을 선택하셨습니다. 상세 판독문에 사유를 작성해주세요.")

        else:
            try:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                defects_str = ", ".join(selected_defects)
                
                row_data = [
                    timestamp, 
                    folder_name, 
                    image_name, 
                    defects_str, 
                    detail_note
                ]
                
                sheet.append_row(row_data)
                st.toast(f"저장 완료! ({image_name})")
                
                st.session_state.current_index += 1
                st.rerun()
                
            except Exception as e:
                st.error(f"저장 중 오류가 발생했습니다: {e}")

if __name__ == "__main__":
    main()

