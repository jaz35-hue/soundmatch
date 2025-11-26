"""Quick setup verification script"""
import os
import sys
from dotenv import load_dotenv

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

print("=" * 60)
print("SoundMatch Setup Verification")
print("=" * 60)

# Check environment variables
print("\n[Environment Variables]")
required = {
    'SPOTIFY_CLIENT_ID': 'Spotify Client ID',
    'SPOTIFY_CLIENT_SECRET': 'Spotify Client Secret', 
    'LASTFM_API_KEY': 'Last.fm API Key'
}

all_ok = True
for var, name in required.items():
    value = os.getenv(var)
    if value:
        print(f"  [OK] {name}: SET")
    else:
        print(f"  [X] {name}: MISSING")
        all_ok = False

youtube_key = os.getenv('YOUTUBE_API_KEY')
if youtube_key:
    print(f"  [OK] YouTube API Key: SET")
else:
    print(f"  [!] YouTube API Key: Not set (optional)")

# Check dependencies
print("\n[Python Dependencies]")
try:
    import flask
    print("  [OK] Flask")
except:
    print("  [X] Flask - Run: pip install flask")
    all_ok = False

try:
    import requests
    print("  [OK] Requests")
except:
    print("  [X] Requests - Run: pip install requests")
    all_ok = False

try:
    from googleapiclient.discovery import build
    print("  [OK] Google API Client (YouTube)")
except:
    print("  [!] Google API Client: Not installed (optional)")

# Check database
print("\n[Database]")
db_path = os.path.join(os.getcwd(), 'database.db')
if os.path.exists(db_path):
    print(f"  [OK] Database exists")
else:
    print("  [!] Database will be created on first run")

# Summary
print("\n" + "=" * 60)
if all_ok:
    print("[OK] Setup looks good! Ready to start.")
    print("\nTo start the server, run:")
    print("   python app.py")
    print("\nThen open: http://localhost:5000/recommendations")
else:
    print("[X] Setup incomplete. Please fix the issues above.")
    print("\nQuick fixes:")
    print("   - Create a .env file with required API keys")
    print("   - Run: pip install -r requirements.txt")
print("=" * 60)

