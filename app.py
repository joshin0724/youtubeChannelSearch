import streamlit as st

def main():
    st.set_page_config(page_title="YouTube Channel Search", layout="centered", page_icon="🔍")
    st.title("🔍 YouTube 채널 검색 자동화")
    st.caption("Google Colab에서 빌드되어 GitHub로 배포된 앱입니다.")
    st.divider()
    
    search_query = st.text_input("검색할 유튜브 채널명 또는 키워드를 입력하세요:")
    
    if st.button("채널 검색 실행", type="primary"):
        if search_query:
            st.info(f"🔄 '{search_query}' 분석 중...")
            st.success("✅ 환경 세팅 완료! 정상적으로 동작합니다.")
        else:
            st.warning("⚠️ 검색어를 입력해 주세요.")

if __name__ == "__main__":
    main()
