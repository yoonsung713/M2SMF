import streamlit as st
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# 1. 페이지 설정
st.set_page_config(page_title="이미지 라벨링 도구", layout="centered")

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

# 3. 이미지 파일 리스트 불러오기 (여러 폴더 지원하도록 수정됨)
@st.cache_data
def load_image_paths(target_folders):
    image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'}
    image_paths = []
    
    # 지정된 폴더 리스트를 순회하며 이미지 찾기
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
    st.title("🖼️ 이미지 분류 작업")
    
    # [수정됨] 사용자의 폴더 구조에 맞춰 리스트 작성
    target_folders = ["roentgen_10_440", "mimic_451", "roentgen_75_440"]
    all_images = load_image_paths(target_folders)
    total_images = len(all_images)
    
    if total_images == 0:
        st.error("지정된 폴더들에 이미지가 없습니다.")
        return

    # [추가됨] 이미 작업한 목록 확인 (새로고침 해도 이어서 하기 위함)
    sheet = get_google_sheet()
    if sheet:
        try:
            # 모든 데이터를 가져와서 이미 라벨링된 파일명 추출
            existing_data = sheet.get_all_values()
            # 헤더가 있다면 건너뛰고, 3번째 열(인덱스 2)이 파일명이라고 가정
            if len(existing_data) > 1:
                processed_files = set(row[2] for row in existing_data[1:]) 
            else:
                processed_files = set()
        except Exception:
            processed_files = set()
    else:
        return # 시트 연결 실패 시 중단

    # 라벨링 안 된 첫 번째 이미지 찾기
    start_index = 0
    for i, img_path in enumerate(all_images):
        img_name = os.path.basename(img_path)
        if img_name not in processed_files:
            start_index = i
            break
        # 마지막까지 다 돌았으면 완료 처리
        if i == total_images - 1 and img_name in processed_files:
            start_index = total_images

    # 세션 상태에 반영 (current_index가 없거나, 진행 상황에 따라 업데이트)
    if 'current_index' not in st.session_state:
        st.session_state.current_index = start_index
    else:
        # 이미 완료된 이미지를 건너뛰기 위해 max값 사용
        st.session_state.current_index = max(st.session_state.current_index, start_index)

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
    progress = (current_idx) / total_images
    st.progress(progress)
    st.caption(f"진행 상황: {current_idx + 1} / {total_images} | 폴더: {folder_name} | 파일명: {image_name}")

    # 이미지 표시
    st.image(current_image_path, use_container_width=True) # 최신 버전 문법 적용

    # 입력 폼
    with st.form(key='labeling_form', clear_on_submit=True): # clear_on_submit: 제출 후 비고란 비우기
        st.write("### 이 이미지에 대한 판단은?")
        
        options = ["옵션 A (정상)", "옵션 B (불량)", "옵션 C (애매함)", "옵션 D (기타)"]
        choice = st.radio("하나를 선택하세요:", options)
        
        note = st.text_input("비고 (선택사항):")
        
        submit_button = st.form_submit_button(label="저장하고 다음으로 >")

    # 저장 로직
    if submit_button:
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # 저장할 데이터: [시간, 폴더명, 파일명, 선택값, 비고]
            row_data = [timestamp, folder_name, image_name, choice, note]
            sheet.append_row(row_data)
            
            # 성공 메시지 (일시적으로 보임)
            st.toast(f"✅ {image_name} 저장 완료!")
            
            # 다음 이미지로 넘어가기
            st.session_state.current_index += 1
            st.rerun() # 화면 새로고침
            
        except Exception as e:
            st.error(f"저장 중 오류가 발생했습니다: {e}")

if __name__ == "__main__":
    main()
