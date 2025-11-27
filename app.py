import streamlit as st
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# 1. 페이지 설정
st.set_page_config(page_title="합성 이미지 판독 도구", layout="centered")

# CSS로 라디오 버튼 간격 조절
st.markdown("""
    <style>
    .stRadio > label {font-weight: bold; font-size: 1.2rem;}
    </style>
    """, unsafe_allow_html=True)

# 2. Google Sheets 연결 함수
def get_google_sheet():
    try:
        # Streamlit Cloud의 Secrets 기능을 사용
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
    st.title("🖼️ 합성 이미지 정밀 판독")
    
    # 작업할 폴더 리스트
    target_folders = ["roentgen_10_440", "roentgen_75_440"]
    all_images = load_image_paths(target_folders)
    total_images = len(all_images)
    
    if total_images == 0:
        st.error("지정된 폴더들에 이미지가 없습니다.")
        return

    # 구글 시트 연결 및 중복 확인
    sheet = get_google_sheet()
    processed_files = set()
    
    if sheet:
        try:
            existing_data = sheet.get_all_values()
            # 헤더가 있다고 가정하고, 파일명은 3번째 열(index 2)에 위치한다고 가정
            if len(existing_data) > 1:
                processed_files = set(row[2] for row in existing_data[1:]) 
        except Exception:
            pass
    else:
        return 

    # 작업 안 한 이미지 인덱스 찾기
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

    # 모든 작업 완료 시
    if st.session_state.current_index >= total_images:
        st.success("모든 이미지 판독이 완료되었습니다. 감사합합니다!")
        st.balloons()
        return

    # 현재 이미지 정보 로드
    current_idx = st.session_state.current_index
    current_image_path = all_images[current_idx]
    image_name = os.path.basename(current_image_path)
    folder_name = os.path.basename(os.path.dirname(current_image_path))

    # UI 상단: 진행률 및 이미지
    progress = (current_idx) / total_images
    st.progress(progress)
    st.caption(f"진행 상황: {current_idx + 1} / {total_images} | 폴더: {folder_name}")
    
    st.image(current_image_path, caption=image_name, use_container_width=True)

    # ---------------------------------------------------------
    # [수정된 부분] 입력 폼: 퀄리티 평가 및 판독문 작성
    # ---------------------------------------------------------
    with st.form(key='labeling_form', clear_on_submit=True):
        st.subheader("📝 판독 결과 입력")
        st.info("이 이미지는 합성된 이미지입니다. 퀄리티와 이상 부위를 판단해주세요.")

        # 1. 퀄리티 등급 (Quality)
        st.markdown("**1. 합성 퀄리티 등급**")
        quality_options = [
            "1. High Quality - 언뜻 보면 실제와 구분이 어려움",
            "2. Low Quality - 합성인 것이 명확히 드러남"
        ]
        quality_choice = st.radio("전반적인 완성도는 어떤가요?", quality_options, index=0)

        # 2. 합성 판단 요인 (Reason)
        st.markdown("**2. 합성이라고 판단한 주된 요인 (가장 큰 결함)**")
        defect_options = [
            "A. 해부학적 구조 오류 (뼈/장기의 위치나 모양이 비현실적)",
            "B. 질감 및 노이즈 이상 (지나치게 매끄럽거나 거친 패턴)",
            "C. 음영/대조 부조화 (그림자나 밝기가 주변과 맞지 않음)",
            "D. 경계선 아티팩트 (배경과 분리되어 보이거나 끊김)",
            "E. 기괴한 형체/미지의 패턴 (Unknown Artifacts)",
            "F. 기타 (아래에 상세 기술)"
        ]
        defect_choice = st.radio("어느 부분이 가장 어색한가요?", defect_options)

        # 3. 상세 판독문 (Pandokmun)
        st.markdown("**3. 상세 판독문 (Description)**")
        detail_note = st.text_area(
            "구체적으로 어떤 부분이 이상한지 서술해주세요.",
            height=100,
            placeholder="예시: 왼쪽 갈비뼈의 음영이 중간에 끊겨 있고, 폐 하단의 질감이 뭉개져 보임."
        )
        
        # 제출 버튼
        submit_button = st.form_submit_button(label="판독 결과 저장하고 다음으로 >", type="primary")

    # 저장 로직
    if submit_button:
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # [수정됨] 저장 데이터 구조: [시간, 폴더, 파일, 퀄리티, 결함요인, 상세판독문]
            row_data = [
                timestamp, 
                folder_name, 
                image_name, 
                quality_choice.split(" ")[1], # "상" or "하" 만 추출 (괄호 앞부분)
                defect_choice, 
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

