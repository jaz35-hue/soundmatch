"""
Spotify API Helper Functions
Handles all interactions with the Spotify Web API
"""

import requests
import time
from datetime import datetime, timedelta, timezone
from flask import current_app

# Cache for client credentials token (valid for 1 hour)
_app_token_cache = {
    'token': None,
    'expires_at': None
}


# =============================================================================
# Token Management
# =============================================================================

def get_valid_spotify_token(user):
    """
    Get a valid Spotify access token for the user.
    Automatically refreshes the token if it's expired.
    
    Args:
        user: User object with Spotify OAuth credentials
    
    Returns:
        str: Valid access token, or None if refresh fails
    """
    from app import db  # Import here to avoid circular imports
    
    # Check if user has Spotify credentials
    if not user.spotify_refresh_token:
        print(f"User {user.username} has no Spotify refresh token")
        return None
    
    # Check if token is still valid
    if user.spotify_token_expires_at:
        now = datetime.now(timezone.utc)
        # Ensure expires_at is timezone-aware for comparison
        expires_at = user.spotify_token_expires_at
        if expires_at.tzinfo is None:
            # If stored as naive datetime, assume it's UTC
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        # Add 5 minute buffer
        if now < expires_at - timedelta(minutes=5):
            # Token is still valid
            return user.spotify_access_token
    
    # Token expired or missing, refresh it
    print(f"Refreshing Spotify token for user {user.username}")
    
    try:
        token_url = 'https://accounts.spotify.com/api/token'
        
        # Get credentials from app config
        client_id = current_app.config.get('SPOTIFY_CLIENT_ID')
        client_secret = current_app.config.get('SPOTIFY_CLIENT_SECRET')
        
        if not client_id or not client_secret:
            print("Missing Spotify credentials in config")
            return None
        
        # Request new token
        token_data = {
            'grant_type': 'refresh_token',
            'refresh_token': user.spotify_refresh_token,
            'client_id': client_id,
            'client_secret': client_secret
        }
        
        response = requests.post(token_url, data=token_data)
        response.raise_for_status()
        token_info = response.json()
        
        # Update user's token
        user.spotify_access_token = token_info['access_token']
        user.spotify_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=token_info.get('expires_in', 3600))
        
        # Update refresh token if provided (some don't)
        if 'refresh_token' in token_info:
            user.spotify_refresh_token = token_info['refresh_token']
        
        db.session.commit()
        print(f"✅ Token refreshed for {user.username}")
        
        return user.spotify_access_token
        
    except requests.RequestException as e:
        print(f"Error refreshing Spotify token: {str(e)}")
        return None
    except Exception as e:
        print(f"Unexpected error refreshing token: {str(e)}")
        return None


# =============================================================================
# Helper Functions
# =============================================================================

