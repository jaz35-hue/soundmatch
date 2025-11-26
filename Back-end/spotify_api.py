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
# User Data Retrieval
# =============================================================================

def get_user_top_tracks(access_token, time_range='medium_term', limit=20):
    """
    Fetch user's top tracks from Spotify.
    
    Args:
        access_token: Valid Spotify access token
        time_range: 'short_term' (4 weeks), 'medium_term' (6 months), 'long_term' (years)
        limit: Number of tracks to return (max 50)
    
    Returns:
        list: List of track dictionaries, or empty list on error
    """
    try:
        url = 'https://api.spotify.com/v1/me/top/tracks'
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {
            'time_range': time_range,
            'limit': min(limit, 50)
        }
        
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        
        tracks = []
        for item in data.get('items', []):
            normalized = normalize_track(item)
            if normalized:
                tracks.append(normalized)
        
        return tracks
        
    except requests.RequestException as e:
        print(f"Error fetching top tracks: {str(e)}")
        return []


def get_user_top_artists(access_token, time_range='medium_term', limit=20):
    """
    Fetch user's top artists from Spotify.
    
    Args:
        access_token: Valid Spotify access token
        time_range: 'short_term', 'medium_term', 'long_term'
        limit: Number of artists to return (max 50)
    
    Returns:
        list: List of artist dictionaries, or empty list on error
    """
    try:
        url = 'https://api.spotify.com/v1/me/top/artists'
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {
            'time_range': time_range,
            'limit': min(limit, 50)
        }
        
        response = requests.get(url, headers=headers, params=params)
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
        
    except requests.RequestException as e:
        print(f"Error fetching top artists: {str(e)}")
        return []


def get_user_recently_played(access_token, limit=50):
    """
    Fetch user's recently played tracks.
    
    Args:
        access_token: Valid Spotify access token
        limit: Number of tracks to return (max 50)
    
    Returns:
        list: List of recently played track dictionaries
    """
    try:
        url = 'https://api.spotify.com/v1/me/player/recently-played'
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {'limit': min(limit, 50)}
        
        response = requests.get(url, headers=headers, params=params)
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
        
    except requests.RequestException as e:
        print(f"Error fetching recently played: {str(e)}")
        return []


# =============================================================================
# Recommendations
# =============================================================================

