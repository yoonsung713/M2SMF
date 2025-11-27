import streamlit as st
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
from datetime import datetime

# 1. 페이지 설정
st.set_page_config(page_title="이미지 라벨링 도구", layout="centered")

# 2. Google Sheets 연결 함수
def get_google_sheet():
    # Streamlit Cloud의 Secrets 기능을 사용합니다.
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    # st.secrets에서 정보를 딕셔너리 형태로 가져옵니다.
    creds_dict = st.secrets["gcp_service_account"]
    
    # gspread로 인증 및 시트 열기
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    
    # 구글 시트 이름 (정확해야 합니다)
    sheet = client.open("labeling_results").sheet1 
    return sheet

# 3. 이미지 파일 리스트 불러오기 (캐싱하여 속도 향상)
@st.cache_data
def load_image_paths(base_folder):
    image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp'}
    image_paths = []
    for root, dirs, files in os.walk(base_folder):
        for file in files:
            if os.path.splitext(file)[1].lower() in image_extensions:
                image_paths.append(os.path.join(root, file))
    return sorted(image_paths)

# 4. 메인 로직
def main():
    st.title("🖼️ 이미지 분류 작업")
    
    # 이미지 로드
    all_images = load_image_paths("images") # 'images' 폴더 내 모든 이미지
    total_images = len(all_images)
    
    if total_images == 0:
        st.error("이미지 폴더에 이미지가 없습니다.")
        return

    # 세션 상태 초기화 (현재 몇 번째 이미지인지 추적)
    if 'current_index' not in st.session_state:
        st.session_state.current_index = 0

    # 작업 완료 체크
    if st.session_state.current_index >= total_images:
        st.success("🎉 모든 이미지 라벨링이 완료되었습니다! 수고하셨습니다.")
        st.balloons()
        return

    # 현재 이미지 정보
    current_idx = st.session_state.current_index
    current_image_path = all_images[current_idx]
    image_name = os.path.basename(current_image_path)
    folder_name = os.path.basename(os.path.dirname(current_image_path))

    # 진행률 표시
    st.progress((current_idx) / total_images)
    st.caption(f"진행 상황: {current_idx + 1} / {total_images} | 폴더: {folder_name} | 파일명: {image_name}")

    # 이미지 표시
    st.image(current_image_path, use_column_width=True)

    # 입력 폼 (폼을 쓰면 버튼 클릭 시에만 페이지가 리로드됨)
    with st.form(key='labeling_form'):
        st.write("### 이 이미지에 대한 판단은?")
        
        # 사지선다 옵션
        options = ["옵션 A (정상)", "옵션 B (불량)", "옵션 C (애매함)", "옵션 D (기타)"]
        choice = st.radio("하나를 선택하세요:", options)
        
        # 비고 입력
        note = st.text_input("비고 (선택사항):")
        
        submit_button = st.form_submit_button(label="저장하고 다음으로 >")

    # 저장 로직
    if submit_button:
        try:
            sheet = get_google_sheet()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # 저장할 데이터: [시간, 폴더명, 파일명, 선택값, 비고]
            row_data = [timestamp, folder_name, image_name, choice, note]
            sheet.append_row(row_data)
            
            # 다음 이미지로 넘어가기
            st.session_state.current_index += 1
            st.rerun() # 화면 새로고침
            
        except Exception as e:
            st.error(f"저장 중 오류가 발생했습니다: {e}")

if __name__ == "__main__":
    main()