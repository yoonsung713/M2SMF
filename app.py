import streamlit as st
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# 1. 페이지 설정
st.set_page_config(page_title="합성 CXR 판독 도구", layout="centered")

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
    st.title("🖼️ 합성 CXR 정밀 판독 (Checkbox)")
    
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

    # 진행률 및 이미지 표시
    progress = (current_idx) / total_images
    st.progress(progress)
    st.caption(f"진행 상황: {current_idx + 1} / {total_images} | 폴더: {folder_name}")
    st.image(current_image_path, caption=image_name, use_container_width=True)

    # ---------------------------------------------------------
    # [수정됨] 체크박스 형태의 입력 폼
    # ---------------------------------------------------------
    # 주의: 유효성 검사 실패 시 입력값이 사라지지 않도록 clear_on_submit=False로 설정(기본값)
    with st.form(key='labeling_form'): 
        st.subheader("📝 합성 판단 근거 (Checklist)")
        st.info("해당하는 항목을 모두 체크해주세요.")

        # 옵션 리스트 정의 (기타 추가됨)
        defect_options = [
            # 1. Texture / Global Artifacts
            "[노이즈/질감] 전반적인 해상도 저하, 픽셀 깨짐, 또는 이질적인 질감 (Noise/Texture)",
            "[노이즈/질감] 텍스트(L/R 마커) 뭉개짐, 또는 배경의 정체불명 아티팩트 (Artifacts)",
            "[노이즈/질감] 경계면(피부/배경)이 부자연스럽게 분리되거나 섞임 (Boundary)",

            # 2. Anatomy / Structure
            "[해부학] 늑골(Rib)의 개수 오류, 융합, 끊김 현상 (Skeletal-Ribs)",
            "[해부학] 쇄골/견갑골/척추의 좌우 비대칭 또는 기형 (Skeletal-General)",
            "[해부학] 심장/횡격막의 위치나 모양이 비현실적임 (Organs)",
            "[해부학] 투과도(Penetration) 물리 법칙 오류 (뼈와 장기의 밝기 부조화)",

            # 3. Lung / Fine Patterns
            "[폐] 폐 혈관상(Vascular markings)의 소실 또는 뭉개짐(Blur)",
            "[폐] 폐 실질 내 해부학적으로 불가능한 혈관 주행/분지 (Vessel Path)",
            "[폐] 폐의 비정상적인 음 (Abnormal Patterns)",
            
            # 4. Others
            "기타 (아래 상세 판독문에 내용을 적어주세요)"
        ]

        # 체크박스 생성 루프
        selected_defects = []
        st.markdown("**이상 소견 선택:**")
        
        for option in defect_options:
            if st.checkbox(option, key=option):
                selected_defects.append(option)

        st.markdown("---")

        # 상세 판독문 (Description)
        st.markdown("**상세 판독 (Description)**")
        detail_note = st.text_area(
            "선택한 항목에 대한 구체적인 설명이나 '기타' 사유를 적어주세요.",
            height=80,
            placeholder="예: 우측 늑골 끊김 관찰됨. (기타 선택 시 필수 작성)"
        )
        
        # 제출 버튼
        submit_button = st.form_submit_button(label="판독 결과 저장하고 다음으로 >", type="primary")

    # 저장 로직 및 유효성 검사 (Validation)
    if submit_button:
        # [추가된 로직] 유효성 검사: 기타 선택 시 내용 필수 확인
        other_option_str = "기타 (아래 상세 판독문에 내용을 적어주세요)"
        is_other_selected = other_option_str in selected_defects
        is_note_empty = not detail_note.strip() # 공백 제거 후 확인

        if is_other_selected and is_note_empty:
            st.error("🚨 '기타' 항목을 선택하셨습니다. 상세 판독문에 구체적인 사유를 작성해주세요.")
        else:
            # 검사 통과 시 저장 진행
            try:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # 체크된 리스트를 문자열로 변환
                defects_str = ", ".join(selected_defects) if selected_defects else "None"
                
                row_data = [
                    timestamp, 
                    folder_name, 
                    image_name, 
                    defects_str, 
                    detail_note
                ]
                
                sheet.append_row(row_data)
                
                st.toast(f"저장 완료! ({image_name})")
                
                # 인덱스 증가 및 페이지 새로고침
                st.session_state.current_index += 1
                st.rerun()
                
            except Exception as e:
                st.error(f"저장 중 오류가 발생했습니다: {e}")

if __name__ == "__main__":
    main()
