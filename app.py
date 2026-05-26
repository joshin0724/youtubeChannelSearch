import streamlit as st
import re
from googleapiclient.discovery import build
import datetime
import isodate

# -------------------------------------------------------------
# 1. 유튜브 스타일 다크모드 및 모바일/PC 반응형 CSS 주입
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
        border-radius: 40px !important;
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
        width: 100%; /* 모바일에서 터치하기 편하도록 가로폭 맞춤 */
    }
    .stButton>button:hover {
        background-color: #FF0000 !important;
    }
    
    /* 📱 모바일/PC 통합 하이브리드 반응형 그리드 시스템 */
    .video-grid {
        display: flex;
        flex-wrap: wrap;
        gap: 16px;
        justify-content: flex-start;
    }
    .video-card-wrapper {
        flex: 1 1 calc(25% - 16px); /* PC 버전: 한 줄에 4개 분할 배치 */
        min-width: 250px; /* 화면이 작아지면 카드가 줄어들다가 모바일 크기에서 자동으로 줄바꿈 */
        max-width: 100%;
        box-sizing: border-box;
    }
    @media (max-width: 768px) {
        .video-card-wrapper {
            flex: 1 1 calc(50% - 16px); /* 태블릿/대형 모바일: 한 줄에 2개 */
        }
    }
    @media (max-width: 480px) {
        .video-card-wrapper {
            flex: 1 1 100%; /* 소형 모바일: 한 줄에 1개 꽉 차게 */
        }
    }

    /* 카드 내부 상세 디자인 */
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
        api_key = st.secrets["YOUTUBE_API_KEY"]
        return build('youtube', 'v3', developerKey=api_key)
    except Exception:
        st.error("🔒 Streamlit Advanced Settings에 'YOUTUBE_API_KEY'가 설정되지 않았습니다.")
        return None

def extract_channel_id_or_handle(url):
    handle_match = re.search(r'youtube\.com/(@[^/?]+)', url)
    if handle_match:
        return handle_match.group(1)
    
    id_match = re.search(r'youtube\.com/channel/([^/?]+)', url)
    if id_match:
        return id_match.group(1)
    
    cleaned = url.strip().split('/')[-1].split('?')[0]
    if cleaned.startswith('@'):
        return cleaned
    return None

def fetch_channel_internal_id(youtube, identity):
    if identity.startswith('UC'):
        return identity
    
    response = youtube.channels().list(part='id', forHandle=identity).execute()
    items = response.get('items', [])
    if items:
        return items[0]['id']
    return None

def get_channel_videos(youtube, channel_id, video_type_filter, search_keyword):
    ch_resp = youtube.channels().list(part='contentDetails', id=channel_id).execute()
    upload_playlist_id = ch_resp['items'][0]['contentDetails']['relatedPlaylists']['uploads']
    
    # 최근 1년 이내 계산 필터 변수 정의
    one_year_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=365)
    
    video_ids = []
    next_page_token = None
    
    # 1년 미만 영상 검색을 위해 최대 2페이지(총 100개 영상 슬라이싱) 추적
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
            
            # 1년 이전에 올린 영상이 나오는 순간 탐색을 조기 종료하여 자원 절약
            if pub_date < one_year_ago:
                break
            video_ids.append(item['snippet']['resourceId']['videoId'])
            
        next_page_token = playlist_resp.get('nextPageToken')
        if not next_page_token or len(video_ids) >= 100:
            break
            
    if not video_ids:
        return []

    # 상세 데이터 묶음 가져오기 (시간 및 카운트 검증)
    video_resp = youtube.videos().list(
        part='snippet,statistics,contentDetails',
        id=','.join(video_ids)
    ).execute()
    
    filtered_videos = []
    
    for v_item in video_resp.get('items', []):
        snippet = v_item['snippet']
        title = snippet['title']
        
        # [요구사항 1, 2] 제목 내 검색어 존재 여부 필터링 (대소문자 무시)
        if search_keyword and search_keyword.lower() not in title.lower():
            continue
            
        # [요구사항 3] 숏츠 필터링 로직 정밀화
        duration_str = v_item['contentDetails']['duration']
        duration_secs = isodate.parse_duration(duration_str).total_seconds()
        
        # 판정 기준: 60초(1분) 이하의 영상은 확실하게 Shorts로 분류
        if video_type_filter == "숏츠(Shorts)" and duration_secs > 60:
            continue
        if video_type_filter == "롱폼(일반 영상)" and duration_secs <= 60:
            continue
            
        stats = v_item.get('statistics', {})
        pub_date = datetime.datetime.strptime(snippet['publishedAt'], "%Y-%m-%dT%H:%M:%SZ")
        formatted_date = pub_date.strftime("%Y.%m.%d")
        
        view_count = int(stats.get('viewCount', 0))
        like_count = int(stats.get('likeCount', 0))
        
        # 썸네일 고화질 매핑
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
    
    # 인풋 영역 UI 디자인 레이아웃 (반응형 그리드)
    col1, col2, col3 = st.columns([2, 1.5, 1])
    
    with col1:
        url_input = st.text_input("유튜브 채널 URL", placeholder="https://www.youtube.com/@채널명 입력")
    with col2:
        search_keyword = st.text_input("영상 내 검색어 (선택)", placeholder="검색할 키워드 입력")
    with col3:
        video_type = st.selectbox("영상 유형", ["롱폼(일반 영상)", "숏츠(Shorts)"])
        
    st.write("")
    search_button = st.button("검색 실행")
    
    # [요구사항 4] 공지 문구 추가
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
                st.error("❌ 올바르지 않은 유튜브 채널 URL 형식입니다. 핸들(@) 형식을 확인해 주세요.")
                return
                
            channel_id = fetch_channel_internal_id(youtube, identity)
            if not channel_id:
                st.error("❌ 해당 채널을 찾을 수 없습니다. URL 혹은 채널 명을 확인해 주세요.")
                return
                
            results = get_channel_videos(youtube, channel_id, video_type, search_keyword)
            
            if not results:
                st.info(f"조회된 최근 1년 이내 영상 중 해당 조건에 맞는 영상이 존재하지 않습니다.")
                return
                
            st.success(f"📊 총 {len(results)}개의 조건 매칭 비디오를 찾았습니다.")
            st.write("")
            
            # [요구사항 5] HTML 반응형 플렉스박스 매핑으로 모바일 화면 깨짐 방지
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
