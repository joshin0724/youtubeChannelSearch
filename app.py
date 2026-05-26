import streamlit as st
import re
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import datetime
import isodate

# -------------------------------------------------------------
# 1. 유튜브 스타일 다크모드 및 모바일/PC 반응형 CSS 주입
# -------------------------------------------------------------
st.set_page_config(page_title="YouTube Channel Analyzer", layout="wide", page_icon="🔴")

st.markdown("""
    <style>
    .stApp {
        background-color: #0F0F0F;
        color: #F1F1F1;
    }
    div[data-baseweb="input"] {
        background-color: #212121 !important;
        border: 1px solid #3F3F3F !important;
        border-radius: 40px !important;
    }
    div[data-baseweb="select"] {
        background-color: #212121 !important;
        border-radius: 8px !important;
    }
    .stButton>button {
        background-color: #CC0000 !important;
        color: white !important;
        border-radius: 20px !important;
        border: none !important;
        font-weight: bold;
        padding: 0.5rem 2rem !important;
        width: 100%;
    }
    .stButton>button:hover {
        background-color: #FF0000 !important;
    }
    
    .video-grid {
        display: flex;
        flex-wrap: wrap;
        gap: 16px;
        justify-content: flex-start;
    }
    .video-card-wrapper {
        flex: 1 1 calc(25% - 16px);
        min-width: 250px;
        max-width: 100%;
        box-sizing: border-box;
    }
    @media (max-width: 768px) {
        .video-card-wrapper {
            flex: 1 1 calc(50% - 16px);
        }
    }
    @media (max-width: 480px) {
        .video-card-wrapper {
            flex: 1 1 100%;
        }
    }

    .video-card {
        background-color: #1F1F1F;
        border-radius: 12px;
        padding: 0px;
        height: 100%;
        overflow: hidden;
        transition: transform 0.2s;
        border: 1px solid #2F2F2F;
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
        line-height: 1.4;
    }
    .video-meta {
        font-size: 12px;
        color: #AAA;
        margin: 0px 8px 12px 8px;
        line-height: 1.5;
    }
    .notice-text {
        font-size: 13px;
        color: #FF8A8A;
        margin-top: 6px;
        display: block;
    }
    </style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------
# 2. YouTube API 커넥터 및 검색 핵심 비즈니스 로직
# -------------------------------------------------------------
def get_youtube_client():
    try:
        api_key = st.secrets["YOUTUBE_API_KEY"].strip() # 공백 제거 안전장치
        return build('youtube', 'v3', developerKey=api_key)
    except Exception:
        st.error("🔒 Streamlit Advanced Settings에 'YOUTUBE_API_KEY'가 설정되지 않았습니다.")
        return None

def extract_channel_id_or_handle(url):
    """URL 내부에서 @핸들네임 또는 고유 ID 문자열을 유연하게 추출합니다."""
    url = url.strip()
    if 'youtube.com' not in url and url.startswith('@'):
        return url
        
    handle_match = re.search(r'youtube\.com/(@[^/?]+)', url)
    if handle_match:
        return handle_match.group(1)
    
    id_match = re.search(r'youtube\.com/channel/([^/?]+)', url)
    if id_match:
        return id_match.group(1)
    
    cleaned = url.split('/')[-1].split('?')[0]
    if cleaned.startswith('@'):
        return cleaned
    return url # 원본 그대로 반환하여 차선책 탐색

def fetch_channel_internal_id(youtube, identity):
    """HttpError 방지를 위한 다중 폴백(Fallback) 채널 ID 확보 인프라"""
    if identity.startswith('UC'):
        return identity
        
    # 차선책 1: 구글 공식 핸들 검색 API 시도
    try:
        # API 전송 전 패딩 제거
        handle_clean = identity.replace('@', '')
        response = youtube.channels().list(part='id', forHandle=handle_clean).execute()
        items = response.get('items', [])
        if items:
            return items[0]['id']
    except HttpError:
        pass # 실패하면 다음 엔진으로 무시하고 토스
        
    # 차선책 2: 범용 검색(Search) 엔진 인터페이스 가동 (HttpError 회피 최적화)
    try:
        search_response = youtube.search().list(
            q=identity,
            type='channel',
            part='id',
            maxResults=1
        ).execute()
        search_items = search_response.get('items', [])
        if search_items:
            return search_items[0]['id']['channelId']
    except HttpError as e:
        st.error(f"❌ YouTube API 호출 한도가 초과되었거나 Key가 유효하지 않습니다. (상세 오차: {e})")
        return None
        
    return None

def get_channel_videos(youtube, channel_id, video_type_filter, search_keyword):
    try:
        ch_resp = youtube.channels().list(part='contentDetails', id=channel_id).execute()
        if not ch_resp.get('items'):
            return []
        upload_playlist_id = ch_resp['items'][0]['contentDetails']['relatedPlaylists']['uploads']
    except HttpError as e:
        st.error(f"❌ 채널 메타데이터 정보를 가져오는데 실패했습니다: {e}")
        return []
    
    one_year_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=365)
    video_ids = []
    next_page_token = None
    
    try:
        for _ in range(2):
            playlist_resp = youtube.playlistItems().list(
                part='snippet',
                playlistId=upload_playlist_id,
                maxResults=50,
                pageToken=next_page_token
            ).execute()
            
            for item in playlist_resp.get('items', []):
                pub_at_str = item['snippet']['publishedAt']
                pub_date = datetime.datetime.strptime(pub_at_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
                
                if pub_date < one_year_ago:
                    break
                video_ids.append(item['snippet']['resourceId']['videoId'])
                
            next_page_token = playlist_resp.get('nextPageToken')
            if not next_page_token or len(video_ids) >= 100:
                break
    except HttpError as e:
        st.error(f"❌ 영상 목록을 패치하는 중 오류가 발생했습니다: {e}")
        return []
            
    if not video_ids:
        return []

    try:
        video_resp = youtube.videos().list(
            part='snippet,statistics,contentDetails',
            id=','.join(video_ids)
        ).execute()
    except HttpError as e:
        st.error(f"❌ 영상 상세 데이터 검색 파이프라인 오류: {e}")
        return []
    
    filtered_videos = []
    
    for v_item in video_resp.get('items', []):
        snippet = v_item['snippet']
        title = snippet['title']
        
        if search_keyword and search_keyword.lower() not in title.lower():
            continue
            
        duration_str = v_item['contentDetails']['duration']
        duration_secs = isodate.parse_duration(duration_str).total_seconds()
        
        if video_type_filter == "숏츠(Shorts)" and duration_secs > 60:
            continue
        if video_type_filter == "롱폼(일반 영상)" and duration_secs <= 60:
            continue
            
        stats = v_item.get('statistics', {})
        pub_date = datetime.datetime.strptime(snippet['publishedAt'], "%Y-%m-%dT%H:%M:%SZ")
        formatted_date = pub_date.strftime("%Y.%m.%d")
        
        view_count = int(stats.get('viewCount', 0))
        like_count = int(stats.get('likeCount', 0))
        
        thumb_url = snippet['thumbnails'].get('high', {}).get('url', snippet['thumbnails']['default']['url'])
        
        video_info = {
            "title": title,
            "thumbnail": thumb_url,
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
    st.title("🔴 YouTube Channel Keyword Search")
    st.subheader("채널 내 유형별 맞춤 영상 검색 시스템")
    st.write("")
    
    col1, col2, col3 = st.columns([2, 1.5, 1])
    
    with col1:
        url_input = st.text_input("유튜브 채널 URL", placeholder="https://www.youtube.com/@채널명 입력")
    with col2:
        search_keyword = st.text_input("영상 내 검색어 (선택)", placeholder="검색할 키워드 입력")
    with col3:
        video_type = st.selectbox("영상 유형", ["롱폼(일반 영상)", "숏츠(Shorts)"])
        
    st.write("")
    search_button = st.button("검색 실행")
    
    st.markdown("<span class='notice-text'>※ 조회 결과는 최근 1년 이내 영상만 필터링되어 반영됩니다.</span>", unsafe_allow_html=True)
    st.write("")
    
    if search_button:
        if not url_input:
            st.warning("⚠️ 분석할 유튜브 채널 URL을 입력해 주세요.")
            return
            
        youtube = get_youtube_client()
        if youtube is None:
            return
            
        with st.spinner("🚀 최근 1년 이내의 영상을 조회하여 키워드 매칭 분석 중입니다..."):
            identity = extract_channel_id_or_handle(url_input)
            if not identity:
                st.error("❌ 올바르지 않은 유튜브 채널 URL 형식입니다.")
                return
                
            channel_id = fetch_channel_internal_id(youtube, identity)
            if not channel_id:
                st.error("❌ 해당 채널을 식별할 수 없습니다. URL 입력값을 다시 한번 확인해 주세요.")
                return
                
            results = get_channel_videos(youtube, channel_id, video_type, search_keyword)
            
            if not results:
                st.info(f"조회된 최근 1년 이내 영상 중 해당 조건에 맞는 영상이 존재하지 않습니다.")
                return
                
            st.success(f"📊 총 {len(results)}개의 조건 매칭 비디오를 찾았습니다.")
            st.write("")
            
            grid_html = "<div class='video-grid'>"
            for video in results:
                grid_html += f"""
                    <div class='video-card-wrapper'>
                        <a href="{video['url']}" target="_blank" style="text-decoration: none;">
                            <div class="video-card">
                                <div style="width:100%; aspect-ratio: 16/9; background-image: url('{video['thumbnail']}'); background-size: cover; background-position: center; border-radius:12px 12px 0 0;"></div>
                                <div class="video-title">{video['title']}</div>
                                <div class="video-meta">
                                    조회수 {video['views']} • 좋아요 {video['likes']}<br>
                                    업로드일: {video['date']}
                                </div>
                            </div>
                        </a>
                    </div>
                """
            grid_html += "</div>"
            
            st.markdown(grid_html, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
