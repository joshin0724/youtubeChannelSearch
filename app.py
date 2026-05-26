import streamlit as st
import re
from googleapiclient.discovery import build
import datetime
import isodate  # 유튜브 영상 시간 파싱용 라이브러리 (requirements에 추가 필요)

# -------------------------------------------------------------
# 1. 유튜브 스타일 커스텀 테마 및 디자인 세팅 (CSS Injection)
# -------------------------------------------------------------
st.set_page_config(page_title="YouTube Channel Analyzer", layout="wide", page_icon="🔴")

st.markdown("""
    <style>
    /* 전체 배경을 유튜브 다크모드 색상으로 지정 */
    .stApp {
        background-color: #0F0F0F;
        color: #F1F1F1;
    }
    /* 입력창 및 셀렉트박스 스타일 선언 */
    div[data-baseweb="input"] {
        background-color: #212121 !important;
        border: 1px solid #3F3F3F !important;
        border-radius: 40px !important; /* 유튜브 검색창 특유의 라운드 적용 */
    }
    div[data-baseweb="select"] {
        background-color: #212121 !important;
        border-radius: 8px !important;
    }
    /* 버튼 스타일 커스텀 */
    .stButton>button {
        background-color: #CC0000 !important;
        color: white !important;
        border-radius: 20px !important;
        border: none !important;
        font-weight: bold;
        padding: 0.5rem 2rem !important;
    }
    .stButton>button:hover {
        background-color: #FF0000 !important;
    }
    /* 카드 디자인 */
    .video-card {
        background-color: #1F1F1F;
        border-radius: 12px;
        padding: 0px;
        margin-bottom: 25px;
        overflow: hidden;
        transition: transform 0.2s;
    }
    .video-card:hover {
        transform: scale(1.02);
    }
    .video-title {
        font-size: 14px;
        font-weight: 600;
        color: #F1F1F1;
        margin: 10px 8px 5px 8px;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }
    .video-meta {
        font-size: 12px;
        color: #AAA;
        margin: 0px 8px 10px 8px;
    }
    </style>
""", unsafe_gradient=True, unsafe_allow_html=True)

# -------------------------------------------------------------
# 2. YouTube API 커넥터 및 핵심 비즈니스 로직 함수
# -------------------------------------------------------------
def get_youtube_client():
    """Secrets에 안전하게 저장된 API Key를 가져와 클라이언트를 빌드합니다."""
    try:
        api_key = st.secrets["YOUTUBE_API_KEY"]
        return build('youtube', 'v3', developerKey=api_key)
    except Exception:
        st.error("🔒 Streamlit Advanced Settings에 'YOUTUBE_API_KEY'가 설정되지 않았습니다.")
        return None

def extract_channel_id_or_handle(url):
    """다양한 유튜브 URL 구조에서 채널 핸들(@) 또는 ID를 추출합니다."""
    handle_match = re.search(r'mailto:[^/]+/(@[^/?]+)', url)
    if handle_match:
        return handle_match.group(1)
    
    id_match = re.search(r'mailto:[^/]+/channel/([^/?]+)', url)
    if id_match:
        return id_match.group(1)
    
    cleaned = url.strip().split('/')[-1].split('?')[0]
    if cleaned.startswith('@'):
        return cleaned
    return None

def fetch_channel_internal_id(youtube, identity):
    """핸들네임(@)을 기반으로 실제 시스템 내부용 고유 Channel ID를 조회합니다."""
    if identity.startswith('UC'):
        return identity
    
    response = youtube.channels().list(
        part='id',
        forHandle=identity
    ).execute()
    
    items = response.get('items', [])
    if items:
        return items[0]['id']
    return None

