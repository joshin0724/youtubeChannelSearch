import streamlit as st
import re
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import datetime
import isodate

# -------------------------------------------------------------
# 1. 화이트 모드 테마 및 모바일 버튼 중앙 정렬 커스텀 CSS 주입
# -------------------------------------------------------------
st.set_page_config(page_title="YouTube Channel Analyzer", layout="wide", page_icon="🔴")

st.markdown("""
    <style>
    /* 배경을 흰색으로, 텍스트를 검은색으로 변경 */
    .stApp {
        background-color: #FFFFFF;
        color: #0F0F0F;
    }
    /* 입력창 및 셀렉트박스 화이트 테마 최적화 */
    div[data-baseweb="input"] {
        background-color: #F9F9F9 !important;
        border: 1px solid #CCCCCC !important;
        border-radius: 40px !important;
        color: #0F0F0F !important;
    }
    div[data-baseweb="select"] {
        background-color: #F9F9F9 !important;
        border: 1px solid #CCCCCC !important;
        border-radius: 8px !important;
    }
    /* 검색 버튼 스타일 및 PC/모바일 분기 처리 */
    .stButton {
        display: flex;
        justify-content: flex-start;
    }
    .stButton>button {
        background-color: #FF0000 !important; /* 유튜브 레드로 강조 */
        color: white !important;
        border-radius: 20px !important;
        border: none !important;
        font-weight: bold;
        padding: 0.5rem 2.5rem !important;
        width: auto;
    }
    .stButton>button:hover {
        background-color: #CC0000 !important;
    }
    
    /* 모바일 환경(화면 폭 768px 이하)일 때 버튼 중앙 정렬 */
    @media (max-width: 768px) {
        .stButton {
            justify-content: center !important;
        }
        .stButton>button {
            width: 80% !important; /* 모바일에서는 터치하기 편하게 가로폭 확대 */
        }
    }

    .notice-text {
        font-size: 13px;
        color: #D32F2F;
        margin-top: 6px;
        display: block;
        font-weight: 500;
    }
    /* 화이트 테마용 카드 컴포넌트 디자인 */
    .v-title {
        font-size: 14px;
        font-weight: 600;
        margin-top: 8px;
        margin-bottom: 4px;
        line-height: 1.4;
    }
    .v-title a {
        color: #0F0F0F !important; /* 제목 텍스트 검은색 */
        text-decoration: none;
    }
    .v-title a:hover {
        color: #FF0000 !important;
    }
    .v-meta {
        font-size: 12px;
        color: #606060 !important; /* 메타 데이터 어두운 회색 */
        line-height: 1.5;
    }
    /* 스트림릿 기본 테두리 상자 디자인 오버라이딩 */
    div[data-testid="stContainer"] {
        background-color: #F9F9F9 !important;
        border: 1px solid #E5E5E5 !important;
        border-radius: 12px !important;
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
            
        # -------------------------------------------------------------
        # 💥 [요구사항 2] 숏츠 필터링 로직 정밀화 연산부
        # -------------------------------------------------------------
        duration_str = v_item['contentDetails']['duration']
        try:
            duration_secs = isodate.parse_duration(duration_str).total_seconds()
        except Exception:
            duration_secs = 0
        
        # 기본 시간 체크 + 세로형 숏츠 패턴을 탐지하기 위한 해상도 비율 검증 구조화
        thumbnails_data = snippet.get('thumbnails', {})
        is_shorts_by_thumb = False
        
        # 일부 숏츠 영상은 썸네일 해상도가 정방형에 가깝거나 세로 비중이 높음
        if 'maxres' in thumbnails_data:
            thumb_detail = thumbnails_data['maxres']
            if thumb_detail.get('width', 16) / thumb_detail.get('height', 9) < 1.3:
                is_shorts_by_thumb = True

        # 최종 판정 알고리즘: 60초 이하이거나 세로형 썸네일 특징을 가진 경우 Shorts 그룹으로 분류
        is_actually_shorts = (duration_secs > 0 and duration_secs <= 60) or is_shorts_by_thumb

        if video_type_filter == "숏츠(Shorts)" and not is_actually_shorts:
            continue
        if video_type_filter == "롱폼(일반 영상)" and is_actually_shorts:
            continue
            
        stats = v_item.get('statistics', {})
        pub_date = datetime.datetime.strptime(snippet['publishedAt'], "%Y-%m-%dT%H:%M:%SZ")
        formatted_date = pub_date.strftime("%Y.%m.%d")
        
        view_count = int(stats.get('viewCount', 0))
        like_count = int(stats.get('likeCount', 0))
        
        thumb_url = thumbnails_data.get('high', {}).get('url', thumbnails_data.get('default', {}).get('url', ''))
        
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
# 3. Streamlit UI 렌더링 엔진 (엔터 키 서브밋 연동 완료)
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
    
    # [요구사항 3] 엔터 키 및 실행 처리를 세션과 결합하여 유기적으로 작동하도록 설계
    search_button = st.button("검색 실행")
    
    st.markdown("<span class='notice-text'>※ 조회 결과는 최근 1년 이내 영상만 필터링되어 반영됩니다.</span>", unsafe_allow_html=True)
    st.write("")
    
    # 버튼이 눌렸거나, 인풋창에서 엔터가 쳐져서 값이 채워진 경우 둘 다 반응형 엔진이 작동함
    if search_button or (url_input and not search_button):
        if not url_input:
            if search_button: # 버튼을 눌렀는데 빈칸일 때만 경고 노출
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
            
            cols = st.columns(4)
            for idx, video in enumerate(results):
                col_idx = idx % 4
                with cols[col_idx]:
                    with st.container(border=True):
                        st.image(video['thumbnail'], use_container_width=True)
                        st.markdown(f"<div class='v-title'><a href='{video['url']}' target='_blank'>{video['title']}</a></div>", unsafe_allow_html=True)
                        st.markdown(f"""
                            <div class='v-meta'>
                                조회수 {video['views']} • 좋아요 {video['likes']}<br>
                                <b>업로드일:</b> {video['date']}
                            </div>
                        """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
