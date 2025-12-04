# Deploying SoundMatch to Railway

## Prerequisites
- GitHub account with your code pushed to a repository
- Railway account (sign up at https://railway.app)
- All API keys ready (Spotify, Last.fm)

## Step-by-Step Deployment

### 1. Prepare Your Repository
```bash
# Ensure all changes are committed and pushed to GitHub
git add .
git commit -m "Prepare for deployment"
git push origin main
```

### 2. Create Railway Project
1. Go to https://railway.app
2. Click **"New Project"**
3. Select **"Deploy from GitHub repo"**
4. Select your `soundmatch` repository

### 3. Configure Service Settings

**Build & Start Settings:**
Railway usually detects Python automatically, but verify:
- **Root Directory**: `Back-end`
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `python app.py`

**Environment Variables:**
Go to the **Variables** tab and add:

```
SECRET_KEY=your-secret-key-here
SPOTIFY_CLIENT_ID=your-spotify-client-id
SPOTIFY_CLIENT_SECRET=your-spotify-client-secret
SPOTIFY_REDIRECT_URI=https://your-app-url.up.railway.app/callback/spotify
LASTFM_API_KEY=your-lastfm-api-key
FLASK_DEBUG=0
PRODUCTION=true
PORT=5000
```

**Important Notes:**
- Generate a secure `SECRET_KEY`: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
- Update `SPOTIFY_REDIRECT_URI` with your Railway app URL after it's generated (Settings -> Domains)
- Set `FLASK_DEBUG=0` for production

### 4. Create Database (Optional but Recommended)
1. In your project view, click **"New"** -> **"Database"** -> **"PostgreSQL"**
2. Once created, Railway automatically adds `DATABASE_URL` to your service variables
3. SoundMatch will automatically detect `DATABASE_URL` and use PostgreSQL instead of SQLite

### 5. Update Spotify Redirect URI
1. Go to Spotify Developer Dashboard
2. Edit your app settings
3. Add redirect URI: `https://your-app-url.up.railway.app/callback/spotify`
4. Save changes

### 6. Verify Deployment
1. Visit your Railway app URL
2. Test registration/login
3. Test Spotify OAuth flow
4. Test recommendations feature

## Troubleshooting

### Build Fails
- Check build logs in Railway dashboard
- Verify `requirements.txt` includes all dependencies

### App Crashes
- Check "Deploy Logs" in Railway
- Verify all environment variables are set
- Ensure `SECRET_KEY` is set

### Database Issues
- If using SQLite (no PostgreSQL service), data will be lost on redeploy
- Use the PostgreSQL service for persistent data


