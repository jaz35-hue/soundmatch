"""
Main Recommendation Engine
Orchestrates recommendations using multiple APIs with clear responsibilities:
- Last.fm: Primary recommendation engine (similar artists, tracks, genres)
- Spotify: Metadata provider (track details, search, artist info)
- YouTube: Optional video discovery (can be disabled)
"""

from typing import List, Dict, Optional
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# Import API modules
from spotify_api import (
    get_artist_info,
    normalize_track,
    search_tracks,
    get_artist_genres
)
from lastfm_api import (
    get_similar_artists,
    get_similar_tracks,
    get_artist_top_tracks as get_lastfm_top_tracks,
    get_artist_tags,
    get_tag_top_artists
)
from youtube_api import (
    search_track_on_youtube,
    get_related_videos,
    rank_videos_by_popularity
)


class RecommendationEngine:
    """
    Main recommendation engine that coordinates between APIs.
    """
    
    def __init__(self, spotify_token: str, use_youtube: bool = False):
        """
        Initialize the recommendation engine.
        
        Args:
            spotify_token: Valid Spotify access token
            use_youtube: Whether to include YouTube recommendations (default: False)
        """
        self.spotify_token = spotify_token
        self.use_youtube = use_youtube
    
    def get_recommendations(
        self,
        seed_artists: Optional[List[str]] = None,
        seed_tracks: Optional[List[str]] = None,
        limit: int = 20,
        exclude_track_ids: Optional[List[str]] = None,
        expand_search: bool = False
    ) -> Dict:
        """
        Get recommendations using a multi-API approach.
        
        Args:
            seed_artists: List of Spotify artist IDs
            seed_tracks: List of Spotify track IDs
            limit: Number of recommendations to return
        
        Returns:
            dict: {
                'tracks': List of recommended tracks (Spotify format),
                'seed_videos': List of YouTube videos for seed tracks (if use_youtube),
                'youtube_videos': List of YouTube recommendations (if use_youtube),
                'sources': Dict showing which APIs were used
            }
        """
        seed_artists = seed_artists or []
        seed_tracks = seed_tracks or []
        exclude_track_ids = exclude_track_ids or []
        exclude_set = set(exclude_track_ids)
        
        # If regenerating (exclude_track_ids provided), expand search to find more diverse tracks
        if exclude_track_ids:
            expand_search = True
            # Increase limit to get more candidates, then filter
            search_limit = limit * 3  # Get 3x more to have options after filtering
        else:
            search_limit = limit
        
        result = {
            'tracks': [],
            'seed_videos': [],
            'youtube_videos': [],
            'sources': {
                'lastfm': False,
                'spotify': False,
                'youtube': False
            }
        }
        
        try:
            # Step 1: Get recommendations from Last.fm (primary engine)
            lastfm_tracks = self._get_lastfm_recommendations(
                seed_artists, 
                seed_tracks, 
                search_limit,
                expand_search=expand_search
            )
            # Filter out excluded tracks
            lastfm_tracks = [t for t in lastfm_tracks if t.get('id') not in exclude_set]
            result['tracks'] = lastfm_tracks
            result['sources']['lastfm'] = len(lastfm_tracks) > 0
            
            # Step 2: If not enough, use genre-based recommendations (more diverse)
            if len(result['tracks']) < limit:
                genre_tracks = self._get_genre_based_recommendations(
                    seed_artists, 
                    search_limit - len(result['tracks']),
                    expand_search=expand_search
                )
                # Filter excluded and merge
                existing_ids = {t.get('id') for t in result['tracks']}
                for track in genre_tracks:
                    track_id = track.get('id')
                    if track_id and track_id not in existing_ids and track_id not in exclude_set:
                        result['tracks'].append(track)
                        existing_ids.add(track_id)
            
            # Step 3: If still not enough, use Spotify search as fallback
            if len(result['tracks']) < limit:
                spotify_tracks = self._get_spotify_fallback_recommendations(
                    seed_artists, 
                    search_limit - len(result['tracks']),
                    expand_search=expand_search
                )
                # Merge without duplicates
                existing_ids = {t.get('id') for t in result['tracks']}
                for track in spotify_tracks:
                    track_id = track.get('id')
                    if track_id and track_id not in existing_ids and track_id not in exclude_set:
                        result['tracks'].append(track)
                        existing_ids.add(track_id)
                result['sources']['spotify'] = len(spotify_tracks) > 0
            
            # Step 3: Optionally get YouTube videos
            if self.use_youtube:
                youtube_data = self._get_youtube_recommendations(seed_artists, seed_tracks, limit)
                result['seed_videos'] = youtube_data.get('seed_videos', [])
                result['youtube_videos'] = youtube_data.get('recommendations', [])
                result['sources']['youtube'] = True
            
            # Limit to requested amount
            result['tracks'] = result['tracks'][:limit]
            
            print(f"✅ Recommendations: {len(result['tracks'])} tracks "
                  f"(Last.fm: {result['sources']['lastfm']}, "
                  f"Spotify: {result['sources']['spotify']}, "
                  f"YouTube: {result['sources']['youtube']})")
            
        except Exception as e:
            print(f"Error in recommendation engine: {str(e)}")
            import traceback
            traceback.print_exc()
        
        return result
    
    def _get_lastfm_recommendations(
        self,
        seed_artists: List[str],
        seed_tracks: List[str],
        limit: int,
        expand_search: bool = False
    ) -> List[Dict]:
        """
        Get recommendations from Last.fm (primary recommendation engine).
        
        Strategy:
        1. Get similar artists from Last.fm
        2. Get top tracks from similar artists
        3. Search Spotify for those tracks to get metadata
        4. Also use similar tracks if seed tracks provided
        """
        recommendations = []
        seen_track_ids = set()
        
        # Get artist names from Spotify (parallel)
        artist_names = []
        def get_artist_name(artist_id):
            try:
                artist_info = get_artist_info(self.spotify_token, artist_id)
                return artist_info.get('name', '') if artist_info else ''
            except Exception as e:
                print(f"Error getting artist info for {artist_id}: {str(e)}")
                return ''
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(get_artist_name, aid): aid for aid in seed_artists[:3]}
            for future in as_completed(futures):
                name = future.result()
                if name:
                    artist_names.append(name)
        
        # Strategy 1: Similar artists from Last.fm (parallel)
        def process_artist(artist_name):
            """Process one artist and return recommendations"""
            artist_recommendations = []
            try:
                # Get similar artists from Last.fm
                similar_limit = 20 if expand_search else 10
                similar_artists = get_similar_artists(artist_name, limit=similar_limit)
                
                if not similar_artists:
                    return artist_recommendations
                
                # Sort by match score (highest first)
                similar_artists.sort(key=lambda x: x.get('match', 0), reverse=True)
                
                # If expanding, use more artists and go deeper in the list
                if expand_search:
                    artists_to_use = similar_artists[:15]
                    tracks_per_artist = 8
                else:
                    artists_to_use = similar_artists[:8]
                    tracks_per_artist = 5
                
                # Get tracks from similar artists (parallel)
                def get_tracks_from_similar(similar):
                    similar_name = similar.get('name', '')
                    match_score = similar.get('match', 0)
                    
                    if similar_name.lower() == artist_name.lower():
                        return []
                    
                    try:
                        lastfm_tracks = get_lastfm_top_tracks(similar_name, limit=tracks_per_artist)
                        tracks = []
                        for track_info in lastfm_tracks:
                            track_name = track_info.get('name', '')
                            if not track_name:
                                continue
                            
                            # Search Spotify for this track
                            spotify_tracks = search_tracks(
                                self.spotify_token,
                                f"{track_name} {similar_name}",
                                limit=2  # Reduced from 3 for speed
                            )
                            
                            for track in spotify_tracks:
                                track_id = track.get('id')
                                if not track_id:
                                    continue
                                
                                # Filter out tracks from seed artists
                                track_artist_ids = []
                                if 'artists' in track and isinstance(track.get('artists'), list):
                                    track_artist_ids = [a.get('id') for a in track['artists'] 
                                                      if isinstance(a, dict) and a.get('id')]
                                
                                if not any(aid in seed_artists for aid in track_artist_ids):
                                    # If track doesn't have preview_url, try to fetch it
                                    if not track.get('preview_url') and track_id:
                                        try:
                                            url = f'https://api.spotify.com/v1/tracks/{track_id}'
                                            headers = {'Authorization': f'Bearer {self.spotify_token}'}
                                            response = requests.get(url, headers=headers, timeout=3)
                                            if response.status_code == 200:
                                                track_data = response.json()
                                                preview_url = track_data.get('preview_url')
                                                if preview_url:
                                                    track['preview_url'] = preview_url
                                        except:
                                            pass  # Continue even if fetch fails
                                    
                                    track['lastfm_match'] = match_score
                                    tracks.append(track)
                                    break  # Only add first match
                        
                        return tracks
                    except Exception as e:
                        print(f"Error getting tracks for {similar_name}: {str(e)}")
                        return []
                
                # Process similar artists in parallel (but limit concurrency)
                with ThreadPoolExecutor(max_workers=5) as executor:
                    futures = {executor.submit(get_tracks_from_similar, similar): similar 
                              for similar in artists_to_use}
                    for future in as_completed(futures):
                        tracks = future.result()
                        artist_recommendations.extend(tracks)
                
            except Exception as e:
                print(f"Error getting Last.fm recommendations for {artist_name}: {str(e)}")
            
            return artist_recommendations
        
        # Process all artists in parallel
        with ThreadPoolExecutor(max_workers=min(len(artist_names), 3)) as executor:
            futures = {executor.submit(process_artist, name): name for name in artist_names}
            for future in as_completed(futures):
                artist_recs = future.result()
                for track in artist_recs:
                    track_id = track.get('id')
                    if track_id and track_id not in seen_track_ids:
                        seen_track_ids.add(track_id)
                        recommendations.append(track)
                        if len(recommendations) >= limit:
                            break
                if len(recommendations) >= limit:
                    break
        
        print(f"Last.fm found {len(recommendations)} recommendations from similar artists")
        
        # Strategy 2: Similar tracks from Last.fm (if seed tracks provided)
        # If expanding, use more seed tracks
        max_seed_tracks = 5 if expand_search else 3
        if seed_tracks and len(recommendations) < limit:
            for track_id in seed_tracks[:max_seed_tracks]:
                if len(recommendations) >= limit:
                    break
                
                try:
                    # Get track info from Spotify
                    url = f'https://api.spotify.com/v1/tracks/{track_id}'
                    headers = {'Authorization': f'Bearer {self.spotify_token}'}
                    response = requests.get(url, headers=headers, timeout=5)
                    
                    if response.status_code == 200:
                        track_data = response.json()
                        track_name = track_data.get('name', '')
                        artist_name = track_data.get('artists', [{}])[0].get('name', '') if track_data.get('artists') else ''
                        
                        if track_name and artist_name:
                            # Get similar tracks from Last.fm
                            # If expanding, get more similar tracks
                            similar_limit = 15 if expand_search else 10
                            similar_tracks = get_similar_tracks(track_name, artist_name, limit=similar_limit)
                            
                            # Use more tracks if expanding
                            tracks_to_use = similar_tracks[:10] if expand_search else similar_tracks[:5]
                            for similar in tracks_to_use:
                                if len(recommendations) >= limit:
                                    break
                                
                                similar_track_name = similar.get('name', '')
                                similar_artist_name = similar.get('artist', '')
                                
                                if not similar_track_name or not similar_artist_name:
                                    continue
                                
                                # Search Spotify
                                spotify_tracks = search_tracks(
                                    self.spotify_token,
                                    f"{similar_track_name} {similar_artist_name}",
                                    limit=3
                                )
                                
                                for track in spotify_tracks:
                                    track_id = track.get('id')
                                    if track_id and track_id not in seen_track_ids:
                                        seen_track_ids.add(track_id)
                                        track['lastfm_match'] = similar.get('match', 0)
                                        recommendations.append(track)
                                        break
                
                except Exception as e:
                    print(f"Error getting similar tracks for {track_id}: {str(e)}")
        
        # Strategy 3: Genre-based recommendations from Last.fm
        # Always use genre-based if expanding search or if not enough tracks
        if (expand_search or len(recommendations) < limit) and artist_names:
            genre_limit = (limit - len(recommendations)) * 2 if expand_search else (limit - len(recommendations))
            genre_tracks = self._get_genre_based_recommendations(
                artist_names, 
                seed_artists, 
                genre_limit,
                expand_search=expand_search
            )
            for track in genre_tracks:
                track_id = track.get('id')
                if track_id and track_id not in seen_track_ids:
                    seen_track_ids.add(track_id)
                    recommendations.append(track)
        
        # Sort by Last.fm match score if available
        recommendations.sort(key=lambda x: x.get('lastfm_match', 0), reverse=True)
        
        return recommendations[:limit]
    
    def _get_genre_based_recommendations(
        self,
        artist_names: List[str],
        seed_artists: List[str],
        limit: int,
        expand_search: bool = False
    ) -> List[Dict]:
        """
        Get genre-based recommendations using Last.fm tags.
        """
        recommendations = []
        seen_track_ids = set()
        
        # Get top tags (genres) from Last.fm
        all_tags = []
        # If expanding, get more tags from more artists
        artists_to_check = artist_names[:3] if expand_search else artist_names[:2]
        tags_per_artist = 8 if expand_search else 5
        
        for artist_name in artists_to_check:
            tags = get_artist_tags(artist_name, limit=tags_per_artist)
            for tag in tags:
                tag_name = tag.get('name', '').lower()
                # Filter out non-genre tags
                if tag_name and tag_name not in ['seen live', 'favorites', 'favourite', 'seen', 'live', 'my music']:
                    all_tags.append(tag_name)
        
        # Get unique tags (more if expanding)
        max_tags = 5 if expand_search else 3
        unique_tags = list(set(all_tags))[:max_tags]
        
        # Process genres in parallel
        def process_genre(tag):
            """Process one genre and return recommendations"""
            genre_recommendations = []
            try:
                # Get top artists for this tag (more if expanding)
                artists_limit = 20 if expand_search else 10
                top_artists = get_tag_top_artists(tag, limit=artists_limit)
                
                # Use more artists if expanding
                artists_to_use = top_artists[:10] if expand_search else top_artists[:5]
                
                # Process artists in parallel
                def get_tracks_from_genre_artist(artist_info):
                    artist_name = artist_info.get('name', '')
                    if not artist_name:
                        return []
                    
                    try:
                        tracks_limit = 5 if expand_search else 3
                        lastfm_tracks = get_lastfm_top_tracks(artist_name, limit=tracks_limit)
                        tracks = []
                        
                        for track_info in lastfm_tracks:
                            track_name = track_info.get('name', '')
                            if not track_name:
                                continue
                            
                            # Search Spotify
                            spotify_tracks = search_tracks(
                                self.spotify_token,
                                f"{track_name} {artist_name}",
                                limit=2
                            )
                            
                            for track in spotify_tracks:
                                track_id = track.get('id')
                                if not track_id:
                                    continue
                                
                                # Filter out seed artists
                                track_artist_ids = []
                                if 'artists' in track and isinstance(track.get('artists'), list):
                                    track_artist_ids = [a.get('id') for a in track['artists'] 
                                                      if isinstance(a, dict) and a.get('id')]
                                
                                if not any(aid in seed_artists for aid in track_artist_ids):
                                    tracks.append(track)
                                    break  # Only add first match
                        
                        return tracks
                    except Exception as e:
                        print(f"Error getting tracks for genre artist {artist_name}: {str(e)}")
                        return []
                
                # Process artists in parallel
                with ThreadPoolExecutor(max_workers=5) as executor:
                    futures = {executor.submit(get_tracks_from_genre_artist, artist_info): artist_info 
                              for artist_info in artists_to_use}
                    for future in as_completed(futures):
                        tracks = future.result()
                        genre_recommendations.extend(tracks)
                
            except Exception as e:
                print(f"Error in genre-based recommendations for tag {tag}: {str(e)}")
            
            return genre_recommendations
        
        # Process all genres in parallel
        with ThreadPoolExecutor(max_workers=min(len(unique_tags), 3)) as executor:
            futures = {executor.submit(process_genre, tag): tag for tag in unique_tags}
            for future in as_completed(futures):
                genre_recs = future.result()
                for track in genre_recs:
                    track_id = track.get('id')
                    if track_id and track_id not in seen_track_ids:
                        seen_track_ids.add(track_id)
                        recommendations.append(track)
                        if len(recommendations) >= limit:
                            break
                if len(recommendations) >= limit:
                    break
        
        return recommendations
    
    def _get_spotify_fallback_recommendations(
        self,
        seed_artists: List[str],
        limit: int,
        expand_search: bool = False
    ) -> List[Dict]:
        """
        Fallback recommendation method using Spotify search.
        Only used when Last.fm doesn't provide enough results.
        """
        recommendations = []
        seen_track_ids = set()
        
        # Get genres from seed artists (more if expanding)
        genres = []
        artists_to_check = seed_artists[:3] if expand_search else seed_artists[:2]
        genres_per_artist = 3 if expand_search else 2
        
        for artist_id in artists_to_check:
            try:
                artist_genres = get_artist_genres(self.spotify_token, artist_id)
                genres.extend(artist_genres[:genres_per_artist])
            except:
                pass
        
        # Use more genres if expanding
        max_genres = 5 if expand_search else 3
        genres = list(set(genres))[:max_genres]
        
        # Search by genre (more results if expanding)
        tracks_per_genre = 40 if expand_search else 20
        for genre in genres:
            if len(recommendations) >= limit:
                break
            try:
                tracks = search_tracks(self.spotify_token, f'genre:"{genre}" year:2020-2024', limit=tracks_per_genre)
                for track in tracks:
                    track_id = track.get('id')
                    if track_id and track_id not in seen_track_ids:
                        track_artist_ids = []
                        if 'artists' in track and isinstance(track.get('artists'), list):
                            track_artist_ids = [a.get('id') for a in track['artists'] 
                                              if isinstance(a, dict) and a.get('id')]
                        
                        if not any(aid in seed_artists for aid in track_artist_ids):
                            seen_track_ids.add(track_id)
                            recommendations.append(track)
                            if len(recommendations) >= limit:
                                break
            except Exception as e:
                print(f"Error in Spotify fallback for genre {genre}: {str(e)}")
        
        return recommendations
    
    def _get_youtube_recommendations(
        self,
        seed_artists: List[str],
        seed_tracks: List[str],
        limit: int
    ) -> Dict:
        """
        Optional YouTube recommendations.
        Only used if use_youtube=True.
        """
        result = {
            'seed_videos': [],
            'recommendations': []
        }
        
        # Get seed videos for selected tracks
        if seed_tracks:
            for track_id in seed_tracks[:3]:
                try:
                    url = f'https://api.spotify.com/v1/tracks/{track_id}'
                    headers = {'Authorization': f'Bearer {self.spotify_token}'}
                    response = requests.get(url, headers=headers, timeout=5)
                    if response.status_code == 200:
                        track = response.json()
                        track_name = track.get('name', '')
                        artist_name = track.get('artists', [{}])[0].get('name', '') if track.get('artists') else ''
                        
                        if track_name and artist_name:
                            youtube_video = search_track_on_youtube(track_name, artist_name, prefer_official=True)
                            if youtube_video:
                                youtube_video['spotify_track_id'] = track_id
                                result['seed_videos'].append(youtube_video)
                except:
                    pass
        
        return result


# Convenience function for backward compatibility
def get_hybrid_recommendations(
    spotify_token: str,
    seed_artists: Optional[List[str]] = None,
    seed_tracks: Optional[List[str]] = None,
    limit: int = 20,
    use_youtube: bool = False,
    exclude_track_ids: Optional[List[str]] = None
) -> Dict:
    """
    Get hybrid recommendations (backward compatibility wrapper).
    
    Args:
        spotify_token: Valid Spotify access token
        seed_artists: List of Spotify artist IDs
        seed_tracks: List of Spotify track IDs
        limit: Number of recommendations to return
        use_youtube: Whether to include YouTube recommendations
    
    Returns:
        dict: Recommendation results
    """
    engine = RecommendationEngine(spotify_token, use_youtube=use_youtube)
    result = engine.get_recommendations(
        seed_artists, 
        seed_tracks, 
        limit,
        exclude_track_ids=exclude_track_ids
    )
    
    # Format for backward compatibility
    return {
        'spotify_tracks': result['tracks'],
        'youtube_videos': result.get('youtube_videos', []),
        'seed_videos': result.get('seed_videos', []),
        'sources': result.get('sources', {})
    }

