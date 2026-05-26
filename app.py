import streamlit as st
import re
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import datetime
import isodate

# -------------------------------------------------------------
# 1. 유튜브 스타일 다크모드 및 기본 UI 디자인 세팅
# -------------------------------------------------------------
st.set_page_config(page_title="YouTube Channel Analyzer", layout="wide", page_icon="🔴")

st.markdown("""
    <style>
    /* 전체 배경 유튜브 다크모드화 */
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
    }
    .stButton>button:hover {
        background-color: #FF0000 !important;
    }
    .notice-text {
        font-size: 13px;
        color: #FF8A8A;
        margin-top: 6px;
        display: block;
    }
    /* 카드 컴포넌트 커스텀 폰트 세팅 */
    .v-title {
        font-size: 14px;
        font-weight: 600;
        color: #F1F1F1;
        margin-top: 8px;
        margin-bottom: 4px;
        line-height: 1.4;
    }
    .v-meta {
        font-size: 12px;
        color: #AAA;
        line-height: 1.5;
    }
    </style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------
# 2. YouTube API 커넥터 및 검색 핵심 비즈니스 로직
# -------------------------------------------------------------
def get_youtube_client():
    try:
        api_key = st.secrets["YOUTUBE_API_KEY"].strip()
        return build('youtube', 'v3', developerKey=api_key)
    except Exception:
        st.error("🔒 Streamlit Advanced Settings에 'YOUTUBE_API_KEY'가 설정되지 않았습니다.")
        return None

def extract_channel_id_or_handle(url):
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
    return url

def fetch_channel_internal_id(youtube, identity):
    if identity.startswith('UC'):
        return identity
        
    try:
        handle_clean = identity.replace('@', '')
        response = youtube.channels().list(part='id', forHandle=handle_clean).execute()
        items = response.get('items', [])
        if items:
            return items[0]['id']
    except HttpError:
        pass
        
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
        st.error(f"❌ YouTube API 호출 오류가 발생했습니다: {e}")
        return None
        
    return None

def get_channel_videos(youtube, channel_id, video_type_filter, search_keyword):
    try:
        ch_resp = youtube.channels().list(part='contentDetails', id=channel_id).execute()
        if not ch_resp.get('items'):
            return []
        upload_playlist_id = ch_resp['items'][0]['contentDetails']['relatedPlaylists']['uploads']
    except HttpError as e:
        st.error(f"❌ 채널 정보를 가져오는데 실패했습니다: {e}")
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
                
                v_id = item['snippet']['resourceId']['videoId']
                if v_id and v_id not in video_ids:
                    video_ids.append(v_id)
                
            next_page_token = playlist_resp.get('nextPageToken')
            if not next_page_token or len(video_ids) >= 100:
                break
    except HttpError as e:
        st.error(f"❌ 영상 목록 패치 중 오류 발생: {e}")
        return []
            
    if not video_ids:
        return []

    video_items = []
    chunk_size = 20
    
    try:
        for i in range(0, len(video_ids), chunk_size):
            chunk_ids = video_ids[i:i + chunk_size]
            video_resp = youtube.videos().list(
                part='snippet,statistics,contentDetails',
                id=','.join(chunk_ids)
            ).execute()
            video_items.extend(video_resp.get('items', []))
    except HttpError as e:
        st.error(f"❌ 영상 상세 정보를 가져오지 못했습니다: {e}")
        return []
    
    filtered_videos = []
    
    for v_item in video_items:
        snippet = v_item['snippet']
        title = snippet['title']
        
        if search_keyword and search_keyword.lower() not in title.lower():
            continue
            
        duration_str = v_item['contentDetails']['duration']
        try:
            duration_secs = isodate.parse_duration(duration_str).total_seconds()
        except Exception:
            duration_secs = 0
        
        if video_type_filter == "숏츠(Shorts)" and duration_secs > 60:
            continue
        if video_type_filter == "롱폼(일반 영상)" and duration_secs <= 60:
            continue
            
        stats = v_item.get('statistics', {})
        pub_date = datetime.datetime.strptime(snippet['publishedAt'], "%Y-%m-%dT%H:%M:%SZ")
        formatted_date = pub_date.strftime("%Y.%m.%d")
        
        view_count = int(stats.get('viewCount', 0))
        like_count = int(stats.get('likeCount', 0))
        
        thumb_url = snippet['thumbnails'].get('high', {}).get('url', snippet['thumbnails'].get('default', {}).get('url', ''))
        
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
# 3. Streamlit UI 렌더링 엔진 (버그 완전 수정 교정부)
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
            
            # 버그 해결책: Native st.columns 구조로 안전하게 분할 매핑 (한 줄에 4개 배치)
            # 이 방식은 화면 크기가 작아지면(모바일) 자동으로 한 줄에 1개씩 떨어지는 반응형을 기본 지원합니다.
            cols = st.columns(4)
            for idx, video in enumerate(results):
                col_idx = idx % 4
                with cols[col_idx]:
                    # 개별 카드 배치용 컨테이너 생성
                    with st.container(border=True):
                        # 1. 썸네일 노출
                        st.image(video['thumbnail'], use_container_width=True)
                        # 2. 제목 (클릭 시 링크 이동 하이퍼링크 결합)
                        st.markdown(f"<div class='v-title'><a href='{video['url']}' target='_blank' style='text-decoration:none; color:#F1F1F1;'>{video['title']}</a></div>", unsafe_allow_html=True)
                        # 3. 조회수 및 메타 데이터
                        st.markdown(f"""
                            <div class='v-meta'>
                                조회수 {video['views']} • 좋아요 {video['likes']}<br>
                                <b>업로드일:</b> {video['date']}
                            </div>
                        """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
