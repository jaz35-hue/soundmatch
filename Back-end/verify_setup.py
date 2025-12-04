import os
import sys
import importlib.util
from pathlib import Path

def print_status(message, status):
    symbol = "[OK]" if status else "[FAIL]"
    print(f"{symbol} {message}")

def check_python_version():
    version = sys.version_info
    is_valid = version.major == 3 and version.minor >= 8
    print_status(f"Python 3.8+ (Current: {version.major}.{version.minor}.{version.micro})", is_valid)
    return is_valid

def check_dependencies():
    required = ['flask', 'requests', 'dotenv', 'flask_sqlalchemy', 'flask_login', 'flask_bcrypt', 'flask_limiter', 'flask_wtf']
    all_installed = True
    print("\nChecking dependencies:")
    for package in required:
        spec = importlib.util.find_spec(package)
        is_installed = spec is not None
        print_status(f"Package '{package}' installed", is_installed)
        if not is_installed:
            all_installed = False
    return all_installed

def check_env_vars():
    from dotenv import load_dotenv
    load_dotenv()
    
    required_vars = ['SPOTIFY_CLIENT_ID', 'SPOTIFY_CLIENT_SECRET', 'LASTFM_API_KEY']
    all_set = True
    print("\nChecking environment variables:")
    for var in required_vars:
        value = os.getenv(var)
        is_set = bool(value)
        print_status(f"Variable '{var}' set", is_set)
        if not is_set:
            all_set = False
            
    # Check optional
    secret_key = os.getenv('SECRET_KEY')
    if secret_key:
        print_status("Variable 'SECRET_KEY' set (Optional for dev)", True)
    else:
        print("WARNING: Variable 'SECRET_KEY' not set (Using auto-generated key for dev)")
        
    return all_set

def main():
    print("SoundMatch Setup Verification")
    print("===========================")
    
    checks = [
        check_python_version(),
        check_dependencies(),
        check_env_vars()
    ]
    
    print("\n===========================")
    if all(checks):
        print("Setup looks good! You can start the server with 'python app.py'")
    else:
        print("Some checks failed. Please fix the issues above before starting.")

if __name__ == "__main__":
    main()
