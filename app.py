import streamlit as st
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# 1. 페이지 설정 (레이아웃을 'wide'로 변경하여 가로 공간 확보)
st.set_page_config(page_title="합성 CXR 판독 도구", layout="wide") 

# 2. Google Sheets 연결 함수
def get_google_sheet():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
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

# 4. 메인 로직
def main():
    st.title("🖼️ 합성 CXR 정밀 판독")
    
    # 작업할 폴더 리스트
    target_folders = ["roentgen_10_440", "roentgen_75_440"]
    all_images = load_image_paths(target_folders)
    total_images = len(all_images)
    
    if total_images == 0:
        st.error("지정된 폴더들에 이미지가 없습니다.")
        return

    # 구글 시트 연결
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

    # 인덱스 찾기
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

    # 현재 이미지 로드
    current_idx = st.session_state.current_index
    current_image_path = all_images[current_idx]
    image_name = os.path.basename(current_image_path)
    folder_name = os.path.basename(os.path.dirname(current_image_path))

    # 진행률 표시
    progress = (current_idx) / total_images
    st.progress(progress)
    st.caption(f"진행 상황: {current_idx + 1} / {total_images} | 폴더: {folder_name}")

    # ---------------------------------------------------------
    # [레이아웃 변경] 좌우 분할 (1:1 비율)
    # ---------------------------------------------------------
    col1, col2 = st.columns([1, 1]) # 왼쪽(이미지), 오른쪽(폼)

    # --- 왼쪽 컬럼: 이미지 표시 ---
    with col1:
        if folder_name == "roentgen_10_440":
            st.warning("⚠️ **Low Quality** 합성 이미지")
        elif folder_name == "roentgen_75_440":
            st.success("✅ **High Quality** 합성 이미지")
        
        # 이미지 꽉 채워서 표시
        st.image(current_image_path, caption=image_name, use_container_width=True)

    # --- 오른쪽 컬럼: 입력 폼 ---
    with col2:
        with st.form(key=f'labeling_form_{image_name}'):
            st.subheader("📝 합성 판단 근거")
            # st.info("해당하는 항목을 모두 체크해주세요.") # 공간 절약을 위해 생략 가능

            defect_options = [
                # 1. Texture
                "[노이즈/질감] 전반적인 해상도 저하, 픽셀 깨짐 (Noise)",
                "[노이즈/질감] 텍스트(L/R) 뭉개짐, 배경 아티팩트 (Artifacts)",
                "[노이즈/질감] 경계면(피부/배경) 분리/섞임 (Boundary)",

                # 2. Anatomy
                "[해부학] 늑골(Rib) 개수 오류, 융합, 끊김 (Ribs)",
                "[해부학] 쇄골/견갑골/척추 비대칭/기형 (Skeletal)",
                "[해부학] 심장/횡격막 위치/모양 비현실적 (Organs)",
                "[해부학] 투과도(Penetration) 물리 오류 (Physics)",

                # 3. Lung
                "[폐] 폐 혈관상(Vascular) 소실/뭉개짐 (Blur)",
                "[폐] 해부학적으로 불가능한 혈관 주행 (Vessel Path)",
                "[폐] 비정상적인 음영 패턴 (Abnormal Patterns)",
                
                # 4. Others
                "기타 (아래 상세 판독문에 내용을 적어주세요)"
            ]

            selected_defects = []
            
            # 체크박스 리스트
            st.markdown("###### **이상 소견 선택**")
            for option in defect_options:
                unique_key = f"{option}_{image_name}"
                if st.checkbox(option, key=unique_key):
                    selected_defects.append(option)

            st.markdown("---")

            st.markdown("###### **상세 판독 (Description)**")
            detail_note = st.text_area(
                "상세 내용 작성",
                height=100,
                placeholder="예: 우측 늑골 끊김 관찰됨.",
                key=f"note_{image_name}",
                label_visibility="collapsed" # 공간 절약을 위해 라벨 숨김
            )
            
            # 버튼을 오른쪽 끝으로 보내고 싶다면 columns 사용 가능
            # sub_col1, sub_col2 = st.columns([2, 1])
            # with sub_col2:
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
