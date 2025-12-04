"""
Main Recommendation Engine
Orchestrates recommendations using multiple APIs with clear responsibilities:
- Last.fm: Primary recommendation engine (similar artists, tracks, genres)
- Spotify: Metadata provider (track details, search, artist info)
"""

from typing import List, Dict, Optional
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import API modules
from spotify_api import (
    get_artist_info,
    normalize_track,
    search_tracks,
    get_artist_genres,
    get_recommendations as get_spotify_recommendations
)
from lastfm_api import (
    get_similar_artists,
    get_similar_tracks,
    get_artist_top_tracks as get_lastfm_top_tracks,
    get_artist_tags,
    get_tag_top_artists
)
class RecommendationEngine:
    """
    Main recommendation engine that coordinates between APIs.
    """
    
    def __init__(self, spotify_token: str):
        """
        Initialize the recommendation engine.
        
        Args:
            spotify_token: Valid Spotify access token
        """
        self.spotify_token = spotify_token
    
    def get_recommendations(
        self,
        seed_artists: Optional[List[str]] = None,
        seed_tracks: Optional[List[str]] = None,
        seed_genres: Optional[List[str]] = None,
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
                'sources': Dict showing which APIs were used
            }
        """
        seed_artists = seed_artists or []
        seed_tracks = seed_tracks or []
        seed_genres = seed_genres or []
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
            'sources': {
                'lastfm': False,
                'spotify': False
            }
        }
        
        try:
            # Determine recommendation strategy based on available seeds
            has_artists = len(seed_artists) > 0
            has_tracks = len(seed_tracks) > 0
            has_genres = len(seed_genres) > 0
            
            # Strategy 1: Genre/Category-only recommendations (use Last.fm tags)
            if has_genres and not has_artists and not has_tracks:
                print(f"Using genre-only recommendations for: {seed_genres}")
                genre_recs = self._get_genre_only_recommendations(
                    seed_genres,
                    search_limit,
                    expand_search=expand_search
                )
                # Filter excluded tracks
                genre_recs = [t for t in genre_recs if t.get('id') not in exclude_set]
                result['tracks'] = genre_recs[:limit]
                result['sources']['lastfm'] = len(genre_recs) > 0
                print(f"✅ Genre-based recommendations: {len(result['tracks'])} tracks")
            
            # Strategy 2: Artist-based recommendations (Last.fm primary)
            elif has_artists:
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
                
                # Step 2: If not enough and genres provided, add genre-based recommendations
                if len(result['tracks']) < limit and has_genres:
                    genre_tracks = get_spotify_recommendations(
                        self.spotify_token,
                        seed_artists=seed_artists[:5] if seed_artists else None,
                        seed_genres=seed_genres[:5],
                        limit=search_limit - len(result['tracks'])
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
            
            # Strategy 3: Track-only recommendations (Last.fm similar tracks)
            elif has_tracks:
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
            
            # Limit to requested amount
            result['tracks'] = result['tracks'][:limit]
            
            print(f"✅ Recommendations: {len(result['tracks'])} tracks "
                  f"(Last.fm: {result['sources']['lastfm']}, "
                  f"Spotify: {result['sources']['spotify']})")
            
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
        
        # Process all artists in parallel (only if we have artists)
        if len(artist_names) > 0:
            max_workers = max(1, min(len(artist_names), 3))  # Ensure at least 1 worker
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
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

        # If we couldn't get any tags from Last.fm (e.g., API 403 or empty data),
        # just return an empty list and let the caller fall back to Spotify-only logic.
        if not unique_tags:
            print("Last.fm genre-based recommendations: no tags found, skipping genre step")
            return []
        
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
        
        # Process all genres in parallel (ensure max_workers >= 1)
        max_workers = max(1, min(len(unique_tags), 3))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
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
    
    def _get_genre_only_recommendations(
        self,
        seed_genres: List[str],
        limit: int,
        expand_search: bool = False
    ) -> List[Dict]:
        """
        Get recommendations based solely on genres/categories using Spotify search.
        This method works when only genres are selected (no artists or tracks).
        Searches Spotify for tracks matching ANY of the selected genres.
        """
        recommendations = []
        seen_track_ids = set()
        
        # Normalize genre names (handle categories that might be formatted differently)
        normalized_genres = []
        for genre in seed_genres[:5]:  # Max 5 genres
            # Convert category IDs to genre names if needed
            genre_lower = genre.lower().strip()
            # Map common category IDs to genre names
            category_map = {
                'pop': 'pop',
                'rock': 'rock',
                'hip-hop': 'hip hop',
                'hip hop': 'hip hop',
                'electronic': 'electronic',
                'jazz': 'jazz',
                'classical': 'classical',
                'country': 'country',
                'r-n-b': 'r&b',
                'r&b': 'r&b',
                'metal': 'metal',
                'indie': 'indie',
                'folk': 'folk',
                'reggae': 'reggae'
            }
            # Use mapped name if it's a category, otherwise use as-is
            normalized_genre = category_map.get(genre_lower, genre_lower)
            normalized_genres.append(normalized_genre)
        
        print(f"Searching Spotify for genres: {normalized_genres}")
        
        # Search Spotify for each genre and combine results
        def search_genre(genre_name):
            """Search Spotify for tracks in a specific genre"""
            genre_tracks = []
            try:
                # Search for tracks using genre as keyword
                # Try multiple search strategies to get diverse results
                search_queries = [
                    genre_name,  # Simple genre name
                    f"genre:{genre_name}",  # Genre filter (if supported)
                    f"tag:{genre_name}",  # Tag filter (if supported)
                ]
                
                # Use the first query that works, or combine results
                tracks_per_genre = (limit // len(normalized_genres)) + 10 if normalized_genres else limit
                if expand_search:
                    tracks_per_genre = tracks_per_genre * 2
                
                # Search with genre name as keyword
                search_results = search_tracks(
                    self.spotify_token,
                    genre_name,
                    limit=min(tracks_per_genre, 50)
                )
                
                # Add initial search results
                for track in search_results:
                    track_id = track.get('id')
                    if track_id:
                        genre_tracks.append(track)
                
                # Also try searching for popular tracks with genre in the query
                if len(genre_tracks) < tracks_per_genre:
                    # Try searching for "popular [genre]" or "[genre] music"
                    additional_queries = [
                        f"{genre_name} music",
                        f"popular {genre_name}",
                        f"best {genre_name}"
                    ]
                    existing_ids = {t.get('id') for t in genre_tracks}
                    for query in additional_queries:
                        if len(genre_tracks) >= tracks_per_genre:
                            break
                        try:
                            more_results = search_tracks(
                                self.spotify_token,
                                query,
                                limit=min(20, tracks_per_genre - len(genre_tracks))
                            )
                            # Add unique tracks
                            for track in more_results:
                                track_id = track.get('id')
                                if track_id and track_id not in existing_ids:
                                    genre_tracks.append(track)
                                    existing_ids.add(track_id)
                        except Exception as e:
                            print(f"Error in additional search for {query}: {str(e)}")
                            continue
                
                print(f"Found {len(genre_tracks)} tracks for genre '{genre_name}'")
                
            except Exception as e:
                print(f"Error searching for genre {genre_name}: {str(e)}")
                import traceback
                traceback.print_exc()
            
            return genre_tracks
        
        # Search all genres in parallel
        if len(normalized_genres) > 0:
            max_workers = max(1, min(len(normalized_genres), 5))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(search_genre, genre): genre for genre in normalized_genres}
                for future in as_completed(futures):
                    genre_tracks = future.result()
                    for track in genre_tracks:
                        track_id = track.get('id')
                        if track_id and track_id not in seen_track_ids:
                            seen_track_ids.add(track_id)
                            recommendations.append(track)
                            if len(recommendations) >= limit:
                                break
                    if len(recommendations) >= limit:
                        break
        
        # Shuffle to mix genres (optional - can be removed if you want genre grouping)
        import random
        random.shuffle(recommendations)
        
        print(f"Found {len(recommendations)} total tracks from genre-only recommendations")
        return recommendations[:limit]
    
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

