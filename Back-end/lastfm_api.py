"""
Last.fm API Helper Functions
Provides similar artists, track recommendations, and genre data
"""

import os
from typing import List, Dict, Optional
import requests

# Last.fm API configuration
LASTFM_API_KEY = os.environ.get('LASTFM_API_KEY')
LASTFM_API_BASE_URL = 'https://ws.audioscrobbler.com/2.0/'

# Default headers
headers = {'User-Agent': 'SoundMatch/1.0'}


def _make_lastfm_request(method: str, params: dict, limit: int = 10) -> dict:
    """
    Make a request to Last.fm API with common error handling.
    
    Args:
        method: Last.fm API method name
        params: Additional parameters for the request
        limit: Maximum number of results
    
    Returns:
        dict: API response data or empty dict on error
    """
    if not LASTFM_API_KEY:
        return {}
    
    try:
        request_params = {
            'method': method,
            'api_key': LASTFM_API_KEY,
            'format': 'json',
            'limit': min(limit, 100),
            **params
        }
        
        response = requests.get(LASTFM_API_BASE_URL, params=request_params, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error calling Last.fm API ({method}): {str(e)}")
        return {}
    except Exception as e:
        print(f"Unexpected error in Last.fm API ({method}): {str(e)}")
        return {}


def _normalize_list(data: dict, key: str) -> list:
    """
    Normalize Last.fm API response that can be either a dict or list.
    
    Args:
        data: Response data dictionary
        key: Key to extract from data
    
    Returns:
        list: Normalized list of items
    """
    if key not in data:
        return []
    
    items = data[key]
    if isinstance(items, dict):
        return [items]
    return items if isinstance(items, list) else []


def get_similar_artists(artist_name: str, limit: int = 10) -> List[Dict]:
    """
    Get similar artists from Last.fm.
    
    Args:
        artist_name: Name of the artist
        limit: Maximum number of similar artists to return
    
    Returns:
        list: List of similar artist dictionaries
    """
    if not LASTFM_API_KEY:
        print("⚠️  Last.fm API key not configured")
        return []
    
    data = _make_lastfm_request('artist.getSimilar', {'artist': artist_name}, limit)
    if not data:
        return []
    
    artists = _normalize_list(data.get('similarartists', {}), 'artist')
    return [
        {
            'name': artist.get('name', ''),
            'mbid': artist.get('mbid', ''),
            'match': float(artist.get('match', 0)) if artist.get('match') else 0.0,
            'url': artist.get('url', '')
        }
        for artist in artists[:limit]
    ]


def get_similar_tracks(track_name: str, artist_name: str, limit: int = 10) -> List[Dict]:
    """
    Get similar tracks from Last.fm.
    
    Args:
        track_name: Name of the track
        artist_name: Name of the artist
        limit: Maximum number of similar tracks to return
    
    Returns:
        list: List of similar track dictionaries
    """
    if not LASTFM_API_KEY:
        return []
    
    data = _make_lastfm_request('track.getSimilar', {'track': track_name, 'artist': artist_name}, limit)
    if not data:
        return []
    
    tracks = _normalize_list(data.get('similartracks', {}), 'track')
    return [
        {
            'name': track.get('name', ''),
            'artist': track.get('artist', {}).get('name', '') if isinstance(track.get('artist'), dict) else track.get('artist', ''),
            'match': float(track.get('match', 0)) if track.get('match') else 0.0,
            'url': track.get('url', '')
        }
        for track in tracks[:limit]
    ]


def get_artist_top_tracks(artist_name: str, limit: int = 10) -> List[Dict]:
    """
    Get top tracks for an artist from Last.fm.
    
    Args:
        artist_name: Name of the artist
        limit: Maximum number of tracks to return
    
    Returns:
        list: List of top track dictionaries
    """
    if not LASTFM_API_KEY:
        return []
    
    data = _make_lastfm_request('artist.getTopTracks', {'artist': artist_name}, limit)
    if not data:
        return []
    
    tracks = _normalize_list(data.get('toptracks', {}), 'track')
    return [
        {
            'name': track.get('name', ''),
            'artist': track.get('artist', {}).get('name', '') if isinstance(track.get('artist'), dict) else artist_name,
            'playcount': int(track.get('playcount', 0)) if track.get('playcount') else 0,
            'listeners': int(track.get('listeners', 0)) if track.get('listeners') else 0,
            'url': track.get('url', '')
        }
        for track in tracks[:limit]
    ]


def get_artist_tags(artist_name: str, limit: int = 10) -> List[Dict]:
    """
    Get tags (genres) for an artist from Last.fm.
    
    Args:
        artist_name: Name of the artist
        limit: Maximum number of tags to return
    
    Returns:
        list: List of tag dictionaries with name and count
    """
    if not LASTFM_API_KEY:
        return []
    
    data = _make_lastfm_request('artist.getTopTags', {'artist': artist_name}, limit)
    if not data:
        return []
    
    tags = _normalize_list(data.get('toptags', {}), 'tag')
    return [
        {
            'name': tag.get('name', ''),
            'count': int(tag.get('count', 0)) if tag.get('count') else 0,
            'url': tag.get('url', '')
        }
        for tag in tags[:limit]
    ]


def search_artists(query: str, limit: int = 10) -> List[Dict]:
    """
    Search for artists on Last.fm.
    
    Args:
        query: Search query
        limit: Maximum number of results
    
    Returns:
        list: List of artist dictionaries
    """
    if not LASTFM_API_KEY:
        return []
    
    data = _make_lastfm_request('artist.search', {'artist': query}, limit)
    if not data or 'results' not in data or 'artistmatches' not in data['results']:
        return []
    
    artists = _normalize_list(data['results']['artistmatches'], 'artist')
    return [
        {
            'name': artist.get('name', ''),
            'mbid': artist.get('mbid', ''),
            'listeners': int(artist.get('listeners', 0)) if artist.get('listeners') else 0,
            'url': artist.get('url', '')
        }
        for artist in artists[:limit]
    ]


def get_tag_top_artists(tag: str, limit: int = 10) -> List[Dict]:
    """
    Get top artists for a tag/genre from Last.fm.
    
    Args:
        tag: Tag/genre name (e.g., 'rock', 'jazz', 'indie')
        limit: Maximum number of artists to return
    
    Returns:
        list: List of artist dictionaries
    """
    if not LASTFM_API_KEY:
        return []
    
    data = _make_lastfm_request('tag.getTopArtists', {'tag': tag}, limit)
    if not data:
        return []
    
    artists = _normalize_list(data.get('topartists', {}), 'artist')
    return [
        {
            'name': artist.get('name', ''),
            'mbid': artist.get('mbid', ''),
            'listeners': int(artist.get('listeners', 0)) if artist.get('listeners') else 0,
            'url': artist.get('url', '')
        }
        for artist in artists[:limit]
    ]

