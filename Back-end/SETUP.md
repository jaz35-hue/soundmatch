# SoundMatch Setup Guide

Complete setup guide for SoundMatch music recommendation system.

## Quick Start

1. **Install dependencies:**
   ```bash
   cd Back-end
   pip install -r requirements.txt
   ```

2. **Set up environment variables** (see sections below)

3. **Start the server:**
   ```bash
   python app.py
   ```

4. **Verify setup:**
   ```bash
   python verify_setup.py
   ```

## Required Environment Variables

Create a `.env` file in the `Back-end` directory with the following:

### 1. Spotify API (Required)

Get your credentials from [Spotify Developer Dashboard](https://developer.spotify.com/dashboard):

```env
SPOTIFY_CLIENT_ID=your_client_id_here
SPOTIFY_CLIENT_SECRET=your_client_secret_here
SPOTIFY_REDIRECT_URI=http://localhost:5000/callback/spotify
```

**Setup Steps:**
1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Create a new app
3. Add redirect URI: `http://localhost:5000/callback/spotify`
4. Copy Client ID and Client Secret

### 2. Last.fm API (Required for Recommendations)

Get your API key from [Last.fm API](https://www.last.fm/api/account/create):

```env
LASTFM_API_KEY=your_lastfm_api_key_here
```

**Setup Steps:**
1. Go to [Last.fm API Account](https://www.last.fm/api/account/create)
2. Sign in or create a Last.fm account
3. Click "Create an API account"
4. Fill in application details:
   - Application name: `SoundMatch`
   - Application description: `Music recommendation system`
   - Callback URL: `http://localhost:5000`
5. Copy your API Key

### 3. YouTube API (Optional)

YouTube recommendations are disabled by default. To enable:

```env
YOUTUBE_API_KEY=your_youtube_api_key_here
```

**Setup Steps:**
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Navigate to **APIs & Services** > **Library**
4. Search for "YouTube Data API v3" and click **Enable**
5. Go to **APIs & Services** > **Credentials**
6. Click **Create Credentials** > **API Key**
7. Copy the API key

**Note:** If you see 403 errors, check:
- API key is valid and active
- YouTube Data API v3 is enabled
- Quota limits haven't been exceeded

### 4. Flask Secret Key (Optional for Development)

```env
SECRET_KEY=your_secret_key_here
```

**Note:** If not set, a temporary key will be auto-generated (development only). Always set this in production.

## Verification

Run the verification script to check your setup:

```bash
cd Back-end
python verify_setup.py
```

Or manually check:

```bash
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print('SPOTIFY_CLIENT_ID:', 'SET' if os.getenv('SPOTIFY_CLIENT_ID') else 'MISSING'); print('LASTFM_API_KEY:', 'SET' if os.getenv('LASTFM_API_KEY') else 'MISSING')"
```

## Testing

1. **Start the server:**
   ```bash
   python app.py
   ```

2. **Open in browser:**
   - Home: `http://localhost:5000`
   - Discover: `http://localhost:5000/discover`
   - Recommendations: `http://localhost:5000/recommendations`

3. **Test recommendations:**
   - Go to Discover page
   - Search for an artist
   - Select artists/songs/genres
   - Click "Get Recommendations"
   - Verify recommendations appear

## Troubleshooting

### "Failed to authenticate with Spotify"
- Check `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` are set correctly
- Verify redirect URI matches in Spotify dashboard

### "No recommendations found"
- Ensure `LASTFM_API_KEY` is set
- Check Last.fm API key is valid
- Try different artists/genres

### Database errors
- Database is created automatically on first run
- If issues occur, delete `database.db` and restart

### Import errors
- Ensure all dependencies are installed: `pip install -r requirements.txt`
- Check Python version (3.8+ required)

## Architecture

See `ARCHITECTURE.md` for detailed system architecture and API responsibilities.

