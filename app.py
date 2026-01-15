import streamlit as st
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# 1. 페이지 설정
st.set_page_config(page_title="합성 CXR 판독 도구", layout="centered")

# CSS로 라디오 버튼 및 멀티셀렉트 스타일 조절
st.markdown("""
    <style>
    .stRadio > label {font-weight: bold; font-size: 1.1rem;}
    .stMultiSelect > label {font-weight: bold; font-size: 1.1rem;}
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
    st.title("🩻 합성 CXR 정밀 판독 (Clinical Review)")
    
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
        st.success("모든 이미지 판독이 완료되었습니다. 감사합니다!")
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
    # [수정된 부분] 입력 폼: 임상의 기준 상세 평가
    # ---------------------------------------------------------
    with st.form(key='labeling_form', clear_on_submit=True):
        st.subheader("📝 판독 결과 입력")
        st.info("영상의학 평가지표를 기준으로 합성 여부를 판단해주세요.")

        # 1. 퀄리티 등급 (Quality)
        st.markdown("**1. 합성 퀄리티 등급**")
        quality_options = [
            "1. High Quality - 언뜻 보면 실제와 구분이 어려움",
            "2. Low Quality - 합성인 것이 명확히 드러남"
        ]
        quality_choice = st.radio("전반적인 완성도는 어떤가요?", quality_options, index=0)

        st.markdown("---")

        # 2. 합성 판단 요인 (Reason) - 수정된 부분
        st.markdown("**2. 합성 판단 근거 (Clinical Indicators)**")
        st.caption("해당하는 결함 요소를 모두 선택해주세요 (복수 선택 가능).")
        
        defect_options = [
            "A. [폐실질] 말초 혈관상(Vascular markings) 소실/뭉개짐 (Ref: 4.6.1)",
            "B. [폐실질] 해부학적으로 불가능한 혈관 주행/분지 (Ref: 4.6.1)",
            "C. [뼈] 늑골(Rib)의 개수 오류, 융합, 끊김 (Ref: 4.3.1)",
            "D. [뼈] 쇄골/견갑골/척추의 비현실적 비대칭/기형 (Ref: 4.4)",
            "E. [인공물] 텍스트(L/R 마커) 깨짐 또는 정체불명의 부유물 (Ref: 3.3, 4.2)",
            "F. [물리] 투과도(Penetration) 부조화 (심장 뒤 척추 안 보임 등) (Ref: 4.6.6)",
            "G. [기타] 기타 사유 (아래 기술)"
        ]
        
        # Radio 대신 Multiselect 사용
        defect_choices = st.multiselect("발견된 이상 소견:", defect_options)

        # 3. 상세 판독문 (Pandokmun)
        st.markdown("**3. 상세 판독문 (Description)**")
        detail_note = st.text_area(
            "구체적으로 어떤 부분이 이상한지 서술해주세요.",
            height=100,
            placeholder="예시: 우측 상엽의 혈관 주행이 갑자기 끊기며, 왼쪽 6번 늑골의 형태가 기형적임."
        )
        
        # 제출 버튼
        submit_button = st.form_submit_button(label="판독 결과 저장하고 다음으로 >", type="primary")

    # 저장 로직
    if submit_button:
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # [수정됨] 데이터 전처리
            # 1. Quality: "High" or "Low" 추출
            quality_val = quality_choice.split(" ")[1] 
            
            # 2. Defect: 리스트를 문자열로 변환 (예: "A..., C...")
            defect_val = ", ".join(defect_choices) if defect_choices else "선택 없음"

            # 저장 데이터 구조: [시간, 폴더, 파일, 퀄리티, 결함요인(전체), 상세판독문]
            row_data = [
                timestamp, 
                folder_name, 
                image_name, 
                quality_val, 
                defect_val, 
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
