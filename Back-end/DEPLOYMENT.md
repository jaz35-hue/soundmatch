# Deploying SoundMatch to Render

## Prerequisites
- GitHub account with your code pushed to a repository
- Render account (sign up at https://render.com)
- All API keys ready (Spotify, Last.fm)

## Step-by-Step Deployment

### 1. Prepare Your Repository
```bash
# Ensure all changes are committed and pushed to GitHub
git add .
git commit -m "Prepare for deployment"
git push origin main
```

### 2. Create Render Account
1. Go to https://render.com
2. Sign up/login with GitHub
3. Authorize Render to access your GitHub repositories

### 3. Create New Web Service
1. Click **"New +"** → **"Web Service"**
2. Connect your GitHub repository
3. Select the repository containing SoundMatch

### 4. Configure Service Settings

**Basic Settings:**
- **Name**: `soundmatch` (or your preferred name)
- **Region**: Choose closest to your users
- **Branch**: `main` (or your default branch)
- **Root Directory**: `Back-end`
- **Runtime**: `Python 3`
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `python app.py`

**Environment Variables:**
Add all required environment variables:

```
SECRET_KEY=your-secret-key-here
SPOTIFY_CLIENT_ID=your-spotify-client-id
SPOTIFY_CLIENT_SECRET=your-spotify-client-secret
SPOTIFY_REDIRECT_URI=https://your-app-name.onrender.com/callback/spotify
LASTFM_API_KEY=your-lastfm-api-key
FLASK_DEBUG=0
PRODUCTION=true
PORT=5000
```

**Important Notes:**
- Generate a secure `SECRET_KEY`: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
- Update `SPOTIFY_REDIRECT_URI` with your Render app URL after deployment
- Set `FLASK_DEBUG=0` for production
- Set `PRODUCTION=true` to enforce SECRET_KEY requirement

### 5. Create PostgreSQL Database (Optional but Recommended)
1. Click **"New +"** → **"PostgreSQL"**
2. Name it: `soundmatch-db`
3. Copy the **Internal Database URL**
4. Add to environment variables as `DATABASE_URL`

**Note:** If using PostgreSQL, update `app.py` to use `DATABASE_URL` instead of SQLite.

### 6. Deploy
1. Click **"Create Web Service"**
2. Wait for build to complete (5-10 minutes)
3. Your app will be available at `https://your-app-name.onrender.com`

### 7. Update Spotify Redirect URI
1. Go to Spotify Developer Dashboard
2. Edit your app settings
3. Add redirect URI: `https://your-app-name.onrender.com/callback/spotify`
4. Save changes

### 8. Verify Deployment
1. Visit your Render app URL
2. Test registration/login
3. Test Spotify OAuth flow
4. Test recommendations feature

## Troubleshooting

### Build Fails
- Check build logs in Render dashboard
- Verify `requirements.txt` includes all dependencies
- Ensure Python version is compatible

### App Crashes
- Check logs in Render dashboard
- Verify all environment variables are set
- Ensure `SECRET_KEY` is set in production

### Database Issues
- SQLite files are ephemeral on Render (reset on restart)
- Use PostgreSQL for persistent data
- Check database connection string

### API Errors
- Verify all API keys are correct
- Check API rate limits
- Review error logs in Render dashboard

## Post-Deployment Checklist
- [ ] All environment variables configured
- [ ] Spotify redirect URI updated
- [ ] App accessible via HTTPS
- [ ] Database initialized (if using PostgreSQL)
- [ ] Test user registration
- [ ] Test Spotify OAuth
- [ ] Test recommendations feature
- [ ] Monitor logs for errors

## Free Tier Limitations
- Services spin down after 15 minutes of inactivity
- First request after spin-down takes ~30 seconds
- 750 hours/month free tier limit
- Consider upgrading for production use

