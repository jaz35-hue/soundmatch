# Deploying SoundMatch

This guide covers deployment for **Render** (Recommended) and **Railway**.

## Prerequisites
- GitHub account with your code pushed to a repository
- Render or Railway account
- All API keys ready (Spotify, Last.fm)

---

## Option 1: Deploy to Render (Recommended)

### 1. Create Web Service
1. Go to [dashboard.render.com](https://dashboard.render.com)
2. Click **"New +"** -> **"Web Service"**
3. Connect your GitHub repository (`soundmatch`)
4. Select the repository

### 2. Configure Settings
Fill in the following details:
- **Name**: `soundmatch` (or your choice)
- **Region**: Closest to you
- **Branch**: `main`
- **Root Directory**: `Back-end`
- **Runtime**: **Python 3**
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `python app.py`

### 3. Environment Variables
Scroll down to "Environment Variables" and add these:

| Key | Value |
|-----|-------|
| `PYTHON_VERSION` | `3.10.0` (or your local version) |
| `SECRET_KEY` | (Generate one: `python -c "import secrets; print(secrets.token_urlsafe(32))"`) |
| `SPOTIFY_CLIENT_ID` | Your Spotify Client ID |
| `SPOTIFY_CLIENT_SECRET` | Your Spotify Client Secret |
| `SPOTIFY_REDIRECT_URI` | `https://<your-app-name>.onrender.com/callback/spotify` |
| `LASTFM_API_KEY` | Your Last.fm API Key |
| `FLASK_DEBUG` | `0` |
| `PRODUCTION` | `true` |

### 4. Finish & Deploy
- Click **"Create Web Service"**.
- Render will start building your app.
- Once deployed, your URL will be `https://<your-app-name>.onrender.com`.

### 5. Update Spotify Redirect URI
1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Edit your app settings.
3. Add the Render URL to Redirect URIs: `https://<your-app-name>.onrender.com/callback/spotify`
4. Save.

---

## Option 2: Deploy to Railway

### 1. Create Railway Project
1. Go to [railway.app](https://railway.app)
2. Click **"New Project"** -> **"Deploy from GitHub repo"**
3. Select your `soundmatch` repository

### 2. Configure Service Settings

**Build & Start Settings:**
- **Root Directory**: `Back-end`
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `python app.py`

**Environment Variables:**
Go to the **Variables** tab and add:
- `SECRET_KEY`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `LASTFM_API_KEY`, `FLASK_DEBUG=0`, `PRODUCTION=true`
- `SPOTIFY_REDIRECT_URI`: `https://<your-app-url>.up.railway.app/callback/spotify`
- `PORT`: `5000`

### 3. Update Spotify Redirect URI
- Add `https://<your-app-url>.up.railway.app/callback/spotify` to your Spotify Dashboard.

### 4. Database (Optional)
- Add a PostgreSQL volume/service in Railway if you need persistent data, or use Render with a persistent disk.

## Troubleshooting

### Build Fails
- Ensure `Back-end` is set as the Root Directory.
- Check logs for missing packages in `requirements.txt`.

### App Crashes
- Check "Logs" tab.
- Verify `SECRET_KEY` is set.
- Ensure `PRODUCTION=true` is set.