def _make_spotify_request(url, headers, params=None, method='GET', data=None, json=None, max_retries=3, silent=False):
    """
    Make a Spotify API request with retry logic and rate limit handling.
    
    Args:
        url: API endpoint URL
        headers: Request headers
        params: Query parameters
        method: HTTP method (GET, POST, PUT, etc.)
        data: Form data
        json: JSON data
        max_retries: Maximum number of retry attempts
        silent: If True, suppress non-critical error messages
    
    Returns:
        requests.Response or None if all retries fail
    """
    for attempt in range(max_retries):
        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=headers, params=params, timeout=10)
            elif method.upper() == 'POST':
                response = requests.post(url, headers=headers, params=params, data=data, json=json, timeout=10)
            elif method.upper() == 'PUT':
                response = requests.put(url, headers=headers, params=params, data=data, json=json, timeout=10)
            else:
                response = requests.request(method, url, headers=headers, params=params, data=data, json=json, timeout=10)
            
            # Handle rate limiting (429 Too Many Requests)
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 5))
                # Cap wait time to avoid hanging too long (e.g. max 10 seconds)
                # If Spotify asks for more, we might just fail this request
                wait_time = min(retry_after, 10) 
                
                if not silent:
                    print(f"Rate limited (429). Waiting {wait_time}s... (Spotify asked for {retry_after}s)")
                
                time.sleep(wait_time)
                
                # If the wait time was capped and less than requested, 
                # we might still fail the next request, but we'll try once more
                continue
            
            # Return response for caller to handle (401, 403, 200, etc.)
            return response
            
        except requests.Timeout:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff
                if not silent:
                    print(f"Request timeout. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                if not silent:
                    print(f"Request timeout after {max_retries} attempts")
                return None
        except requests.RequestException as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff
                if not silent:
                    print(f"Request error: {str(e)}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                if not silent:
                    print(f"Request failed after {max_retries} attempts")
                return None
    
    return None


# =============================================================================
# User Data Retrieval
# =============================================================================

def get_user_top_tracks(access_token, time_range='medium_term', limit=20):
    """
    Fetch user's top tracks from Spotify.
    """
    try:
        url = 'https://api.spotify.com/v1/me/top/tracks'
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {
            'time_range': time_range,
            'limit': min(limit, 50)
        }
        
        response = _make_spotify_request(url, headers, params=params)
        
        if not response:
            return []
            
        response.raise_for_status()
        data = response.json()
        
        tracks = []
        for item in data.get('items', []):
            normalized = normalize_track(item)
            if normalized:
                tracks.append(normalized)
        
        return tracks
        
    except Exception as e:
        print(f"Error fetching top tracks: {str(e)}")
        return []


def get_user_top_artists(access_token, time_range='medium_term', limit=20):
    """
    Fetch user's top artists from Spotify.
    """
    try:
        url = 'https://api.spotify.com/v1/me/top/artists'
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {
            'time_range': time_range,
            'limit': min(limit, 50)
        }
        
        response = _make_spotify_request(url, headers, params=params)
        
        if not response:
            return []
            
        response.raise_for_status()
        data = response.json()
        
        artists = []
        for item in data.get('items', []):
            artists.append({
                'id': item['id'],
                'name': item['name'],
                'genres': item.get('genres', []),
                'image_url': item['images'][0]['url'] if item['images'] else None,
                'spotify_url': item['external_urls']['spotify'],
                'popularity': item.get('popularity', 0)
            })
        
        return artists
        
    except Exception as e:
        print(f"Error fetching top artists: {str(e)}")
        return []


def get_user_recently_played(access_token, limit=50):
    """
    Fetch user's recently played tracks.
    """
    try:
        url = 'https://api.spotify.com/v1/me/player/recently-played'
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {'limit': min(limit, 50)}
        
        response = _make_spotify_request(url, headers, params=params)
        
        if not response:
            return []
            
        response.raise_for_status()
        data = response.json()
        
        tracks = []
        for item in data.get('items', []):
            track = item['track']
            normalized = normalize_track(track)
            if normalized:
                # Add played_at timestamp for recently played
                normalized['played_at'] = item.get('played_at')
                tracks.append(normalized)
        
        return tracks
        
    except Exception as e:
        print(f"Error fetching recently played: {str(e)}")
        return []


# =============================================================================
# Recommendations
# =============================================================================

def get_recommendations(access_token, seed_tracks=None, seed_artists=None, seed_genres=None, **params):
    """
    Get track recommendations from Spotify.
    """
    try:
        url = 'https://api.spotify.com/v1/recommendations'
        headers = {'Authorization': f'Bearer {access_token}'}
        
        # Build parameters
        request_params = params.copy()
        
        # Add market parameter (helps with availability)
        if 'market' not in request_params:
            request_params['market'] = 'US'
        
        # Add seeds
        if seed_tracks:
            request_params['seed_tracks'] = ','.join(seed_tracks[:5])
        if seed_artists:
            request_params['seed_artists'] = ','.join(seed_artists[:5])
        if seed_genres:
            request_params['seed_genres'] = ','.join(seed_genres[:5])
        
        # Validate we have at least one seed
        has_seeds = bool(seed_tracks or seed_artists or seed_genres)
        if not has_seeds:
            print("No seeds provided for recommendations")
            return []
        
        # Set default limit if not provided
        if 'limit' not in request_params:
            request_params['limit'] = 20
        
        print(f"Requesting recommendations with params: {request_params}")
        
        response = _make_spotify_request(url, headers, params=request_params)
        
        if not response:
            return []
        
        # Handle 404 - recommendations endpoint is deprecated (Nov 2024)
        if response.status_code == 404:
            print(f"⚠️  Recommendations endpoint deprecated (404) - This endpoint is no longer available for new applications")
            print(f"   Using alternative recommendation methods instead")
            return []
        
        # Handle 401 - authentication issue
        if response.status_code == 401:
            print(f"Authentication failed (401) - Token may be invalid or missing scopes")
            return []
        
        response.raise_for_status()
        data = response.json()
        
        recommendations = []
        for track in data.get('tracks', []):
            normalized = normalize_track(track)
            if normalized:
                recommendations.append(normalized)
        
        print(f"Successfully got {len(recommendations)} recommendations from Spotify")
        return recommendations
        
    except Exception as e:
        print(f"Error getting recommendations: {str(e)}")
        return []


def search_tracks(access_token, query, limit=20):
    """
    Search for tracks on Spotify.
    """
    try:
        url = 'https://api.spotify.com/v1/search'
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {
            'q': query,
            'type': 'track',
            'limit': min(limit, 50)
        }
        
        response = _make_spotify_request(url, headers, params=params)
        
        if not response:
            return []
            
        response.raise_for_status()
        data = response.json()
        
        tracks = []
        for track in data.get('tracks', {}).get('items', []):
            normalized = normalize_track(track)
            if normalized:
                tracks.append(normalized)
        
        return tracks
        
    except Exception as e:
        print(f"Error searching tracks: {str(e)}")
        return []


def get_track(access_token, track_id):
    """
    Get a single track by ID.
    
    Args:
        access_token: Valid Spotify access token
        track_id: Spotify track ID
    
    Returns:
        dict: Normalized track dictionary, or None if failed
    """
    try:
        url = f'https://api.spotify.com/v1/tracks/{track_id}'
        headers = {'Authorization': f'Bearer {access_token}'}
        
        response = _make_spotify_request(url, headers)
        
        if not response or response.status_code != 200:
            return None
            
        track = response.json()
        return normalize_track(track)
        
    except Exception as e:
        print(f"Error getting track {track_id}: {str(e)}")
        return None


def normalize_track(track):
    """
    Normalize track data to standard format.
    
    Args:
        track: Track dictionary from Spotify API
    
    Returns:
        dict: Normalized track dictionary, or None if track is invalid
    """
    if not track or not track.get('id'):
        return None
    
    # Extract artist name(s) as string
    artist_names = []
    if track.get('artist'):  # Already a string
        artist_string = track['artist']
    elif track.get('artists'):
        if isinstance(track['artists'], list):
            artist_names = [a.get('name', 'Unknown Artist') if isinstance(a, dict) else str(a) for a in track['artists']]
        else:
            artist_names = [str(track['artists'])]
        artist_string = ', '.join(artist_names) if artist_names else 'Unknown Artist'
    else:
        artist_string = 'Unknown Artist'
    
    # Extract image URL from album
    image_url = track.get('image_url')
    if not image_url and track.get('album'):
        album = track['album']
        if isinstance(album, dict) and album.get('images'):
            image_url = album['images'][0].get('url') if album['images'] else None
    
    # Extract Spotify URL
    spotify_url = track.get('spotify_url')
    if not spotify_url and track.get('external_urls'):
        spotify_url = track['external_urls'].get('spotify')
    
    # Extract preview URL - Spotify provides 30-second previews for most tracks
    preview_url = track.get('preview_url')
    # Some tracks might have null preview_url, which is valid (not all tracks have previews)
    # Keep it as None if not available, don't try to generate one
    
    return {
        'id': track['id'],
        'name': track.get('name', 'Unknown Track'),
        'artist': artist_string,  # String for display
        'artists': track.get('artists', []),  # Keep as array for consistency
        'album': track.get('album', {}),  # Keep as object for consistency
        'image_url': image_url,  # For display
        'preview_url': preview_url,  # 30-second preview URL (can be null)
        'spotify_url': spotify_url,
        'external_urls': track.get('external_urls', {}),
        'popularity': track.get('popularity', 0)
    }


def get_artist_genres(access_token, artist_id):
    """
    Get genres for an artist.
    """
    try:
        url = f'https://api.spotify.com/v1/artists/{artist_id}'
        headers = {'Authorization': f'Bearer {access_token}'}
        
        response = _make_spotify_request(url, headers)
        
        if response and response.status_code == 200:
            artist = response.json()
            genres = artist.get('genres', [])
            if genres:
                print(f"Found {len(genres)} genres for artist {artist_id}: {genres[:3]}")
            else:
                print(f"No genres found for artist {artist_id} - this is normal for some artists")
                # Try to infer genre from artist name or use search
                artist_name = artist.get('name', '')
                if artist_name:
                    # Try searching for the artist to see if we can find genre info
                    search_url = 'https://api.spotify.com/v1/search'
                    search_params = {
                        'q': f'artist:"{artist_name}"',
                        'type': 'artist',
                        'limit': 1
                    }
                    try:
                        search_response = _make_spotify_request(search_url, headers, params=search_params)
                        if search_response and search_response.status_code == 200:
                            search_data = search_response.json()
                            search_artists = search_data.get('artists', {}).get('items', [])
                            if search_artists and search_artists[0].get('genres'):
                                genres = search_artists[0].get('genres', [])
                                print(f"Found genres via search for {artist_name}: {genres[:3]}")
                    except:
                        pass
            return genres
        elif response and response.status_code == 404:
            print(f"Artist {artist_id} not found (404) - may be invalid ID")
            return []
        else:
            status = response.status_code if response else "Unknown"
            print(f"Failed to get artist info for {artist_id}: Status {status}")
            return []
    except Exception as e:
        print(f"Error getting artist genres for {artist_id}: {str(e)}")
        return []


def get_track_artists(access_token, track_id):
    """
    Get artist IDs from a track.
    """
    try:
        url = f'https://api.spotify.com/v1/tracks/{track_id}'
        headers = {'Authorization': f'Bearer {access_token}'}
        
        response = _make_spotify_request(url, headers)
        
        if response and response.status_code == 200:
            track = response.json()
            return [artist['id'] for artist in track.get('artists', [])]
        return []
    except Exception as e:
        print(f"Error getting track artists: {str(e)}")
        return []


def get_artist_top_tracks_for_recommendations(access_token, artist_ids, limit=20):
    """
    Fallback method: Get top tracks from multiple artists as recommendations.
    Used when recommendations API is not available (client credentials limitation).
    """
    try:
        all_tracks = []
        tracks_per_artist = max(5, limit // len(artist_ids)) if artist_ids else 10
        
        for artist_id in artist_ids[:5]:  # Limit to 5 artists
            url = f'https://api.spotify.com/v1/artists/{artist_id}/top-tracks'
            headers = {'Authorization': f'Bearer {access_token}'}
            params = {'market': 'US'}
            
            response = _make_spotify_request(url, headers, params=params)
            
            if response and response.status_code == 200:
                data = response.json()
                tracks = data.get('tracks', [])
                
                for track in tracks[:tracks_per_artist]:
                    normalized = normalize_track(track)
                    if normalized:
                        all_tracks.append(normalized)
            else:
                status = response.status_code if response else "Unknown"
                print(f"Failed to get top tracks for artist {artist_id}: {status}")
        
        # Shuffle and limit
        import random
        random.shuffle(all_tracks)
        return all_tracks[:limit]
        
    except Exception as e:
        print(f"Error getting artist top tracks: {str(e)}")
        return []


def add_track_to_spotify_library(access_token, track_id):
    """
    Add a track to the user's Spotify library (liked songs).
    """
    try:
        url = 'https://api.spotify.com/v1/me/tracks'
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        data = {'ids': [track_id]}
        
        response = _make_spotify_request(url, headers, json=data, method='PUT')
        
        if response:
            response.raise_for_status()
            return True
        return False
        
    except Exception as e:
        print(f"Error adding track to Spotify library: {str(e)}")
        return False


def get_artist_info(access_token, artist_id):
    """
    Get artist information by ID.
    """
    try:
        url = f'https://api.spotify.com/v1/artists/{artist_id}'
        headers = {'Authorization': f'Bearer {access_token}'}
        
        response = _make_spotify_request(url, headers)
        
        if response and response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        print(f"Error getting artist info: {str(e)}")
        return None