def get_channel_videos(youtube, channel_id, video_type_filter):
    """채널의 최신 영상들을 가져온 후, 재생 시간을 기준으로 롱폼/숏츠를 필터링합니다."""
    # 1. 채널의 '업로드 목록' 고유 ID 확보
    ch_resp = youtube.channels().list(part='contentDetails', id=channel_id).execute()
    upload_playlist_id = ch_resp['items'][0]['contentDetails']['relatedPlaylists']['uploads']
    
    # 2. 업로드 플레이리스트에서 최신 비디오 ID 30개 파싱
    next_page_token = None
    video_ids = []
    
    playlist_resp = youtube.playlistItems().list(
        part='snippet',
        playlistId=upload_playlist_id,
        maxResults=30,
        pageToken=next_page_token
    ).execute()
    
    for item in playlist_resp.get('items', []):
        video_ids.append(item['snippet']['resourceId']['videoId'])
        
    if not video_ids:
        return []

    # 3. 비디오 상세 정보 검색 (조회수, 좋아요, 재생시간, 썸네일 통합 추출)
    video_resp = youtube.videos().list(
        part='snippet,statistics,contentDetails',
        id=','.join(video_ids)
    ).execute()
    
    filtered_videos = []
    
    for v_item in video_resp.get('items', []):
        # 재생시간 계산 (ISO 8601 포맷 파싱)
        duration_str = v_item['contentDetails']['duration']
        duration_secs = isodate.parse_duration(duration_str).total_seconds()
        
        # 숏츠(60초 이하) / 롱폼(60초 초과) 정밀 판정 분류기
        if video_type_filter == "숏츠(Shorts)" and duration_secs > 60:
            continue
        if video_type_filter == "롱폼(일반 영상)" and duration_secs <= 60:
            continue
            
        # 메타데이터 구조화
        snippet = v_item['snippet']
        stats = v_item.get('statistics', {})
        
        # 날짜 파싱
        pub_date = datetime.datetime.strptime(snippet['publishedAt'], "%Y-%m-%dT%H:%M:%SZ")
        formatted_date = pub_date.strftime("%Y.%m.%d")
        
        # 숫자 포맷팅 (조회수 만 단위 등 처리 가능하나 기본형 유지)
        view_count = int(stats.get('viewCount', 0))
        like_count = int(stats.get('likeCount', 0))
        
        video_info = {
            "title": snippet['title'],
            "thumbnail": snippet['thumbnails'].get('high', snippet['thumbnails']['default'])['url'],
            "views": f"{view_count:,}회",
            "likes": f"{like_count:,}개",
            "date": formatted_date,
            "url": f"https://youtube.com/watch?v={v_item['id']}"
        }
        filtered_videos.append(video_info)
        
    return filtered_videos

# -------------------------------------------------------------
# 3. Streamlit UI 렌더링 엔진
# -------------------------------------------------------------
def main():
    st.title("🔴 YouTube Channel Search")
    st.subheader("숏츠 및 롱폼 맞춤형 영상 검색 인프라")
    st.write("")
    
    # 메인 컨트롤 레이아웃 설정
    col1, col2 = st.columns([3, 1])
    
    with col1:
        url_input = st.text_input("유튜브 채널 URL", placeholder="https://www.youtube.com/@유튜브채널명 입력")
    with col2:
        video_type = st.selectbox("영상 유형 선택", ["롱폼(일반 영상)", "숏츠(Shorts)"])
        
    st.write("")
    search_button = st.button("검색 실행")
    
    if search_button:
        if not url_input:
            st.warning("⚠️ 분석할 유튜브 채널 URL을 입력해 주세요.")
            return
            
        youtube = get_youtube_client()
        if youtube is None:
            return
            
        with st.spinner("🚀 유튜브 데이터베이스에서 채널 정보를 검색 및 분류 중입니다..."):
            # 1. URL 해석 및 파싱
            identity = extract_channel_id_or_handle(url_input)
            if not identity:
                st.error("❌ 올바르지 않은 유튜브 채널 URL 형식입니다. 핸들(@) 형식을 확인해 주세요.")
                return
                
            # 2. 내부 시스템 ID 매핑
            channel_id = fetch_channel_internal_id(youtube, identity)
            if not channel_id:
                st.error("❌ 해당 채널을 찾을 수 없습니다. URL 혹은 채널 명을 확인해 주세요.")
                return
                
            # 3. 비디오 로딩 및 분류 작업
            results = get_channel_videos(youtube, channel_id, video_type)
            
            if not results:
                st.info(f"조회된 최신 영상 중 해당 카테고리({video_type})의 영상이 존재하지 않습니다.")
                return
                
            # 4. 유튜브 스타일 그리드 UI 렌더링 출력 (한 줄에 4개씩 카드 배치)
            st.success(f"📊 총 {len(results)}개의 비디오가 조건에 맞춰 정렬되었습니다.")
            st.write("")
            
            grid_columns = st.columns(4)
            for idx, video in enumerate(results):
                col_target = grid_columns[idx % 4]
                with col_target:
                    # 클릭 시 해당 유튜브 주소로 이동하는 카드 컴포넌트 마크다운 구조화
                    st.markdown(f"""
                        <a href="{video['url']}" target="_blank" style="text-decoration: none;">
                            <div class="video-card">
                                <img src="{video['thumbnail']}" style="width:100%; border-radius:12px 12px 0 0; object-fit: cover;">
                                <div class="video-title">{video['title']}</div>
                                <div class="video-meta">
                                    조회수 {video['views']} • 좋아요 {video['likes']}<br>
                                    업로드일: {video['date']}
                                </div>
                            </div>
                        </a>
                    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
