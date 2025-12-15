# SoundMatch

A music recommendation web application that helps users discover new music based on their preferences.

## Features

- 🎵 **Music Discovery**: Search for artists, tracks, and genres
- 🎯 **Smart Recommendations**: Get personalized recommendations using Last.fm and Spotify APIs
- 💾 **Save Favorites**: Save tracks to your favorites list
- 🔐 **User Authentication**: Secure login with Spotify OAuth or username/password
- 📊 **Recommendation History**: View and manage your past recommendations

## Tech Stack

- **Backend**: Python, Flask, SQLAlchemy
- **Frontend**: HTML, CSS, JavaScript
- **APIs**: Spotify Web API, Last.fm API
- **Database**: SQLite

## Quick Start

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd soundmatch
   ```

2. **Set up environment variables:**
   - Copy `.env.example` to `Back-end/.env`
   - Fill in your API keys (see `Back-end/SETUP.md` for detailed instructions)

3. **Install dependencies:**
   ```bash
   cd Back-end
   pip install -r requirements.txt
   ```

4. **Start the server:**
   ```bash
   python app.py
   ```

5. **Open in browser:**
   ```
   http://localhost:5000
   ```

## Documentation

- **Setup Guide**: `Back-end/SETUP.md` - Complete setup instructions
- **Deployment Guide**: `Back-end/DEPLOYMENT.md` - Deployment instructions for Render & Railway

## Requirements

- Python 3.8+
- Spotify API credentials
- Last.fm API key

See `Back-end/SETUP.md` for detailed setup instructions.