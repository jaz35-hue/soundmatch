#!/usr/bin/env python3
"""
Quick Start Script - Verifies setup and starts the Flask server
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def check_environment():
    """Check if all required environment variables are set"""
    print("=" * 50)
    print("🔍 Checking Environment Setup...")
    print("=" * 50)
    
    required = {
        'SPOTIFY_CLIENT_ID': 'Spotify Client ID',
        'SPOTIFY_CLIENT_SECRET': 'Spotify Client Secret',
        'LASTFM_API_KEY': 'Last.fm API Key'
    }
    
    optional = {
        'YOUTUBE_API_KEY': 'YouTube API Key (optional)',
        'SECRET_KEY': 'Flask Secret Key (optional - auto-generated in dev)'
    }
    
    all_good = True
    
    print("\n📋 Required Variables:")
    for var, desc in required.items():
        value = os.getenv(var)
        if value:
            print(f"  ✅ {desc}: SET")
        else:
            print(f"  ❌ {desc}: MISSING")
            all_good = False
    
    print("\n📋 Optional Variables:")
    for var, desc in optional.items():
        value = os.getenv(var)
        if value:
            print(f"  ✅ {desc}: SET")
        else:
            print(f"  ⚠️  {desc}: Not set (OK)")
    
    return all_good

def check_dependencies():
    """Check if all required Python packages are installed"""
    print("\n" + "=" * 50)
    print("📦 Checking Python Dependencies...")
    print("=" * 50)
    
    required_packages = {
        'flask': 'Flask',
        'flask_sqlalchemy': 'Flask-SQLAlchemy',
        'flask_login': 'Flask-Login',
        'requests': 'Requests',
        'dotenv': 'python-dotenv'
    }
    
    optional_packages = {
        'googleapiclient': 'Google API Client (for YouTube)'
    }
    
    all_good = True
    
    print("\n📋 Required Packages:")
    for module, name in required_packages.items():
        try:
            __import__(module.replace('-', '_'))
            print(f"  ✅ {name}: Installed")
        except ImportError:
            print(f"  ❌ {name}: MISSING - Run: pip install {name}")
            all_good = False
    
    print("\n📋 Optional Packages:")
    for module, name in optional_packages.items():
        try:
            __import__(module)
            print(f"  ✅ {name}: Installed")
        except ImportError:
            print(f"  ⚠️  {name}: Not installed (optional)")
    
    return all_good

def check_database():
    """Check database status"""
    print("\n" + "=" * 50)
    print("💾 Checking Database...")
    print("=" * 50)
    
    db_path = Path('database.db')
    if db_path.exists():
        size = db_path.stat().st_size
        print(f"  ✅ Database exists ({size:,} bytes)")
    else:
        print("  ⚠️  Database will be created on first run")
    
    return True

def main():
    """Main function"""
    print("\n" + "🚀 SoundMatch Quick Start" + "\n")
    
    # Check environment
    env_ok = check_environment()
    
    # Check dependencies
    deps_ok = check_dependencies()
    
    # Check database
    db_ok = check_database()
    
    print("\n" + "=" * 50)
    print("📊 Summary")
    print("=" * 50)
    
    if env_ok and deps_ok:
        print("\n✅ Everything looks good! Ready to start the server.")
        print("\n" + "=" * 50)
        print("🎯 Next Steps:")
        print("=" * 50)
        print("1. Start the Flask server:")
        print("   python app.py")
        print("\n2. Open your browser:")
        print("   http://localhost:5000/recommendations")
        print("\n3. Test audio previews:")
        print("   - Select artists/songs")
        print("   - Click 'Get Recommendations'")
        print("   - Try the play button on tracks")
        print("\n" + "=" * 50)
        
        # Ask if user wants to start server
        response = input("\n❓ Start the Flask server now? (y/n): ").strip().lower()
        if response == 'y':
            print("\n🚀 Starting Flask server...")
            print("=" * 50)
            print("Server will be available at: http://localhost:5000")
            print("Press Ctrl+C to stop the server")
            print("=" * 50 + "\n")
            
            # Import and run the app
            try:
                from app import app
                app.run(debug=True, host='0.0.0.0', port=5000)
            except KeyboardInterrupt:
                print("\n\n👋 Server stopped. Goodbye!")
            except Exception as e:
                print(f"\n❌ Error starting server: {e}")
                print("\nTry running manually: python app.py")
        else:
            print("\n👋 Run 'python app.py' when you're ready to start!")
    else:
        print("\n❌ Setup incomplete. Please fix the issues above.")
        print("\n💡 Quick fixes:")
        if not env_ok:
            print("   - Create a .env file with required API keys")
            print("   - See SETUP_CHECKLIST.md for details")
        if not deps_ok:
            print("   - Run: pip install -r requirements.txt")
        print()

if __name__ == '__main__':
    main()