def get_recommendations(access_token, seed_tracks=None, seed_artists=None, seed_genres=None, **params):
    """
    Get track recommendations from Spotify.
    
    Args:
        access_token: Valid Spotify access token
        seed_tracks: List of track IDs (up to 5)
        seed_artists: List of artist IDs (up to 5)
        seed_genres: List of genre names (up to 5)
        **params: Additional parameters like:
            - target_energy: 0.0 to 1.0
            - target_valence: 0.0 to 1.0
            - target_tempo: BPM
            - min_popularity, max_popularity: 0 to 100
            - limit: Number of recommendations (default 20, max 100)
    
    Returns:
        list: List of recommended track dictionaries
    
    Note: Total seeds (tracks + artists + genres) must be between 1 and 5
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
        
        response = requests.get(url, headers=headers, params=request_params)
        
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
        
    except requests.RequestException as e:
        print(f"Error getting recommendations: {str(e)}")
        return []


def _make_spotify_request(url, headers, params=None, max_retries=3, silent=False):
    """
    Make a Spotify API request with retry logic and rate limit handling.
    
    Args:
        url: API endpoint URL
        headers: Request headers
        params: Query parameters
        max_retries: Maximum number of retry attempts
        silent: If True, suppress non-critical error messages
    
    Returns:
        requests.Response or None if all retries fail
    """
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            
            # Handle rate limiting (429 Too Many Requests)
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 60))
                if not silent:
                    print(f"Rate limited (429). Waiting {retry_after}s...")
                time.sleep(retry_after)
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


def get_track_audio_features(access_token, track_ids, fallback_token=None):
    """
    Get audio features for multiple tracks.
    Handles batching (max 100 IDs per request), rate limiting, and errors gracefully.
    If user token fails with 403, automatically tries client credentials token as fallback.
    
    Args:
        access_token: Valid Spotify access token (user or client credentials)
        track_ids: List of track IDs (up to 100 per batch)
        fallback_token: Optional fallback token to try if primary token fails
    
    Returns:
        list: List of audio features dictionaries (one per track)
    """
    if not track_ids:
        return []
    
    all_features = []
    batch_size = 100
    tokens_to_try = [access_token]
    if fallback_token:
        tokens_to_try.append(fallback_token)
    
    for i in range(0, len(track_ids), batch_size):
        batch = track_ids[i:i + batch_size]
        url = 'https://api.spotify.com/v1/audio-features'
        params = {'ids': ','.join(batch)}
        
        success = False
        for token in tokens_to_try:
            headers = {'Authorization': f'Bearer {token}'}
            # Use silent mode for audio-features (optional feature)
            response = _make_spotify_request(url, headers, params, silent=True)
            
            if not response:
                continue
            
            # Handle specific error codes
            if response.status_code == 403:
                # Try next token if available
                if token == tokens_to_try[-1]:
                    # Last token failed, skip this batch silently
                    continue
                continue
            elif response.status_code == 401:
                # Token expired, try next token
                if token == tokens_to_try[-1]:
                    return []  # All tokens failed
                continue
            elif response.status_code == 429:
                # Rate limited, wait and retry
                break
            
            try:
                response.raise_for_status()
                data = response.json()
                
                for features in data.get('audio_features', []):
                    if features and features.get('id'):
                        all_features.append({
                            'id': features['id'],
                            'energy': features.get('energy', 0.5),
                            'valence': features.get('valence', 0.5),
                            'tempo': features.get('tempo', 120),
                            'danceability': features.get('danceability', 0.5),
                            'acousticness': features.get('acousticness', 0.5),
                            'instrumentalness': features.get('instrumentalness', 0),
                            'speechiness': features.get('speechiness', 0),
                            'liveness': features.get('liveness', 0)
                        })
                success = True
                break  # Success, no need to try other tokens
            except (requests.HTTPError, ValueError) as e:
                # Try next token if available
                if token == tokens_to_try[-1]:
                    continue
                continue
        
        if not success:
            # Silently skip failed batches - audio features are optional
            pass
    
    return all_features


def get_recommendations_by_audio_features(access_token, seed_track_ids, limit=20):
    """
    Get recommendations by finding tracks with similar audio features.
    Alternative to the deprecated recommendations endpoint.
    
    Args:
        access_token: Valid Spotify access token
        seed_track_ids: List of track IDs to use as seeds (up to 5)
        limit: Number of recommendations to return
    
    Returns:
        list: List of recommended track dictionaries
    """
    if not seed_track_ids:
        return []
    
    # Get fallback token once for reuse
    fallback_token = None
    try:
        from flask import current_app
        if current_app:
            from app import get_app_access_token
            fallback_token = get_app_access_token()
    except:
        pass
    
    try:
        # Get audio features for seed tracks
        seed_features = get_track_audio_features(access_token, seed_track_ids[:5], fallback_token=fallback_token)
        if not seed_features:
            return []
        
        # Calculate average audio features
        feature_keys = ['danceability', 'energy', 'valence', 'tempo', 'acousticness', 'instrumentalness']
        avg_features = {}
        for key in feature_keys:
            values = [f.get(key, 0) for f in seed_features if f.get(key) is not None]
            if values:
                avg_features[key] = sum(values) / len(values)
        
        # Extract genres from seed tracks' artists
        seed_genres = []
        for track_id in seed_track_ids[:3]:
            try:
                url = f'https://api.spotify.com/v1/tracks/{track_id}'
                headers = {'Authorization': f'Bearer {access_token}'}
                response = requests.get(url, headers=headers, timeout=5)
                if response.status_code == 200:
                    track = response.json()
                    if track.get('artists'):
                        artist_id = track['artists'][0]['id']
                        artist_genres = get_artist_genres(access_token, artist_id)
                        seed_genres.extend(artist_genres[:2])
            except:
                continue
        
        seed_genres = list(set(seed_genres))[:3]
        
        # Search for tracks in similar genres
        all_tracks = []
        if seed_genres:
            for genre in seed_genres:
                if len(all_tracks) >= limit:
                    break
                try:
                    url = 'https://api.spotify.com/v1/search'
                    headers = {'Authorization': f'Bearer {access_token}'}
                    params = {
                        'q': f'genre:"{genre}" year:2020-2024',
                        'type': 'track',
                        'limit': min(20, limit),
                        'market': 'US'
                    }
                    response = requests.get(url, headers=headers, params=params, timeout=5)
                    if response.status_code == 200:
                        tracks = response.json().get('tracks', {}).get('items', [])
                        for track in tracks:
                            if len(all_tracks) >= limit:
                                break
                            # Exclude seed tracks
                            if track['id'] not in seed_track_ids:
                                normalized = normalize_track(track)
                                if normalized:
                                    all_tracks.append(normalized)
                except:
                    continue
        
        # Score tracks by audio feature similarity if we have features
        if all_tracks and avg_features:
            track_ids = [t['id'] for t in all_tracks[:50]]
            # Use same fallback token if available
            track_features = get_track_audio_features(access_token, track_ids, fallback_token=fallback_token)
            # Create a dict for quick lookup
            features_dict = {f['id']: f for f in track_features}
            
            # Score tracks
            scored_tracks = []
            for track in all_tracks:
                features = features_dict.get(track['id'])
                if not features:
                    continue
                score = 0
                for key in feature_keys:
                    if key in avg_features and key in features:
                        diff = abs(avg_features[key] - features[key])
                        score += 1 - diff  # Closer = higher score
                scored_tracks.append((score, track))
            
            # Sort by score and return top tracks
            scored_tracks.sort(key=lambda x: x[0], reverse=True)
            all_tracks = [t for _, t in scored_tracks[:limit]]
        
        return all_tracks[:limit]
        
    except Exception as e:
        print(f"Error getting recommendations by audio features: {str(e)}")
        return []


def search_tracks(access_token, query, limit=20):
    """
    Search for tracks on Spotify.
    
    Args:
        access_token: Valid Spotify access token
        query: Search query string
        limit: Number of results to return (max 50)
    
    Returns:
        list: List of track dictionaries matching the search
    """
    try:
        url = 'https://api.spotify.com/v1/search'
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {
            'q': query,
            'type': 'track',
            'limit': min(limit, 50)
        }
        
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        
        tracks = []
        for track in data.get('tracks', {}).get('items', []):
            normalized = normalize_track(track)
            if normalized:
                tracks.append(normalized)
        
        return tracks
        
    except requests.RequestException as e:
        print(f"Error searching tracks: {str(e)}")
        return []


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


def filter_tracks_by_artists(tracks, exclude_artist_ids):
    """
    Filter out tracks from excluded artists.
    
    Args:
        tracks: List of track dictionaries
        exclude_artist_ids: List of artist IDs to exclude
    
    Returns:
        list: Filtered tracks
    """
    if not exclude_artist_ids:
        return tracks
    
    exclude_set = set(exclude_artist_ids)
    filtered = []
    for track in tracks:
        track_artist_ids = [artist.get('id') for artist in track.get('artists', [])]
        if not any(aid in exclude_set for aid in track_artist_ids):
            filtered.append(track)
    return filtered


def get_recommendations_from_artists_and_genres(access_token, seed_artists=None, seed_genres=None, seed_tracks=None, limit=20):
    """
    Smart fallback: Get recommendations using genre-based search and artist genre extraction.
    Works with client credentials (no user auth needed).
    
    Args:
        access_token: Valid Spotify access token
        seed_artists: List of artist IDs
        seed_genres: List of genre names
        seed_tracks: List of track IDs
        limit: Number of recommendations to return
    
    Returns:
        list: List of track dictionaries from different artists in similar genres
    """
    try:
        all_tracks = []
        seed_artists = seed_artists or []
        seed_genres = seed_genres or []
        seed_tracks = seed_tracks or []
        
        # Step 1: Collect genres from all sources - prioritize track genres over artist genres
        genres_to_search = list(seed_genres)
        
        # Get genres from tracks first (more accurate than artist genres)
        if seed_tracks:
            for track_id in seed_tracks[:5]:
                track_genres = get_track_genres(access_token, track_id)
                genres_to_search.extend(track_genres[:2])
        
        # Also get genres from selected artists' top tracks (more accurate)
        if seed_artists:
            for artist_id in seed_artists[:3]:
                # Get top tracks from artist to extract genres from tracks
                try:
                    url = f'https://api.spotify.com/v1/artists/{artist_id}/top-tracks'
                    headers = {'Authorization': f'Bearer {access_token}'}
                    response = requests.get(url, headers=headers, params={'market': 'US'}, timeout=5)
                    if response.status_code == 200:
                        top_tracks = response.json().get('tracks', [])[:5]  # Get top 5 tracks
                        for track in top_tracks:
                            track_id = track.get('id')
                            if track_id:
                                track_genres = get_track_genres(access_token, track_id)
                                genres_to_search.extend(track_genres[:1])
                except Exception as e:
                    print(f"Error getting top tracks for genre extraction: {str(e)}")
                    # Fallback to artist genres
                    artist_genres = get_artist_genres(access_token, artist_id)
                    genres_to_search.extend(artist_genres[:2])
        
        # Remove duplicates and limit
        genres_to_search = list(set(genres_to_search))[:8]  # Get more genres for better variety
        print(f"Searching for tracks in genres: {genres_to_search}")
        
        # Step 2: Get tracks from genres (excludes seed artists)
        if genres_to_search:
            tracks_from_genres = get_tracks_by_genres(access_token, genres_to_search, limit, exclude_artist_ids=seed_artists)
            all_tracks.extend(tracks_from_genres)
            print(f"Got {len(tracks_from_genres)} tracks from genres")
        
        # Step 3: If genres found, try to get more from similar genres
        if len(all_tracks) < limit and seed_artists and genres_to_search:
            additional_tracks = get_popular_tracks_by_artist_genres(access_token, seed_artists, limit - len(all_tracks))
            all_tracks.extend(additional_tracks)
            print(f"Got {len(additional_tracks)} additional tracks from similar genres")
        
        # Step 4: Get tracks from related artists (this is the main recommendation source)
        if len(all_tracks) < limit and seed_artists:
            all_tracks = _get_tracks_from_related_artists(access_token, seed_artists, all_tracks, limit)
        
        # Step 5: Use audio features similarity if we have seed tracks
        if len(all_tracks) < limit and seed_tracks:
            all_tracks = _get_tracks_by_audio_features(access_token, seed_tracks, seed_artists, all_tracks, limit)
        
        # Step 6: If still not enough, get more tracks from genres with better search
        if len(all_tracks) < limit and genres_to_search:
            all_tracks = _get_more_tracks_from_genres(access_token, genres_to_search, seed_artists, all_tracks, limit)
        
        # Step 7: Final fallback - search for popular tracks in genres
        if len(all_tracks) < limit // 2:
            all_tracks = _get_tracks_from_genre_and_search(access_token, seed_artists, genres_to_search, all_tracks, limit)
        
        # CRITICAL: Filter out ALL tracks from selected artists - we want recommendations, not their own tracks
        if seed_artists:
            original_count = len(all_tracks)
            all_tracks = filter_tracks_by_artists(all_tracks, seed_artists)
            if len(all_tracks) < original_count:
                print(f"Filtered out {original_count - len(all_tracks)} tracks from selected artists (keeping only recommendations)")
        
        # Remove duplicates, shuffle, and return
        unique_tracks = _deduplicate_tracks(all_tracks)
        import random
        random.shuffle(unique_tracks)
        print(f"Returning {len(unique_tracks)} recommendations (excluding selected artists)")
        return unique_tracks[:limit]
        
    except Exception as e:
        print(f"Error getting smart recommendations: {str(e)}")
        import traceback
        traceback.print_exc()
        return []


def _get_tracks_from_related_artists(access_token, seed_artists, existing_tracks, limit):
    """Helper: Get tracks from related artists, with improved fallback."""
    print(f"Not enough tracks from genres ({len(existing_tracks)}/{limit}), trying related artists")
    related_artists_list = []
    
    for artist_id in seed_artists[:3]:
        related = get_related_artists(access_token, artist_id)
        if related:
            related_artists_list.extend(related[:8])  # Get more related artists for variety
    
    # Remove duplicates and seed artists
    seen_ids = set(seed_artists)
    unique_related = []
    for artist in related_artists_list:
        if artist.get('id') and artist['id'] not in seen_ids:
            unique_related.append(artist)
            seen_ids.add(artist['id'])
    print(f"Found {len(unique_related)} unique related artists")
    
    # Get top tracks from related artists
    if unique_related:
        related_ids = [a['id'] for a in unique_related[:10] if a.get('id')]
        if related_ids:
            tracks_per_artist = max(3, (limit - len(existing_tracks)) // len(related_ids) + 1)
            
            for related_id in related_ids:
                if len(existing_tracks) >= limit:
                    break
                try:
                    url = f'https://api.spotify.com/v1/artists/{related_id}/top-tracks'
                    headers = {'Authorization': f'Bearer {access_token}'}
                    response = requests.get(url, headers=headers, params={'market': 'US'}, timeout=5)
                    if response.status_code == 200:
                        tracks = [t for t in [normalize_track(t) for t in response.json().get('tracks', [])[:tracks_per_artist]] if t]
                        filtered = filter_tracks_by_artists(tracks, seed_artists)
                        existing_tracks.extend(filtered)
                except Exception as e:
                    print(f"Error getting tracks from related artist {related_id}: {str(e)}")
            
            print(f"Added {len(existing_tracks)} tracks from related artists")
    else:
        # If no related artists found, we'll rely on other methods (similar artists search, genre search)
        print("No related artists found via API - will try other recommendation methods")
    
    return existing_tracks


def _get_tracks_by_audio_features(access_token, seed_tracks, seed_artists, existing_tracks, limit):
    """Helper: Get tracks similar by audio features."""
    print(f"Finding tracks with similar audio features")
    
    try:
        # Get audio features for seed tracks
        fallback_token = None
        try:
            from flask import current_app
            if current_app:
                from app import get_app_access_token
                fallback_token = get_app_access_token()
        except:
            pass
        
        seed_features_list = get_track_audio_features(access_token, seed_tracks[:5], fallback_token=fallback_token)
        if not seed_features_list:
            return existing_tracks
        
        # Calculate average audio features
        feature_keys = ['danceability', 'energy', 'valence', 'tempo', 'acousticness', 'instrumentalness']
        avg_features = {}
        for key in feature_keys:
            values = [f.get(key, 0) for f in seed_features_list if f.get(key) is not None]
            if values:
                avg_features[key] = sum(values) / len(values)
        
        if not avg_features:
            return existing_tracks
        
        # Search for tracks in similar genres and filter by audio features
        # Get genres from seed tracks
        seed_genres = []
        for track_id in seed_tracks[:3]:
            track_genres = get_track_genres(access_token, track_id)
            seed_genres.extend(track_genres[:2])
        seed_genres = list(set(seed_genres))[:3]
        
        if seed_genres:
            url = 'https://api.spotify.com/v1/search'
            headers = {'Authorization': f'Bearer {access_token}'}
            seen_track_ids = {t.get('id') for t in existing_tracks}
            
            for genre in seed_genres:
                if len(existing_tracks) >= limit:
                    break
                try:
                    # Search for tracks in this genre
                    params = {
                        'q': f'genre:"{genre}" year:2020-2024',
                        'type': 'track',
                        'limit': 50,
                        'market': 'US'
                    }
                    response = requests.get(url, headers=headers, params=params, timeout=5)
                    if response.status_code == 200:
                        tracks = [t for t in [normalize_track(t) for t in response.json().get('tracks', {}).get('items', [])] if t]
                        # Filter out seed artists
                        filtered_tracks = [t for t in filter_tracks_by_artists(tracks, seed_artists) 
                                         if t and t.get('id') and t.get('id') not in seen_track_ids]
                        
                        # Get audio features for these tracks and score by similarity
                        track_ids = [t['id'] for t in filtered_tracks[:30]]
                        if track_ids:
                            track_features_list = get_track_audio_features(access_token, track_ids, fallback_token=fallback_token)
                            features_dict = {f['id']: f for f in track_features_list}
                            
                            # Score tracks by audio feature similarity
                            scored_tracks = []
                            for track in filtered_tracks:
                                track_id = track.get('id')
                                if track_id in features_dict:
                                    features = features_dict[track_id]
                                    score = 0
                                    for key in feature_keys:
                                        if key in avg_features and key in features:
                                            diff = abs(avg_features[key] - features[key])
                                            score += 1 - diff  # Closer = higher score
                                    scored_tracks.append((score, track))
                            
                            # Sort by score and add top tracks
                            scored_tracks.sort(key=lambda x: x[0], reverse=True)
                            for score, track in scored_tracks[:10]:
                                if len(existing_tracks) >= limit:
                                    break
                                if track.get('id') not in seen_track_ids:
                                    existing_tracks.append(track)
                                    seen_track_ids.add(track.get('id'))
                except Exception as e:
                    print(f"Error getting tracks by audio features for genre {genre}: {str(e)}")
        
        print(f"Added {len(existing_tracks)} tracks based on audio features")
    except Exception as e:
        print(f"Error in audio features recommendation: {str(e)}")
    
    return existing_tracks


def _get_more_tracks_from_genres(access_token, genres, seed_artists, existing_tracks, limit):
    """Helper: Get more tracks from genres with better search strategies."""
    print(f"Getting more tracks from genres: {genres}")
    
    url = 'https://api.spotify.com/v1/search'
    headers = {'Authorization': f'Bearer {access_token}'}
    seen_track_ids = {t.get('id') for t in existing_tracks}
    
    # Try different search strategies for each genre
    for genre in genres:
        if len(existing_tracks) >= limit:
            break
        try:
            # Strategy 1: Search by genre with year filter
            queries = [
                f'genre:"{genre}" year:2020-2024',
                f'genre:"{genre}" tag:new',
                f'genre:"{genre}"'
            ]
            
            for query in queries:
                if len(existing_tracks) >= limit:
                    break
                try:
                    params = {
                        'q': query,
                        'type': 'track',
                        'limit': min(30, limit - len(existing_tracks) + 10),
                        'market': 'US'
                    }
                    response = requests.get(url, headers=headers, params=params, timeout=5)
                    if response.status_code == 200:
                        tracks = [t for t in [normalize_track(t) for t in response.json().get('tracks', {}).get('items', [])] if t]
                        filtered = [t for t in filter_tracks_by_artists(tracks, seed_artists) 
                                   if t and t.get('id') and t.get('id') not in seen_track_ids]
                        existing_tracks.extend(filtered)
                        seen_track_ids.update(t.get('id') for t in filtered)
                except:
                    pass
        except Exception as e:
            print(f"Error searching genre {genre}: {str(e)}")
    
    print(f"Added {len(existing_tracks)} more tracks from genres")
    return existing_tracks


def _get_tracks_from_genre_and_search(access_token, seed_artists, seed_genres, existing_tracks, limit):
    """Helper: Final fallback - search by genres and popular tracks, excluding seed artists."""
    print(f"Final fallback: searching by genres and popular tracks")
    
    url = 'https://api.spotify.com/v1/search'
    headers = {'Authorization': f'Bearer {access_token}'}
    seen_track_ids = {t.get('id') for t in existing_tracks}
    
    # Try to search by genres if we have any
    if seed_genres:
        for genre in seed_genres[:3]:
            if len(existing_tracks) >= limit:
                break
            try:
                params = {
                    'q': f'genre:"{genre}" year:2020-2024',
                    'type': 'track',
                    'limit': min(30, limit - len(existing_tracks) + 10),
                    'market': 'US'
                }
                response = requests.get(url, headers=headers, params=params, timeout=5)
                if response.status_code == 200:
                    tracks = [t for t in [normalize_track(t) for t in response.json().get('tracks', {}).get('items', [])] if t]
                    # Filter out seed artists and duplicates
                    filtered = [t for t in filter_tracks_by_artists(tracks, seed_artists) 
                               if t and t.get('id') and t.get('id') not in seen_track_ids]
                    existing_tracks.extend(filtered)
                    seen_track_ids.update(t.get('id') for t in filtered)
            except Exception as e:
                print(f"Error searching by genre {genre}: {str(e)}")
    
    # Last resort: popular tracks (but still filter out seed artists)
    if len(existing_tracks) < limit // 2:
        popular_queries = ['tag:new year:2023-2024', 'tag:hipster year:2023-2024']
        for query in popular_queries:
            if len(existing_tracks) >= limit:
                break
            try:
                params = {'q': query, 'type': 'track', 'limit': min(30, limit - len(existing_tracks) + 10), 'market': 'US'}
                response = requests.get(url, headers=headers, params=params, timeout=5)
                if response.status_code == 200:
                    tracks = [t for t in [normalize_track(t) for t in response.json().get('tracks', {}).get('items', [])] if t]
                    filtered = [t for t in filter_tracks_by_artists(tracks, seed_artists) 
                               if t and t.get('id') and t.get('id') not in seen_track_ids]
                    existing_tracks.extend(filtered)
                    seen_track_ids.update(t.get('id') for t in filtered)
            except Exception as e:
                print(f"Error searching popular tracks: {str(e)}")
    
    print(f"Added {len(existing_tracks)} total tracks from genre/search fallback")
    return existing_tracks



def _deduplicate_tracks(tracks):
    """Helper: Remove duplicate tracks by ID."""
    seen_ids = set()
    unique = []
    for track in tracks:
        track_id = track.get('id')
        if track_id and track_id not in seen_ids:
            seen_ids.add(track_id)
            unique.append(track)
    return unique


def get_artist_genres(access_token, artist_id):
    """
    Get genres for an artist.
    
    Args:
        access_token: Valid Spotify access token
        artist_id: Artist ID
    
    Returns:
        list: List of genre strings
    """
    try:
        url = f'https://api.spotify.com/v1/artists/{artist_id}'
        headers = {'Authorization': f'Bearer {access_token}'}
        
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
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
                        search_response = requests.get(search_url, headers=headers, params=search_params, timeout=5)
                        if search_response.status_code == 200:
                            search_data = search_response.json()
                            search_artists = search_data.get('artists', {}).get('items', [])
                            if search_artists and search_artists[0].get('genres'):
                                genres = search_artists[0].get('genres', [])
                                print(f"Found genres via search for {artist_name}: {genres[:3]}")
                    except:
                        pass
            return genres
        elif response.status_code == 404:
            print(f"Artist {artist_id} not found (404) - may be invalid ID")
            return []
        else:
            print(f"Failed to get artist info for {artist_id}: Status {response.status_code}, Response: {response.text[:100]}")
            return []
    except Exception as e:
        print(f"Error getting artist genres for {artist_id}: {str(e)}")
        import traceback
        traceback.print_exc()
        return []


def get_track_genres(access_token, track_id):
    """
    Get genres from a track's artist.
    
    Args:
        access_token: Valid Spotify access token
        track_id: Track ID
    
    Returns:
        list: List of genre strings
    """
    try:
        # Get track info
        url = f'https://api.spotify.com/v1/tracks/{track_id}'
        headers = {'Authorization': f'Bearer {access_token}'}
        
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            track = response.json()
            # Get genres from first artist
            if track.get('artists'):
                artist_id = track['artists'][0]['id']
                return get_artist_genres(access_token, artist_id)
        return []
    except Exception as e:
        print(f"Error getting track genres: {str(e)}")
        return []


def get_popular_tracks_by_artist_genres(access_token, artist_ids, limit=10):
    """
    Get popular tracks from other artists in the same genres as seed artists.
    
    Args:
        access_token: Valid Spotify access token
        artist_ids: List of artist IDs
        limit: Number of tracks to return
    
    Returns:
        list: List of track dictionaries
    """
    try:
        all_tracks = []
        
        # Get genres from seed artists
        all_genres = []
        for artist_id in artist_ids[:3]:
            genres = get_artist_genres(access_token, artist_id)
            all_genres.extend(genres[:2])
        
        unique_genres = list(set(all_genres))[:3]
        
        # Search for popular tracks in these genres
        for genre in unique_genres:
            url = 'https://api.spotify.com/v1/search'
            headers = {'Authorization': f'Bearer {access_token}'}
            params = {
                'q': f'genre:"{genre}"',
                'type': 'track',
                'limit': min(10, limit // len(unique_genres) + 1),
                'market': 'US'
            }
            
            response = requests.get(url, headers=headers, params=params)
            if response.status_code == 200:
                data = response.json()
                tracks = data.get('tracks', {}).get('items', [])
                
                # Filter out tracks from seed artists
                for track in tracks:
                    track_artist_ids = [artist['id'] for artist in track.get('artists', [])]
                    # Only include if NOT from seed artists
                    if not any(aid in artist_ids for aid in track_artist_ids):
                        # Normalize to standard Spotify API format
                        all_tracks.append({
                            'id': track['id'],
                            'name': track['name'],
                            'artists': track['artists'],  # Keep as array for consistency
                            'album': track['album'],  # Keep as object for consistency
                            'preview_url': track.get('preview_url'),
                            'external_urls': track.get('external_urls', {}),
                            'popularity': track.get('popularity', 0)
                        })
        
        # Sort by popularity and limit
        all_tracks.sort(key=lambda x: x['popularity'], reverse=True)
        return all_tracks[:limit]
        
    except Exception as e:
        print(f"Error getting popular tracks by genres: {str(e)}")
        return []


def get_tracks_by_genres(access_token, genres, limit=10, exclude_artist_ids=None):
    """
    Get popular tracks by searching for tracks in specific genres.
    Excludes tracks from specified artists to ensure recommendations are from different artists.
    
    Args:
        access_token: Valid Spotify access token
        genres: List of genre names
        limit: Number of tracks to return
        exclude_artist_ids: List of artist IDs to exclude (optional)
    
    Returns:
        list: List of track dictionaries from different artists
    """
    try:
        all_tracks = []
        exclude_set = set(exclude_artist_ids) if exclude_artist_ids else set()
        tracks_per_genre = max(10, limit // len(genres) + 5) if genres else 10
        
        for genre in genres[:5]:  # Limit to 5 genres
            # Search for tracks with genre in query
            url = 'https://api.spotify.com/v1/search'
            headers = {'Authorization': f'Bearer {access_token}'}
            params = {
                'q': f'genre:"{genre}"',
                'type': 'track',
                'limit': min(tracks_per_genre, 50),  # Get more to filter
                'market': 'US'
            }
            
            response = requests.get(url, headers=headers, params=params)
            if response.status_code == 200:
                data = response.json()
                tracks = data.get('tracks', {}).get('items', [])
                
                for track in tracks:
                    # Get artist IDs for this track
                    track_artist_ids = [artist['id'] for artist in track.get('artists', [])]
                    
                    # Only include if NOT from excluded artists (seed artists)
                    if not any(aid in exclude_set for aid in track_artist_ids):
                        # Normalize to standard Spotify API format
                        all_tracks.append({
                            'id': track['id'],
                            'name': track['name'],
                            'artists': track['artists'],  # Keep as array for consistency
                            'album': track['album'],  # Keep as object for consistency
                            'preview_url': track.get('preview_url'),
                            'external_urls': track.get('external_urls', {}),
                            'popularity': track.get('popularity', 0)
                        })
                
                # Count tracks added (for debugging)
                added_count = len([t for t in all_tracks if not any(aid in exclude_set for aid in [a['id'] for a in t.get('artists', [])])])
                print(f"Added {added_count} tracks from genre '{genre}' (excluding seed artists)")
        
        # Sort by popularity (most popular first) and limit
        all_tracks.sort(key=lambda x: x['popularity'], reverse=True)
        
        # Shuffle top results for variety
        import random
        if len(all_tracks) > limit:
            top_tracks = all_tracks[:limit * 2]  # Take top 2x limit
            random.shuffle(top_tracks)
            return top_tracks[:limit]
        
        random.shuffle(all_tracks)
        return all_tracks
        
    except Exception as e:
        print(f"Error getting tracks by genres: {str(e)}")
        return []


def get_track_artists(access_token, track_id):
    """
    Get artist IDs from a track.
    
    Args:
        access_token: Valid Spotify access token
        track_id: Track ID
    
    Returns:
        list: List of artist IDs
    """
    try:
        url = f'https://api.spotify.com/v1/tracks/{track_id}'
        headers = {'Authorization': f'Bearer {access_token}'}
        
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
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
    
    Args:
        access_token: Valid Spotify access token
        artist_ids: List of artist IDs
        limit: Total number of tracks to return
    
    Returns:
        list: List of track dictionaries
    """
    try:
        all_tracks = []
        tracks_per_artist = max(5, limit // len(artist_ids)) if artist_ids else 10
        
        for artist_id in artist_ids[:5]:  # Limit to 5 artists
            url = f'https://api.spotify.com/v1/artists/{artist_id}/top-tracks'
            headers = {'Authorization': f'Bearer {access_token}'}
            params = {'market': 'US'}
            
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                tracks = data.get('tracks', [])
                
                for track in tracks[:tracks_per_artist]:
                    normalized = normalize_track(track)
                    if normalized:
                        all_tracks.append(normalized)
            else:
                print(f"Failed to get top tracks for artist {artist_id}: {response.status_code}")
        
        # Shuffle and limit
        import random
        random.shuffle(all_tracks)
        return all_tracks[:limit]
        
    except Exception as e:
        print(f"Error getting artist top tracks: {str(e)}")
        return []


def get_related_artists(access_token, artist_id):
    """
    Get related artists for an artist.
    
    Args:
        access_token: Valid Spotify access token
        artist_id: Artist ID
    
    Returns:
        list: List of related artist dictionaries
    """
    try:
        url = f'https://api.spotify.com/v1/artists/{artist_id}/related-artists'
        headers = {'Authorization': f'Bearer {access_token}'}
        
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code == 404:
            # Silently return empty list for 404 (endpoint deprecated)
            return []
        
        response.raise_for_status()
        data = response.json()
        
        related = []
        for artist in data.get('artists', [])[:10]:
            related.append({
                'id': artist['id'],
                'name': artist['name'],
                'genres': artist.get('genres', []),
                'image_url': artist['images'][0]['url'] if artist.get('images') else None,
                'spotify_url': artist['external_urls']['spotify'],
                'popularity': artist.get('popularity', 0)
            })
        
        return related
        
    except requests.RequestException as e:
        print(f"Error getting related artists: {str(e)}")
        return []


def find_similar_artists_by_search(access_token, artist_name, limit=10):
    """
    Find similar artists using search API when related artists endpoint is not available.
    Uses search with artist name and common genre terms.
    
    Args:
        access_token: Valid Spotify access token
        artist_name: Name of the artist to find similar artists for
        limit: Number of similar artists to return
    
    Returns:
        list: List of artist dictionaries
    """
    try:
        # Search for artists with similar names or in similar genres
        url = 'https://api.spotify.com/v1/search'
        headers = {'Authorization': f'Bearer {access_token}'}
        
        # Try searching for the artist first to get their info
        params = {
            'q': f'artist:"{artist_name}"',
            'type': 'artist',
            'limit': 1
        }
        
        response = requests.get(url, headers=headers, params=params, timeout=5)
        if response.status_code == 200:
            data = response.json()
            artists = data.get('artists', {}).get('items', [])
            if artists:
                # Get the artist's genres
                artist_genres = artists[0].get('genres', [])
                if artist_genres:
                    # Search for other artists in the same genres
                    genre_query = ' OR '.join([f'genre:"{g}"' for g in artist_genres[:2]])
                    params = {
                        'q': genre_query,
                        'type': 'artist',
                        'limit': limit + 5  # Get more to filter
                    }
                    
                    response = requests.get(url, headers=headers, params=params, timeout=5)
                    if response.status_code == 200:
                        data = response.json()
                        similar_artists = []
                        original_name_lower = artist_name.lower()
                        
                        for artist in data.get('artists', {}).get('items', []):
                            # Exclude the original artist
                            if artist['name'].lower() != original_name_lower:
                                similar_artists.append({
                                    'id': artist['id'],
                                    'name': artist['name'],
                                    'genres': artist.get('genres', []),
                                    'image_url': artist['images'][0]['url'] if artist.get('images') else None,
                                    'spotify_url': artist['external_urls']['spotify'],
                                    'popularity': artist.get('popularity', 0)
                                })
                                if len(similar_artists) >= limit:
                                    break
                        
                        return similar_artists
        
        return []
        
    except Exception as e:
        print(f"Error finding similar artists by search: {str(e)}")
        return []


def get_available_genre_seeds(access_token):
    """
    Get list of available genre seeds for recommendations.
    
    Note: This endpoint was deprecated by Spotify in November 2024.
    This function now immediately returns empty list and relies on fallback genres.
    
    Args:
        access_token: Valid Spotify access token (not used, kept for compatibility)
    
    Returns:
        list: Always returns empty list (endpoint deprecated)
    """
    # Endpoint deprecated - don't even try
    print("⚠️  Genre seeds endpoint deprecated (Nov 2024)")
    print("   Using comprehensive fallback genre list (126+ genres) instead.")
    return []


def add_track_to_spotify_library(access_token, track_id):
    """
    Add a track to the user's Spotify library (liked songs).
    
    Args:
        access_token: Valid Spotify access token with user-library-modify scope
        track_id: Spotify track ID to add
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        url = 'https://api.spotify.com/v1/me/tracks'
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        data = {'ids': [track_id]}
        
        response = requests.put(url, headers=headers, json=data)
        response.raise_for_status()
        return True
        
    except requests.RequestException as e:
        print(f"Error adding track to Spotify library: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response status: {e.response.status_code}")
            print(f"Response body: {e.response.text}")
        return False


def get_artist_info(access_token, artist_id):
    """
    Get artist information by ID.
    
    Args:
        access_token: Valid Spotify access token
        artist_id: Spotify artist ID
    
    Returns:
        dict: Artist information including name, or None if failed
    """
    try:
        url = f'https://api.spotify.com/v1/artists/{artist_id}'
        headers = {'Authorization': f'Bearer {access_token}'}
        
        response = requests.get(url, headers=headers, timeout=2)
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        print(f"Error getting artist info: {str(e)}")
        return None

