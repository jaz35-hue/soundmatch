"""
YouTube Data API v3 Helper Functions
Handles video search, recommendations, and metadata retrieval
"""

import requests
import os
import re
from typing import List, Dict, Optional


# YouTube API configuration
YOUTUBE_API_KEY = os.environ.get('YOUTUBE_API_KEY')
YOUTUBE_API_BASE_URL = 'https://www.googleapis.com/youtube/v3'


def search_videos(query: str, max_results: int = 10, video_category_id: str = '10', order: str = 'relevance') -> List[Dict]:
    """
    Search for videos on YouTube.
    
    Args:
        query: Search query (e.g., "Dua Lipa Levitating")
        max_results: Maximum number of results (default 10, max 50)
        video_category_id: Category ID (10 = Music)
        order: Sort order ('relevance', 'viewCount', 'rating', 'date')
    
    Returns:
        list: List of video dictionaries with id, title, channel, thumbnail, etc.
    """
    if not YOUTUBE_API_KEY:
        print("⚠️  YouTube API key not configured")
        return []
    
    try:
        url = f'{YOUTUBE_API_BASE_URL}/search'
        params = {
            'part': 'snippet',
            'q': query,
            'type': 'video',
            'videoCategoryId': video_category_id,  # 10 = Music
            'maxResults': min(max_results, 50),
            'key': YOUTUBE_API_KEY,
            'order': order
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        videos = []
        for item in data.get('items', []):
            video = {
                'video_id': item['id']['videoId'],
                'title': item['snippet']['title'],
                'channel': item['snippet']['channelTitle'],
                'thumbnail': item['snippet']['thumbnails'].get('high', {}).get('url', ''),
                'description': item['snippet']['description'][:200],  # Truncate description
                'published_at': item['snippet']['publishedAt']
            }
            videos.append(video)
        
        return videos
        
    except requests.HTTPError as e:
        if e.response and e.response.status_code == 403:
            print(f"⚠️  YouTube API 403 Forbidden - API key may be invalid, expired, or have restrictions")
            print(f"   Check your YouTube API key in Google Cloud Console")
            print(f"   Ensure YouTube Data API v3 is enabled and the key has proper permissions")
        else:
            print(f"Error searching YouTube videos: {str(e)}")
        return []
    except requests.RequestException as e:
        print(f"Error searching YouTube videos: {str(e)}")
        return []
    except Exception as e:
        print(f"Unexpected error in YouTube search: {str(e)}")
        return []


def get_video_details(video_ids: List[str]) -> List[Dict]:
    """
    Get detailed information about videos (views, likes, duration).
    
    Args:
        video_ids: List of YouTube video IDs
    
    Returns:
        list: List of video dictionaries with stats
    """
    if not YOUTUBE_API_KEY or not video_ids:
        return []
    
    try:
        url = f'{YOUTUBE_API_BASE_URL}/videos'
        params = {
            'part': 'statistics,contentDetails,snippet',
            'id': ','.join(video_ids[:50]),  # Max 50 IDs per request
            'key': YOUTUBE_API_KEY
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        videos = []
        for item in data.get('items', []):
            stats = item.get('statistics', {})
            video = {
                'video_id': item['id'],
                'title': item['snippet']['title'],
                'channel': item['snippet']['channelTitle'],
                'thumbnail': item['snippet']['thumbnails'].get('high', {}).get('url', ''),
                'views': int(stats.get('viewCount', 0)),
                'likes': int(stats.get('likeCount', 0)),
                'duration': item.get('contentDetails', {}).get('duration', ''),
                'published_at': item['snippet']['publishedAt']
            }
            videos.append(video)
        
        return videos
        
    except requests.RequestException as e:
        print(f"Error getting YouTube video details: {str(e)}")
        return []
    except Exception as e:
        print(f"Unexpected error getting video details: {str(e)}")
        return []


def get_related_videos(video_id: str, max_results: int = 10) -> List[Dict]:
    """
    Get videos related to a given video (YouTube's recommendation algorithm).
    
    Args:
        video_id: YouTube video ID
        max_results: Maximum number of related videos
    
    Returns:
        list: List of related video dictionaries
    """
    if not YOUTUBE_API_KEY:
        return []
    
    try:
        # First, get the video details to extract keywords
        url = f'{YOUTUBE_API_BASE_URL}/videos'
        params = {
            'part': 'snippet',
            'id': video_id,
            'key': YOUTUBE_API_KEY
        }
        
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            return []
        
        data = response.json()
        items = data.get('items', [])
        if not items:
            return []
        
        video_snippet = items[0].get('snippet', {})
        title = video_snippet.get('title', '')
        channel = video_snippet.get('channelTitle', '')
        
        # Extract keywords from title (remove common words)
        title_words = [w for w in title.split() if len(w) > 3 and w.lower() not in ['official', 'video', 'audio', 'music', 'song', 'lyrics', 'hd', '4k']]
        search_query = ' '.join(title_words[:3])  # Use first 3 meaningful words
        
        # If we have channel name, search for similar artists
        if channel and len(search_query) < 5:
            search_query = f"{channel} music"
        
        if not search_query:
            return []
        
        # Search for similar videos using extracted keywords
        return search_videos(search_query, max_results=max_results)
        
    except requests.RequestException as e:
        print(f"Error getting related YouTube videos: {str(e)}")
        return []
    except Exception as e:
        print(f"Unexpected error getting related videos: {str(e)}")
        return []


def search_track_on_youtube(track_name: str, artist_name: str, prefer_official: bool = True) -> Optional[Dict]:
    """
    Search for a specific track on YouTube, preferring official videos.
    Uses scoring system to rank results.
    
    Args:
        track_name: Name of the track
        artist_name: Name of the artist
        prefer_official: Prefer "Official Video" or "Official Audio" in title
    
    Returns:
        dict: Best video dictionary or None if not found
    """
    # Try different query formats with exclusions
    queries = [
        f"{artist_name} {track_name} official video -lyrics -live -cover -remix",
        f"{artist_name} {track_name} official audio -lyrics -live -cover -remix",
        f"{artist_name} {track_name} -lyrics -live -cover -remix",
        f'"{track_name}" "{artist_name}" -lyrics -live'
    ]
    
    all_candidates = []
    seen_video_ids = set()
    
    for query in queries:
        videos = search_videos(query, max_results=10)
        for video in videos:
            video_id = video.get('video_id')
            if video_id and video_id not in seen_video_ids:
                seen_video_ids.add(video_id)
                all_candidates.append(video)
    
    if not all_candidates:
        return None
    
    # Score and rank videos
    scored_videos = []
    for video in all_candidates:
        score = 0
        title_lower = video['title'].lower()
        channel_lower = video.get('channel', '').lower()
        artist_lower = artist_name.lower()
        
        # Positive scoring
        if 'official video' in title_lower:
            score += 50
        elif 'official audio' in title_lower:
            score += 45
        elif 'official' in title_lower:
            score += 30
        
        # Prefer artist's official channel
        if artist_lower in channel_lower or channel_lower in artist_lower:
            score += 20
        
        # Negative scoring (exclude unwanted content)
        if 'lyrics' in title_lower:
            score -= 30
        if 'live' in title_lower or 'concert' in title_lower:
            score -= 25
        if 'cover' in title_lower:
            score -= 20
        if 'remix' in title_lower:
            score -= 15
        if 'karaoke' in title_lower:
            score -= 30
        if 'instrumental' in title_lower:
            score -= 10
        
        scored_videos.append((score, video))
    
    # Sort by score (descending) and return best
    scored_videos.sort(key=lambda x: x[0], reverse=True)
    
    if scored_videos and scored_videos[0][0] > 0:  # Only return if score is positive
        return scored_videos[0][1]
    
    return None


def rank_videos_by_popularity(videos: List[Dict], exclude_keywords: List[str] = None) -> List[Dict]:
    """
    Rank videos by popularity and quality (views, likes, official status).
    Filters out unwanted content (lyrics, live, covers).
    
    Args:
        videos: List of video dictionaries
        exclude_keywords: Keywords to exclude (default: ['lyrics', 'live', 'cover', 'karaoke'])
    
    Returns:
        list: Sorted videos by quality and popularity score
    """
    if not videos:
        return []
    
    if exclude_keywords is None:
        exclude_keywords = ['lyrics', 'live', 'concert', 'cover', 'karaoke', 'instrumental']
    
    # Get video IDs to fetch stats and duration
    video_ids = [v['video_id'] for v in videos]
    detailed_videos = get_video_details(video_ids)
    
    # Create a mapping of video_id to details
    details_map = {v['video_id']: v for v in detailed_videos}
    
    # Score and rank videos
    scored_videos = []
    for video in videos:
        video_id = video['video_id']
        details = details_map.get(video_id, {})
        
        title_lower = video.get('title', '').lower()
        channel_lower = video.get('channel', '').lower()
        
        # Skip videos with excluded keywords
        if any(keyword in title_lower for keyword in exclude_keywords):
            continue
        
        views = details.get('views', 0)
        likes = details.get('likes', 0)
        duration = details.get('duration', '')
        
        # Calculate duration in seconds (YouTube format: PT3M45S)
        duration_seconds = parse_youtube_duration(duration)
        
        # Filter by duration: prefer 2-6 minutes for official videos
        if duration_seconds > 0:
            if duration_seconds < 60 or duration_seconds > 600:  # Less than 1 min or more than 10 min
                continue  # Skip very short (trailers) or very long (concerts) videos
        
        # Quality score based on title
        quality_score = 0
        if 'official video' in title_lower:
            quality_score += 50
        elif 'official audio' in title_lower:
            quality_score += 45
        elif 'official' in title_lower:
            quality_score += 30
        
        # Popularity score: views + (likes * 100)
        popularity_score = views + (likes * 100)
        
        # Combined score: quality + popularity (normalized)
        # Normalize popularity to 0-50 range (assuming max views ~1B)
        normalized_popularity = min(50, (popularity_score / 1000000) * 50)
        final_score = quality_score + normalized_popularity
        
        scored_videos.append({
            **video,
            'views': views,
            'likes': likes,
            'duration_seconds': duration_seconds,
            'quality_score': quality_score,
            'popularity_score': popularity_score,
            'final_score': final_score
        })
    
    # Sort by final score (descending)
    scored_videos.sort(key=lambda x: x.get('final_score', 0), reverse=True)
    
    return scored_videos


def parse_youtube_duration(duration: str) -> int:
    """
    Parse YouTube duration format (PT3M45S) to seconds.
    
    Args:
        duration: YouTube duration string (e.g., "PT3M45S")
    
    Returns:
        int: Duration in seconds, or 0 if parsing fails
    """
    if not duration or not duration.startswith('PT'):
        return 0
    
    try:
        import re
        # Extract hours, minutes, seconds
        hours = re.search(r'(\d+)H', duration)
        minutes = re.search(r'(\d+)M', duration)
        seconds = re.search(r'(\d+)S', duration)
        
        total_seconds = 0
        if hours:
            total_seconds += int(hours.group(1)) * 3600
        if minutes:
            total_seconds += int(minutes.group(1)) * 60
        if seconds:
            total_seconds += int(seconds.group(1))
        
        return total_seconds
    except:
        return 0

