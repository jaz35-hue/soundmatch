"""
SoundMatch Flask Application
Main application file with routes, models, and configuration.
"""

# Standard library imports
import json
import os
import secrets
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

# Third-party imports
from dotenv import load_dotenv
import requests
from flask import Flask, jsonify, flash, redirect, render_template, request, session, url_for
from flask_bcrypt import Bcrypt
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import InputRequired, Length, Regexp, ValidationError

# Local imports
from spotify_api import (
    add_track_to_spotify_library,
    get_available_genre_seeds,
    get_user_recently_played,
    get_user_top_artists,
    get_user_top_tracks,
    get_valid_spotify_token,
    normalize_track,
    search_tracks
)

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = (BASE_DIR.parent / "templates-front-end").resolve()
STATIC_DIR = FRONTEND_DIR / "static"
INSTANCE_DIR = BASE_DIR / "instance"

# Ensure expected directories exist so deployments work out of the box
FRONTEND_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
INSTANCE_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(
    __name__,
    template_folder=str(FRONTEND_DIR),
    static_folder=str(STATIC_DIR),
)

# SECRET_KEY must be set via environment variable for security
secret_key_raw = os.environ.get('SECRET_KEY')
secret_key = None

if secret_key_raw:
    # Strip whitespace in case there are any leading/trailing spaces
    secret_key = secret_key_raw.strip()
    # Check if after stripping it's still not empty
    if not secret_key:
        secret_key = None
    
app.config['SECRET_KEY'] = secret_key

if not app.config['SECRET_KEY']:
    # Check if we're in production mode
    production_mode = os.environ.get('PRODUCTION', '').lower() in ('true', '1', 'yes')
    
    if production_mode:
        # In production, we must have a SECRET_KEY
        print("ERROR: PRODUCTION mode detected but SECRET_KEY is missing or empty!")
        print(f"DEBUG: PRODUCTION env var = '{os.environ.get('PRODUCTION')}'")
        print(f"DEBUG: SECRET_KEY in os.environ = {'SECRET_KEY' in os.environ}")
        raw_value = os.environ.get('SECRET_KEY', '')
        print(f"DEBUG: SECRET_KEY raw value type = {type(raw_value)}")
        print(f"DEBUG: SECRET_KEY raw value repr = {repr(raw_value)}")
        print(f"DEBUG: SECRET_KEY raw value length = {len(raw_value)}")
        if raw_value:
            print(f"DEBUG: SECRET_KEY after strip length = {len(raw_value.strip())}")
            print(f"DEBUG: SECRET_KEY first 10 chars (repr) = {repr(raw_value[:10])}")
        raise ValueError("SECRET_KEY environment variable is required in production! Please set SECRET_KEY in your Render environment variables.")
    else:
        # Development fallback (NOT SECURE - only for local dev)
        app.config['SECRET_KEY'] = secrets.token_urlsafe(32)
        print("⚠️  WARNING: Using auto-generated SECRET_KEY. Set SECRET_KEY environment variable for production!")

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False  # Suppress deprecation warning
db_path = BASE_DIR / 'database.db'

# Spotify OAuth configuration
SPOTIFY_CLIENT_ID = os.environ.get('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.environ.get('SPOTIFY_CLIENT_SECRET')
SPOTIFY_REDIRECT_URI = os.environ.get('SPOTIFY_REDIRECT_URI', 'http://localhost:5000/callback/spotify')
SPOTIFY_AUTH_URL = 'https://accounts.spotify.com/authorize'
SPOTIFY_TOKEN_URL = 'https://accounts.spotify.com/api/token'
SPOTIFY_API_BASE_URL = 'https://api.spotify.com/v1'
SPOTIFY_SCOPES = 'user-read-email user-read-private user-top-read user-read-recently-played user-library-read user-library-modify'

# Store Spotify credentials in app config for spotify_api.py to access
app.config['SPOTIFY_CLIENT_ID'] = SPOTIFY_CLIENT_ID
app.config['SPOTIFY_CLIENT_SECRET'] = SPOTIFY_CLIENT_SECRET

# If an `instance/database.db` exists (from previous runs), copy it locally
# so the app will continue using the same data. Only copy when the root DB is missing.
instance_db_path = INSTANCE_DIR / 'database.db'
if not db_path.exists() and instance_db_path.exists():
    try:
        shutil.copy2(instance_db_path, db_path)
    except Exception:
        # ignore copy errors; DB creation will proceed later
        pass

# Database configuration - SQLite only
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{db_path}"
print(f"Using SQLite database: {db_path}")

bcrypt = Bcrypt(app)
db = SQLAlchemy(app)

# Setup Flask-Limiter for rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",  # Use Redis in production: os.environ.get('REDIS_URL', 'memory://')
    strategy="fixed-window"
)

# Setup Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


class User(db.Model, UserMixin):
    """User model with account lockout protection."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=True, index=True)  # Made nullable for Spotify users
    password = db.Column(db.String(255), nullable=True)  # Made nullable for Spotify OAuth users
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp(), nullable=False)
    last_login = db.Column(db.DateTime, nullable=True)
    
    # Account lockout fields
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    account_locked = db.Column(db.Boolean, default=False, nullable=False)
    locked_until = db.Column(db.DateTime, nullable=True)
    
    # Spotify OAuth fields
    spotify_id = db.Column(db.String(255), unique=True, nullable=True, index=True)
    spotify_access_token = db.Column(db.String(255), nullable=True)
    spotify_refresh_token = db.Column(db.String(255), nullable=True)
    spotify_token_expires_at = db.Column(db.DateTime, nullable=True)
    auth_provider = db.Column(db.String(20), default='local', nullable=False)  # 'local' or 'spotify'
    
    def __repr__(self):
        return f'<User {self.username}>'
    
    def is_account_locked(self):
        """Check if account is currently locked."""
        if not self.account_locked:
            return False
        if self.locked_until and datetime.now(timezone.utc) > self.locked_until:
            # Lock expired, unlock account
            self.account_locked = False
            self.locked_until = None
            self.failed_login_attempts = 0
            db.session.commit()
            return False
        return True
    
    def increment_failed_login(self, max_attempts=5, lockout_duration_minutes=30):
        """Increment failed login attempts and lock account if threshold reached."""
        self.failed_login_attempts += 1
        
        if self.failed_login_attempts >= max_attempts:
            self.account_locked = True
            self.locked_until = datetime.now(timezone.utc) + timedelta(minutes=lockout_duration_minutes)
            print(f"Account {self.username} locked until {self.locked_until}")
        
        db.session.commit()
    
    def reset_failed_login_attempts(self):
        """Reset failed login attempts on successful login."""
        if self.failed_login_attempts > 0:
            self.failed_login_attempts = 0
            db.session.commit()

class UserPreferences(db.Model):
    """Store user's music preferences"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)

    # Preference data (stored as JSON strings)
    favorite_genres = db.Column(db.Text)  # JSON string of genres
    favorite_artists = db.Column(db.Text)  # JSON string of artist IDs
    disliked_genres = db.Column(db.Text)  # JSON string of genres

    # Listening preferences
    min_popularity = db.Column(db.Integer, default=0)  # 0-100
    max_popularity = db.Column(db.Integer, default=100)
    prefer_explicit = db.Column(db.Boolean, default=True)

    # Time-based preferences
    energy_preference = db.Column(db.String(20), default='any')  # 'low', 'medium', 'high', 'any'
    tempo_preference = db.Column(db.String(20), default='any')  # 'slow', 'medium', 'fast', 'any'

    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    updated_at = db.Column(db.DateTime, onupdate=db.func.current_timestamp())

    # Relationship
    user = db.relationship('User', backref=db.backref('preferences', uselist=False, cascade='all, delete-orphan'))

class RecommendationHistory(db.Model):
    """Track recommendations given to users"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # Recommendation data
    track_id = db.Column(db.String(255), nullable=False)  # Spotify track ID
    track_name = db.Column(db.String(255), nullable=False)
    artist_name = db.Column(db.String(255), nullable=False)
    album_name = db.Column(db.String(255))
    track_image_url = db.Column(db.String(500))
    preview_url = db.Column(db.String(500))
    spotify_url = db.Column(db.String(500))

    # User interaction
    user_rating = db.Column(db.Integer)  # 1-5 stars, null if not rated
    is_saved = db.Column(db.Boolean, default=False)
    is_dismissed = db.Column(db.Boolean, default=False)

    # Metadata
    recommended_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    recommendation_reason = db.Column(db.Text)  # Why was this recommended?

    # Relationship
    user = db.relationship('User', backref=db.backref('recommendations', lazy='dynamic', cascade='all, delete-orphan'))

class SavedTracks(db.Model):
    """User's saved/favorite tracks"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # Track data
    track_id = db.Column(db.String(255), nullable=False)
    track_name = db.Column(db.String(255), nullable=False)
    artist_name = db.Column(db.String(255), nullable=False)
    album_name = db.Column(db.String(255))
    track_image_url = db.Column(db.String(500))
    spotify_url = db.Column(db.String(500))

    # User data
    notes = db.Column(db.Text)  # User's personal notes
    saved_at = db.Column(db.DateTime, default=db.func.current_timestamp())

    # Relationship
    user = db.relationship('User', backref=db.backref('saved_tracks', lazy='dynamic', cascade='all, delete-orphan'))

    # Unique constraint - user can't save the same track twice
    __table_args__ = (db.UniqueConstraint('user_id', 'track_id', name='_user_track_uc'),)

def check_and_update_schema():
    """Check if database schema is up to date and recreate if needed."""
    with app.app_context():
        from sqlalchemy import inspect
        
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        
        if 'user' in tables:
            # Check existing columns
            columns = [col['name'] for col in inspector.get_columns('user')]
            print(f"Existing columns in user table: {columns}")
            
            # Required columns for current schema
            required_columns = {
                'id', 'username', 'email', 'password', 'created_at', 'last_login', 
                'failed_login_attempts', 'account_locked', 'locked_until',
                'spotify_id', 'spotify_access_token', 'spotify_refresh_token', 
                'spotify_token_expires_at', 'auth_provider'
            }
            existing_columns = set(columns)
            
            # Check if all required columns exist
            missing_columns = required_columns - existing_columns
            
            if missing_columns:
                print(f"Missing columns detected: {missing_columns}")
                print("⚠️  Recreating database with updated schema...")
                print("⚠️  WARNING: This will delete all existing user data!")
                
                # Drop and recreate the table
                try:
                    db.drop_all()
                    db.create_all()
                    print("✅ Database schema updated successfully!")
                    return True
                except Exception as e:
                    print(f"❌ Error recreating tables: {str(e)}")
                    return False
            else:
                print("✅ Database schema is up to date.")
                return True
        return True


def init_db():
    """Initialize the database and create all tables."""
    with app.app_context():
        # First, try to update schema if table exists
        schema_updated = check_and_update_schema()
        
        # Create all tables (will only create if they don't exist)
        db.create_all()
        
        if not schema_updated:
            # If schema update failed, drop and recreate
            print("Schema update failed. Dropping and recreating tables...")
            db.drop_all()
            db.create_all()
            print("Database tables recreated successfully!")
        else:
            print("Database tables created/updated successfully!")




class RegisterForm(FlaskForm):
    """Secure registration form with comprehensive validation."""
    username = StringField(
        validators=[
            InputRequired(message="Username is required."),
            Length(min=4, max=20, message="Username must be between 4 and 20 characters."),
            Regexp('^[a-zA-Z0-9_]+$', message="Username can only contain letters, numbers, and underscores.")
        ],
        render_kw={"placeholder": "Username (4-20 characters)", "autocomplete": "username"}
    )
    password = PasswordField(
        validators=[
            InputRequired(message="Password is required."),
            Length(min=8, max=128, message="Password must be between 8 and 128 characters."),
            Regexp(
                r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$',
                message="Password must contain at least one uppercase letter, one lowercase letter, one number, and one special character."
            )
        ],
        render_kw={"placeholder": "Password (min 8 characters)", "autocomplete": "new-password"}
    )
    
    submit = SubmitField("Register")

    def validate_username(self, username):
        """Validate username uniqueness and format."""
        if not username.data:
            return
        
        username.data = username.data.strip()
        
        # Check for reserved usernames
        reserved = ['admin', 'administrator', 'root', 'system', 'support', 'help', 'info']
        if username.data.lower() in reserved:
            raise ValidationError("This username is reserved. Please choose another.")
        
        try:
            existing_user = User.query.filter_by(username=username.data).first()
            if existing_user:
                raise ValidationError("This username is already taken. Please choose another.")
        except Exception as e:
            print(f"Error validating username: {str(e)}")
    
    def validate_password(self, password):
        """Additional password strength validation."""
        if not password.data:
            return
        
        # Check for common weak passwords
        weak_passwords = ['password', '12345678', 'qwerty', 'abc123', 'password123', 'admin123']
        if password.data.lower() in weak_passwords:
            raise ValidationError("This password is too common. Please choose a stronger password.")
        
        # Check for username in password
        try:
            username_field = getattr(self, 'username', None)
            if username_field and username_field.data:
                if username_field.data.lower() in password.data.lower():
                    raise ValidationError("Password cannot contain your username.")
        except AttributeError:
            pass


class LoginForm(FlaskForm):
    username = StringField(validators=[InputRequired(), Length(min=4, max=20)],
                           render_kw={"placeholder": "Username", "autocomplete": "username"})
    password = PasswordField(validators=[InputRequired(), Length(min=4, max=20)],
                             render_kw={"placeholder": "Password", "autocomplete": "current-password"})
    
    submit = SubmitField("Login")




@login_manager.user_loader
def load_user(user_id):
    """Load user by ID. Returns None if user_id is invalid."""
    try:
        # Use db.session.get() instead of deprecated Query.get()
        return db.session.get(User, int(user_id))
    except (ValueError, TypeError):
        return None


@app.route('/')
def home():
    return render_template('home.html') 


# =============================================================================
# Authentication Routes
# =============================================================================

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    """Secure user login with account lockout."""
    # Redirect if already logged in
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    form = LoginForm()
    
    if form.validate_on_submit():
        username = form.username.data.strip()
        password = form.password.data
        
        try:
            user = User.query.filter_by(username=username).first()
            
            # Check if account is locked
            if user and user.is_account_locked():
                remaining_time = (user.locked_until - datetime.now(timezone.utc)).total_seconds() / 60
                flash(f'Account is temporarily locked due to too many failed login attempts. Please try again in {int(remaining_time)} minutes.', 'danger')
                return render_template('login.html', form=form)
            
            # Check if user exists and password is correct
            if user and bcrypt.check_password_hash(user.password, password):
                # Reset failed login attempts on successful login
                user.reset_failed_login_attempts()
                
                # Update last login
                user.last_login = datetime.now(timezone.utc)
                db.session.commit()
                
                # Log user in
                login_user(user, remember=False)
                
                # Redirect to intended page or dashboard
                next_page = request.args.get('next')
                if next_page:
                    return redirect(next_page)
                return redirect(url_for('dashboard'))
            else:
                # Increment failed login attempts if user exists
                if user:
                    user.increment_failed_login()
                    if user.is_account_locked():
                        flash('Too many failed login attempts. Your account has been temporarily locked.', 'danger')
                    else:
                        remaining_attempts = 5 - user.failed_login_attempts
                        if remaining_attempts > 0:
                            flash(f'Invalid username or password. {remaining_attempts} attempt(s) remaining.', 'danger')
                        else:
                            flash('Invalid username or password. Account locked.', 'danger')
                else:
                    flash('Invalid username or password. Please try again.', 'danger')
        except Exception as e:
            print(f"Login error: {str(e)}")
            import traceback
            traceback.print_exc()
            flash('An error occurred during login. Please try again.', 'danger')
    
    return render_template('login.html', form=form)


@app.route('/logout', methods=['GET', 'POST'])
@login_required
def logout():
    # Clear any pending flash messages before logout
    session.pop('_flashes', None)
    logout_user()
    flash('You have been successfully logged out.', 'info')
    return redirect(url_for('login'))


# =============================================================================
# Protected Routes (Require Login)
# =============================================================================

@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    """Dashboard with user's recent tracks"""
    import random
    
    tracks = []
    is_spotify_user = False
    
    # Try to get user's Spotify tracks
    if current_user.spotify_refresh_token:
        token = get_valid_spotify_token(current_user)
        if token:
            is_spotify_user = True
            # Randomly choose time range for variety
            time_ranges = ['short_term', 'medium_term', 'long_term']
            time_range = random.choice(time_ranges)
            
            # Get top tracks
            top_tracks = get_user_top_tracks(token, time_range=time_range, limit=20)
            if top_tracks:
                # Randomly select 3 tracks
                tracks = random.sample(top_tracks, min(3, len(top_tracks)))
            else:
                # Fallback to recently played
                recent = get_user_recently_played(token, limit=20)
                if recent:
                    tracks = random.sample(recent, min(3, len(recent)))
    
    # For non-Spotify users, get random popular tracks
    if not tracks:
        try:
            token, _ = get_spotify_token()
            if token:
                # Search for popular tracks
                popular_queries = ['pop', 'rock', 'hip hop', 'jazz', 'electronic', 'indie', 'r&b', 'country']
                query = random.choice(popular_queries)
                search_results = search_tracks(token, query, limit=20)
                if search_results:
                    tracks = random.sample(search_results, min(3, len(search_results)))
        except Exception as e:
            print(f"Error getting random tracks: {str(e)}")
    
    return render_template('dashboard.html', tracks=tracks, is_spotify_user=is_spotify_user)


@app.route('/discover')
def discover():
    """Public discover page."""
    return render_template('discover.html')


@app.route('/recommendations')
def recommendations():
    """Public recommendations page."""
    return render_template('recommendations.html')


@app.route('/saved')
@login_required
def saved():
    """User's saved tracks page."""
    return render_template('saved.html')


@app.route('/register', methods=['GET', 'POST'])
@limiter.limit("5 per hour")
def register():
    """Secure user registration."""
    # Redirect if already logged in
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    form = RegisterForm()

    if form.validate_on_submit():
        try:
            # Normalize and sanitize input
            username = form.username.data.strip()
            password = form.password.data
            
            # Final duplicate check
            existing_username = User.query.filter_by(username=username).first()
            if existing_username:
                flash('Username already exists. Please choose a different username.', 'danger')
                form.username.errors.append('Username already exists.')
                return render_template('register.html', form=form)
            
            # Hash password
            hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
            
            # Create new user
            new_user = User(
                username=username,
                email=None,
                password=hashed_password,
                created_at=datetime.now(timezone.utc),
                auth_provider='local'
            )
            db.session.add(new_user)
            db.session.commit()
            
            flash('Registration successful! You can now log in.', 'success')
            return redirect(url_for('login'))
            
        except Exception as e:
            db.session.rollback()
            import traceback
            error_trace = traceback.format_exc()
            print(f"Registration error: {str(e)}")
            print(f"Traceback: {error_trace}")
            
            error_str = str(e).lower()
            if 'unique constraint failed' in error_str or 'integrityerror' in error_str:
                if 'username' in error_str:
                    flash('Username already exists.', 'danger')
                    form.username.errors.append('Username already exists.')
            else:
                flash('An error occurred during registration. Please try again.', 'danger')

    return render_template('register.html', form=form)




# =============================================================================
# Spotify OAuth Routes
# =============================================================================

@app.route('/login/spotify')
def login_spotify():
    """Initiate Spotify OAuth flow."""
    # Redirect if already logged in
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if not SPOTIFY_CLIENT_ID:
        flash('Spotify login is not configured. Please use regular login.', 'warning')
        return redirect(url_for('login'))
    
    # Generate state token for CSRF protection
    state = secrets.token_urlsafe(16)
    session['oauth_state'] = state
    
    # Build authorization URL
    params = {
        'client_id': SPOTIFY_CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': SPOTIFY_REDIRECT_URI,
        'state': state,
        'scope': SPOTIFY_SCOPES,
        'show_dialog': 'false'
    }
    
    auth_url = f"{SPOTIFY_AUTH_URL}?{urlencode(params)}"
    return redirect(auth_url)


@app.route('/callback/spotify')
def spotify_callback():
    """Handle Spotify OAuth callback."""
    # Verify state to prevent CSRF
    state = request.args.get('state')
    if not state or state != session.get('oauth_state'):
        flash('Invalid state parameter. Please try again.', 'danger')
        return redirect(url_for('login'))
    
    # Clear the state
    session.pop('oauth_state', None)
    
    # Check for errors
    error = request.args.get('error')
    if error:
        flash(f'Spotify authorization failed: {error}', 'danger')
        return redirect(url_for('login'))
    
    # Get authorization code
    code = request.args.get('code')
    if not code:
        flash('No authorization code received.', 'danger')
        return redirect(url_for('login'))
    
    try:
        # Exchange code for access token
        token_data = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': SPOTIFY_REDIRECT_URI,
            'client_id': SPOTIFY_CLIENT_ID,
            'client_secret': SPOTIFY_CLIENT_SECRET
        }
        
        token_response = requests.post(SPOTIFY_TOKEN_URL, data=token_data)
        token_response.raise_for_status()
        token_info = token_response.json()
        
        access_token = token_info['access_token']
        refresh_token = token_info.get('refresh_token')
        expires_in = token_info.get('expires_in', 3600)
        
        # Get user profile from Spotify
        headers = {'Authorization': f'Bearer {access_token}'}
        profile_response = requests.get(f'{SPOTIFY_API_BASE_URL}/me', headers=headers)
        profile_response.raise_for_status()
        profile = profile_response.json()
        
        spotify_id = profile['id']
        spotify_email = profile.get('email')
        display_name = profile.get('display_name', spotify_id)
        
        # Check if user exists
        user = User.query.filter_by(spotify_id=spotify_id).first()
        
        if user:
            # Update existing user's tokens
            user.spotify_access_token = access_token
            user.spotify_refresh_token = refresh_token
            user.spotify_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            user.last_login = datetime.now(timezone.utc)
            db.session.commit()
            
            login_user(user, remember=False)
            flash(f'Welcome back, {user.username}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            # Create new user
            # Generate unique username from display_name
            base_username = ''.join(c for c in display_name if c.isalnum() or c == '_')[:20]
            username = base_username
            counter = 1
            while User.query.filter_by(username=username).first():
                username = f"{base_username}{counter}"
                counter += 1
            
            new_user = User(
                username=username,
                email=spotify_email,
                password=None,  # No password for OAuth users
                spotify_id=spotify_id,
                spotify_access_token=access_token,
                spotify_refresh_token=refresh_token,
                spotify_token_expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
                auth_provider='spotify',
                created_at=datetime.now(timezone.utc)
            )
            
            db.session.add(new_user)
            db.session.commit()
            
            login_user(new_user, remember=False)
            flash(f'Welcome to SoundMatch, {new_user.username}! Your account has been created via Spotify.', 'success')
            return redirect(url_for('dashboard'))
    
    except requests.RequestException as e:
        print(f"Spotify API error: {str(e)}")
        flash('Failed to connect to Spotify. Please try again.', 'danger')
        return redirect(url_for('login'))
    except Exception as e:
        print(f"Error in Spotify callback: {str(e)}")
        import traceback
        traceback.print_exc()
        flash('An error occurred during Spotify login. Please try again.', 'danger')
        return redirect(url_for('login'))


# =============================================================================
# TESTING ENDPOINTS - Spotify API Integration Test
# =============================================================================

@app.route('/test/spotify', methods=['GET'])
@login_required
def test_spotify_api():
    """Test Spotify API integration"""
    
    # Get valid token
    token = get_valid_spotify_token(current_user)
    
    if not token:
        return jsonify({'error': 'No valid Spotify token. Please login with Spotify.'}), 401
    
    # Test fetching top tracks
    top_tracks = get_user_top_tracks(token, limit=5)
    
    # Test fetching top artists
    top_artists = get_user_top_artists(token, limit=5)
    
    return jsonify({
        'message': 'Spotify API test successful',
        'user': current_user.username,
        'auth_provider': current_user.auth_provider,
        'top_tracks_count': len(top_tracks),
        'top_artists_count': len(top_artists),
        'sample_top_track': top_tracks[0] if top_tracks else None
    }), 200


# =============================================================================
# API ENDPOINTS - CRUD Operations
# =============================================================================

# -----------------------------------------------------------------------------
# User Preferences CRUD
# -----------------------------------------------------------------------------

@app.route('/api/preferences', methods=['GET'])
@login_required
def get_preferences():
    """Get current user's preferences"""
    try:
        prefs = current_user.preferences
        
        if not prefs:
            # Return default preferences if none exist
            return jsonify({
                'exists': False,
                'preferences': {
                    'favorite_genres': [],
                    'favorite_artists': [],
                    'disliked_genres': [],
                    'min_popularity': 0,
                    'max_popularity': 100,
                    'prefer_explicit': True,
                    'energy_preference': 'any',
                    'tempo_preference': 'any'
                }
            }), 200
        
        # Parse JSON fields
        favorite_genres = json.loads(prefs.favorite_genres) if prefs.favorite_genres else []
        favorite_artists = json.loads(prefs.favorite_artists) if prefs.favorite_artists else []
        disliked_genres = json.loads(prefs.disliked_genres) if prefs.disliked_genres else []
        
        return jsonify({
            'exists': True,
            'preferences': {
                'id': prefs.id,
                'favorite_genres': favorite_genres,
                'favorite_artists': favorite_artists,
                'disliked_genres': disliked_genres,
                'min_popularity': prefs.min_popularity,
                'max_popularity': prefs.max_popularity,
                'prefer_explicit': prefs.prefer_explicit,
                'energy_preference': prefs.energy_preference,
                'tempo_preference': prefs.tempo_preference,
                'created_at': prefs.created_at.isoformat() if prefs.created_at else None,
                'updated_at': prefs.updated_at.isoformat() if prefs.updated_at else None
            }
        }), 200
        
    except Exception as e:
        print(f"Error getting preferences: {str(e)}")
        return jsonify({'error': 'Failed to retrieve preferences'}), 500


@app.route('/api/preferences', methods=['POST', 'PUT'])
@login_required
def create_or_update_preferences():
    """Create or update user preferences"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Check if preferences exist
        prefs = current_user.preferences
        
        if prefs:
            # Update existing preferences
            if 'favorite_genres' in data:
                prefs.favorite_genres = json.dumps(data['favorite_genres'])
            if 'favorite_artists' in data:
                prefs.favorite_artists = json.dumps(data['favorite_artists'])
            if 'disliked_genres' in data:
                prefs.disliked_genres = json.dumps(data['disliked_genres'])
            if 'min_popularity' in data:
                prefs.min_popularity = data['min_popularity']
            if 'max_popularity' in data:
                prefs.max_popularity = data['max_popularity']
            if 'prefer_explicit' in data:
                prefs.prefer_explicit = data['prefer_explicit']
            if 'energy_preference' in data:
                prefs.energy_preference = data['energy_preference']
            if 'tempo_preference' in data:
                prefs.tempo_preference = data['tempo_preference']
            
            prefs.updated_at = datetime.now(timezone.utc)
            db.session.commit()
            
            return jsonify({
                'message': 'Preferences updated successfully',
                'preferences_id': prefs.id
            }), 200
        else:
            # Create new preferences
            new_prefs = UserPreferences(
                user_id=current_user.id,
                favorite_genres=json.dumps(data.get('favorite_genres', [])),
                favorite_artists=json.dumps(data.get('favorite_artists', [])),
                disliked_genres=json.dumps(data.get('disliked_genres', [])),
                min_popularity=data.get('min_popularity', 0),
                max_popularity=data.get('max_popularity', 100),
                prefer_explicit=data.get('prefer_explicit', True),
                energy_preference=data.get('energy_preference', 'any'),
                tempo_preference=data.get('tempo_preference', 'any')
            )
            
            db.session.add(new_prefs)
            db.session.commit()
            
            return jsonify({
                'message': 'Preferences created successfully',
                'preferences_id': new_prefs.id
            }), 201
            
    except Exception as e:
        db.session.rollback()
        print(f"Error creating/updating preferences: {str(e)}")
        return jsonify({'error': 'Failed to save preferences'}), 500


@app.route('/api/preferences', methods=['DELETE'])
@login_required
def delete_preferences():
    """Delete user preferences (reset to defaults)"""
    try:
        prefs = current_user.preferences
        
        if prefs:
            db.session.delete(prefs)
            db.session.commit()
            return jsonify({'message': 'Preferences deleted successfully'}), 200
        else:
            return jsonify({'message': 'No preferences to delete'}), 404
            
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting preferences: {str(e)}")
        return jsonify({'error': 'Failed to delete preferences'}), 500


# -----------------------------------------------------------------------------
# Recommendation History CRUD
# -----------------------------------------------------------------------------

@app.route('/api/recommendations/history', methods=['GET'])
@login_required
def get_recommendation_history():
    """Get user's recommendation history with pagination"""
    try:
        # Pagination parameters
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        # Filtering parameters
        rated_only = request.args.get('rated_only', 'false').lower() == 'true'
        saved_only = request.args.get('saved_only', 'false').lower() == 'true'
        dismissed_only = request.args.get('dismissed_only', 'false').lower() == 'true'
        
        # Build query
        query = current_user.recommendations
        
        if rated_only:
            query = query.filter(RecommendationHistory.user_rating.isnot(None))
        if saved_only:
            query = query.filter(RecommendationHistory.is_saved == True)
        if dismissed_only:
            query = query.filter(RecommendationHistory.is_dismissed == True)
        
        # Order by most recent first
        query = query.order_by(RecommendationHistory.recommended_at.desc())
        
        # Paginate
        paginated = query.paginate(page=page, per_page=per_page, error_out=False)
        
        recommendations = [{
            'id': rec.id,
            'track_id': rec.track_id,
            'track_name': rec.track_name,
            'artist_name': rec.artist_name,
            'album_name': rec.album_name,
            'track_image_url': rec.track_image_url,
            'preview_url': rec.preview_url,
            'spotify_url': rec.spotify_url,
            'user_rating': rec.user_rating,
            'is_saved': rec.is_saved,
            'is_dismissed': rec.is_dismissed,
            'recommended_at': rec.recommended_at.isoformat() if rec.recommended_at else None,
            'recommendation_reason': rec.recommendation_reason
        } for rec in paginated.items]
        
        return jsonify({
            'recommendations': recommendations,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': paginated.total,
                'pages': paginated.pages,
                'has_next': paginated.has_next,
                'has_prev': paginated.has_prev
            }
        }), 200
        
    except Exception as e:
        print(f"Error getting recommendation history: {str(e)}")
        return jsonify({'error': 'Failed to retrieve recommendation history'}), 500


@app.route('/api/recommendations/history/<int:rec_id>', methods=['GET'])
@login_required
def get_recommendation(rec_id):
    """Get specific recommendation by ID"""
    try:
        rec = RecommendationHistory.query.filter_by(
            id=rec_id,
            user_id=current_user.id
        ).first()
        
        if not rec:
            return jsonify({'error': 'Recommendation not found'}), 404
        
        return jsonify({
            'id': rec.id,
            'track_id': rec.track_id,
            'track_name': rec.track_name,
            'artist_name': rec.artist_name,
            'album_name': rec.album_name,
            'track_image_url': rec.track_image_url,
            'preview_url': rec.preview_url,
            'spotify_url': rec.spotify_url,
            'user_rating': rec.user_rating,
            'is_saved': rec.is_saved,
            'is_dismissed': rec.is_dismissed,
            'recommended_at': rec.recommended_at.isoformat() if rec.recommended_at else None,
            'recommendation_reason': rec.recommendation_reason
        }), 200
        
    except Exception as e:
        print(f"Error getting recommendation: {str(e)}")
        return jsonify({'error': 'Failed to retrieve recommendation'}), 500


@app.route('/api/recommendations/<int:rec_id>/rate', methods=['POST'])
@login_required
def rate_recommendation(rec_id):
    """Rate a recommendation (1-5 stars)"""
    try:
        data = request.get_json()
        rating = data.get('rating')
        
        if not rating or rating not in [1, 2, 3, 4, 5]:
            return jsonify({'error': 'Rating must be between 1 and 5'}), 400
        
        rec = RecommendationHistory.query.filter_by(
            id=rec_id,
            user_id=current_user.id
        ).first()
        
        if not rec:
            return jsonify({'error': 'Recommendation not found'}), 404
        
        rec.user_rating = rating
        db.session.commit()
        
        return jsonify({
            'message': 'Rating saved successfully',
            'rating': rating
        }), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"Error rating recommendation: {str(e)}")
        return jsonify({'error': 'Failed to save rating'}), 500


@app.route('/api/recommendations/<int:rec_id>/save', methods=['POST'])
@login_required
def save_recommendation(rec_id):
    """Mark a recommendation as saved"""
    try:
        rec = RecommendationHistory.query.filter_by(
            id=rec_id,
            user_id=current_user.id
        ).first()
        
        if not rec:
            return jsonify({'error': 'Recommendation not found'}), 404
        
        rec.is_saved = True
        db.session.commit()
        
        return jsonify({'message': 'Recommendation saved successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"Error saving recommendation: {str(e)}")
        return jsonify({'error': 'Failed to save recommendation'}), 500


@app.route('/api/recommendations/<int:rec_id>/dismiss', methods=['POST'])
@login_required
def dismiss_recommendation(rec_id):
    """Mark a recommendation as dismissed"""
    try:
        rec = RecommendationHistory.query.filter_by(
            id=rec_id,
            user_id=current_user.id
        ).first()
        
        if not rec:
            return jsonify({'error': 'Recommendation not found'}), 404
        
        rec.is_dismissed = True
        db.session.commit()
        
        return jsonify({'message': 'Recommendation dismissed successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"Error dismissing recommendation: {str(e)}")
        return jsonify({'error': 'Failed to dismiss recommendation'}), 500


@app.route('/api/recommendations/history/<int:rec_id>', methods=['DELETE'])
@login_required
def delete_recommendation(rec_id):
    """Delete a recommendation from history"""
    try:
        rec = RecommendationHistory.query.filter_by(
            id=rec_id,
            user_id=current_user.id
        ).first()
        
        if not rec:
            return jsonify({'error': 'Recommendation not found'}), 404
        
        db.session.delete(rec)
        db.session.commit()
        
        return jsonify({'message': 'Recommendation deleted successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting recommendation: {str(e)}")
        return jsonify({'error': 'Failed to delete recommendation'}), 500


# -----------------------------------------------------------------------------
# Saved Tracks CRUD
# -----------------------------------------------------------------------------

@app.route('/api/saved-tracks', methods=['GET'])
@login_required
def get_saved_tracks():
    """Get all saved tracks with pagination"""
    try:
        # Pagination parameters
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        # Search parameter
        search = request.args.get('search', '').strip()
        
        # Build query
        query = current_user.saved_tracks
        
        # Apply search filter
        if search:
            search_filter = f"%{search}%"
            query = query.filter(
                db.or_(
                    SavedTracks.track_name.ilike(search_filter),
                    SavedTracks.artist_name.ilike(search_filter),
                    SavedTracks.album_name.ilike(search_filter)
                )
            )
        
        # Order by most recent first
        query = query.order_by(SavedTracks.saved_at.desc())
        
        # Paginate
        paginated = query.paginate(page=page, per_page=per_page, error_out=False)
        
        saved_tracks = [{
            'id': track.id,
            'track_id': track.track_id,
            'track_name': track.track_name,
            'artist_name': track.artist_name,
            'album_name': track.album_name,
            'track_image_url': track.track_image_url,
            'spotify_url': track.spotify_url,
            'notes': track.notes,
            'saved_at': track.saved_at.isoformat() if track.saved_at else None
        } for track in paginated.items]
        
        return jsonify({
            'saved_tracks': saved_tracks,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': paginated.total,
                'pages': paginated.pages,
                'has_next': paginated.has_next,
                'has_prev': paginated.has_prev
            }
        }), 200
        
    except Exception as e:
        print(f"Error getting saved tracks: {str(e)}")
        return jsonify({'error': 'Failed to retrieve saved tracks'}), 500


@app.route('/api/saved-tracks/<int:track_id>', methods=['GET'])
@login_required
def get_saved_track(track_id):
    """Get specific saved track by ID"""
    try:
        track = SavedTracks.query.filter_by(
            id=track_id,
            user_id=current_user.id
        ).first()
        
        if not track:
            return jsonify({'error': 'Saved track not found'}), 404
        
        return jsonify({
            'id': track.id,
            'track_id': track.track_id,
            'track_name': track.track_name,
            'artist_name': track.artist_name,
            'album_name': track.album_name,
            'track_image_url': track.track_image_url,
            'spotify_url': track.spotify_url,
            'notes': track.notes,
            'saved_at': track.saved_at.isoformat() if track.saved_at else None
        }), 200
        
    except Exception as e:
        print(f"Error getting saved track: {str(e)}")
        return jsonify({'error': 'Failed to retrieve saved track'}), 500


@app.route('/api/saved-tracks', methods=['POST'])
@login_required
def save_track():
    """Save a new track to favorites"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Required fields
        required_fields = ['track_id', 'track_name', 'artist_name']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Check if already saved
        existing = SavedTracks.query.filter_by(
            user_id=current_user.id,
            track_id=data['track_id']
        ).first()
        
        if existing:
            return jsonify({'error': 'Track already saved'}), 409
        
        # Create new saved track
        new_track = SavedTracks(
            user_id=current_user.id,
            track_id=data['track_id'],
            track_name=data['track_name'],
            artist_name=data['artist_name'],
            album_name=data.get('album_name'),
            track_image_url=data.get('track_image_url'),
            spotify_url=data.get('spotify_url'),
            notes=data.get('notes', '')
        )
        
        db.session.add(new_track)
        db.session.commit()
        
        return jsonify({
            'message': 'Track saved successfully',
            'track_id': new_track.id
        }), 201
        
    except Exception as e:
        db.session.rollback()
        print(f"Error saving track: {str(e)}")
        return jsonify({'error': 'Failed to save track'}), 500


@app.route('/api/saved-tracks/<int:track_id>', methods=['PUT'])
@login_required
def update_saved_track(track_id):
    """Update notes for a saved track"""
    try:
        data = request.get_json()
        
        if not data or 'notes' not in data:
            return jsonify({'error': 'Notes field required'}), 400
        
        track = SavedTracks.query.filter_by(
            id=track_id,
            user_id=current_user.id
        ).first()
        
        if not track:
            return jsonify({'error': 'Saved track not found'}), 404
        
        track.notes = data['notes']
        db.session.commit()
        
        return jsonify({'message': 'Notes updated successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"Error updating saved track: {str(e)}")
        return jsonify({'error': 'Failed to update notes'}), 500


@app.route('/api/spotify/add-to-library', methods=['POST'])
@login_required
def add_to_spotify_library():
    """Add a track to user's Spotify liked songs"""
    try:
        if current_user.auth_provider != 'spotify':
            return jsonify({'error': 'Spotify account required'}), 403
        
        data = request.get_json()
        if not data or 'track_id' not in data:
            return jsonify({'error': 'track_id required'}), 400
        
        track_id = data['track_id']
        token = get_valid_spotify_token(current_user)
        
        if not token:
            return jsonify({'error': 'Failed to get Spotify token'}), 500
        
        success = add_track_to_spotify_library(token, track_id)
        
        if success:
            return jsonify({'message': 'Track added to Spotify library'}), 200
        else:
            return jsonify({'error': 'Failed to add track to Spotify library'}), 500
            
    except Exception as e:
        print(f"Error adding track to Spotify library: {str(e)}")
        return jsonify({'error': 'Failed to add track to Spotify library'}), 500


@app.route('/api/saved-tracks/<int:track_id>', methods=['DELETE'])
@login_required
def delete_saved_track(track_id):
    """Remove a track from saved/favorites"""
    try:
        track = SavedTracks.query.filter_by(
            id=track_id,
            user_id=current_user.id
        ).first()
        
        if not track:
            return jsonify({'error': 'Saved track not found'}), 404
        
        db.session.delete(track)
        db.session.commit()
        
        return jsonify({'message': 'Track removed from saved successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting saved track: {str(e)}")
        return jsonify({'error': 'Failed to remove saved track'}), 500


# =============================================================================
# PUBLIC API ENDPOINTS - No Login Required
# =============================================================================

@app.route('/api/public/search/artists', methods=['GET'])
def public_search_artists():
    """
    Search for artists without requiring login.
    Uses user's Spotify token if logged in, otherwise app credentials.
    
    Query params:
        q: Search query (artist name)
        limit: Number of results (default 10, max 50)
    """
    try:
        query = request.args.get('q', '').strip()
        limit = request.args.get('limit', 10, type=int)
        
        if not query:
            return jsonify({'error': 'Search query required', 'artists': []}), 400
        
        # Get best available token
        token, _ = get_spotify_token()
        if not token:
            print("Failed to get Spotify token for artist search")
            return jsonify({'error': 'Failed to authenticate with Spotify', 'artists': []}), 500
        
        # Search for artists
        url = 'https://api.spotify.com/v1/search'
        headers = {'Authorization': f'Bearer {token}'}
        params = {
            'q': query,
            'type': 'artist',
            'limit': min(limit, 50)
        }
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            
            # Handle HTTP errors
            if response.status_code == 401:
                print("Spotify API returned 401 (unauthorized) - token may be expired")
                return jsonify({'error': 'Authentication failed. Please try again.', 'artists': []}), 401
            elif response.status_code == 429:
                print("Spotify API rate limit exceeded")
                return jsonify({'error': 'Too many requests. Please try again in a moment.', 'artists': []}), 429
            elif response.status_code >= 400:
                print(f"Spotify API error: {response.status_code} - {response.text}")
                return jsonify({'error': 'Spotify API error. Please try again.', 'artists': []}), response.status_code
            
            response.raise_for_status()
            data = response.json()
            
        except requests.Timeout:
            print("Spotify API request timed out")
            return jsonify({'error': 'Request timed out. Please try again.', 'artists': []}), 504
        except requests.RequestException as e:
            print(f"Spotify API request error: {str(e)}")
            return jsonify({'error': 'Failed to connect to Spotify. Please try again.', 'artists': []}), 503
        
        # Parse results
        artists = []
        artists_data = data.get('artists', {})
        items = artists_data.get('items', [])
        
        for artist in items:
            try:
                artists.append({
                    'id': artist['id'],
                    'name': artist['name'],
                    'genres': artist.get('genres', []),
                    'image_url': artist['images'][0]['url'] if artist.get('images') and len(artist['images']) > 0 else None,
                    'spotify_url': artist['external_urls']['spotify'],
                    'popularity': artist.get('popularity', 0),
                    'followers': artist.get('followers', {}).get('total', 0)
                })
            except (KeyError, IndexError) as e:
                print(f"Error parsing artist data: {str(e)}")
                continue
        
        return jsonify({
            'artists': artists,
            'count': len(artists)
        }), 200
        
    except Exception as e:
        print(f"Error searching artists: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'An unexpected error occurred. Please try again.', 'artists': []}), 500


@app.route('/api/public/search/tracks', methods=['GET'])
def public_search_tracks():
    """
    Search for tracks without requiring login.
    Uses user's Spotify token if logged in, otherwise app credentials.
    
    Query params:
        q: Search query (track name, artist, etc.)
        limit: Number of results (default 10, max 50)
    """
    try:
        query = request.args.get('q', '').strip()
        limit = request.args.get('limit', 10, type=int)
        
        if not query:
            return jsonify({'error': 'Search query required'}), 400
        
        # Get best available token
        token, _ = get_spotify_token()
        if not token:
            return jsonify({'error': 'Failed to authenticate with Spotify'}), 500
        
        # Use the search_tracks function from spotify_api
        tracks = search_tracks(token, query, limit=min(limit, 50))
        
        return jsonify({
            'tracks': tracks,
            'count': len(tracks)
        }), 200
        
    except Exception as e:
        print(f"Error searching tracks: {str(e)}")
        return jsonify({'error': 'Failed to search tracks'}), 500


@app.route('/api/public/artist/<artist_id>', methods=['GET'])
def public_get_artist(artist_id):
    """
    Get artist by ID without requiring login.
    Uses user's Spotify token if logged in, otherwise app credentials.
    """
    try:
        # Get best available token
        token, _ = get_spotify_token()
        if not token:
            return jsonify({'error': 'Failed to authenticate with Spotify'}), 500
        
        url = f'https://api.spotify.com/v1/artists/{artist_id}'
        headers = {'Authorization': f'Bearer {token}'}
        
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        artist = response.json()
        
        artist_data = {
            'id': artist['id'],
            'name': artist['name'],
            'genres': artist.get('genres', []),
            'image_url': artist['images'][0]['url'] if artist.get('images') else None,
            'spotify_url': artist['external_urls']['spotify'],
            'popularity': artist.get('popularity', 0),
            'followers': artist.get('followers', {}).get('total', 0)
        }
        
        return jsonify({'artist': artist_data}), 200
        
    except Exception as e:
        print(f"Error getting artist: {str(e)}")
        return jsonify({'error': 'Failed to get artist'}), 500


@app.route('/api/public/genres', methods=['GET'])
def public_get_genres():
    """Get list of available genre seeds for recommendations."""
    try:
        # Get best available token
        token, using_user_token = get_spotify_token()
        if using_user_token:
            print(f"Using Spotify token for logged-in user: {current_user.username}")
        
        if not token:
            # If we can't get any token, use fallback genres
            genres = get_fallback_genres()
            return jsonify({
                'genres': genres,
                'count': len(genres),
                'using_fallback': True,
                'note': 'Using fallback genres (Failed to authenticate with Spotify)'
            }), 200
        
        # Genre seeds endpoint is deprecated (Nov 2024) - use fallback immediately
        # No need to try the API call
        genres = get_fallback_genres()
        using_fallback = True
        print(f"Using fallback genre list with {len(genres)} genres (Genre seeds endpoint deprecated)")
        
        return jsonify({
            'genres': genres,
            'count': len(genres),
            'using_fallback': using_fallback,
            'using_user_token': using_user_token,
            'note': 'Using fallback genres (Spotify API requires user authentication for genre seeds)' if using_fallback else None
        }), 200
        
    except Exception as e:
        print(f"Error getting genres: {str(e)}")
        # Return fallback genres
        genres = get_fallback_genres()
        return jsonify({
            'genres': genres,
            'count': len(genres)
        }), 200


@app.route('/api/public/recommendations', methods=['POST'])
def public_get_recommendations():
    """
    Get recommendations without requiring login.
    Anyone can use this to discover music!
    If logged in, uses user's Spotify token for better results.
    Recommendations are automatically saved to history for logged-in users.
    
    Request body:
        seed_artists: List of artist IDs (up to 5)
        seed_tracks: List of track IDs (up to 5)
        seed_genres: List of genre names (up to 5)
        limit: Number of recommendations (default 20, max 100)
        min_popularity: Minimum popularity (0-100)
        max_popularity: Maximum popularity (0-100)
        target_energy: Target energy level (0.0-1.0)
        target_valence: Target mood/positivity (0.0-1.0)
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'Request body required'}), 400
        
        # Get best available token
        token, using_user_token = get_spotify_token()
        if using_user_token:
            print(f"Using Spotify token for logged-in user: {current_user.username}")
        
        if not token:
            return jsonify({'error': 'Failed to authenticate with Spotify'}), 500
        
        # Extract parameters
        seed_artists = data.get('seed_artists', [])
        seed_tracks = data.get('seed_tracks', [])
        seed_genres = data.get('seed_genres', [])
        
        # Validate we have at least one seed
        if not seed_artists and not seed_tracks and not seed_genres:
            return jsonify({'error': 'At least one seed (artist, track, or genre) required'}), 400
        
        # Ensure we have at least 2 seeds for better recommendations
        # If only one seed provided, add a related genre
        total_seeds = len(seed_artists) + len(seed_tracks) + len(seed_genres)
        if total_seeds == 1 and not seed_genres:
            # Add a default popular genre
            seed_genres = ['pop']
        
        # Build recommendation parameters
        rec_params = {
            'limit': min(data.get('limit', 20), 100)
        }
        
        # Add optional parameters
        if 'min_popularity' in data:
            rec_params['min_popularity'] = data['min_popularity']
        if 'max_popularity' in data:
            rec_params['max_popularity'] = data['max_popularity']
        if 'target_energy' in data:
            rec_params['target_energy'] = data['target_energy']
        if 'target_valence' in data:
            rec_params['target_valence'] = data['target_valence']
        if 'target_tempo' in data:
            rec_params['target_tempo'] = data['target_tempo']
        
        # Use new recommendation engine (Last.fm primary, Spotify metadata)
        from recommendation_engine import RecommendationEngine
        
        # Get excluded track IDs for regeneration
        exclude_tracks = data.get('exclude_tracks', [])
        
        engine = RecommendationEngine(spotify_token=token)
        hybrid_result = engine.get_recommendations(
            seed_artists=seed_artists[:5] if seed_artists else None,
            seed_tracks=seed_tracks[:5] if seed_tracks else None,
            limit=rec_params.get('limit', 20),
            exclude_track_ids=exclude_tracks
        )
        
        # Extract tracks from recommendation engine result
        recommendations = hybrid_result.get('tracks', [])
        
        # Limit to requested amount
        recommendations = recommendations[:rec_params.get('limit', 20)]
        
        # Save recommendations to history if user is logged in
        saved_count = save_recommendations_to_history(recommendations, seed_artists, seed_genres, seed_tracks)
        
        return jsonify({
            'recommendations': recommendations,
            'count': len(recommendations),
            'seeds': {
                'artists': seed_artists[:5],
                'tracks': seed_tracks[:5],
                'genres': seed_genres[:5]
            },
            'sources': hybrid_result.get('sources', {}),
            'saved_to_history': saved_count if current_user.is_authenticated else None
        }), 200
        
    except Exception as e:
        print(f"Error getting public recommendations: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Failed to get recommendations'}), 500


@app.route('/api/public/recommendations/sessions', methods=['GET'])
def get_recommendation_sessions():
    """
    Get recommendation sessions grouped by recommendation_reason and time.
    Returns unique recommendation sessions that can be selected.
    """
    if not current_user.is_authenticated:
        return jsonify({
            'sessions': [],
            'count': 0,
            'message': 'Login required to view recommendation history'
        }), 200
    
    try:
        from sqlalchemy import func
        
        # Get unique recommendation sessions grouped by reason and date
        sessions_query = db.session.query(
            RecommendationHistory.recommendation_reason,
            func.min(RecommendationHistory.recommended_at).label('first_recommended'),
            func.max(RecommendationHistory.recommended_at).label('last_recommended'),
            func.count(RecommendationHistory.id).label('track_count')
        ).filter(
            RecommendationHistory.user_id == current_user.id
        ).group_by(
            RecommendationHistory.recommendation_reason
        ).order_by(
            func.max(RecommendationHistory.recommended_at).desc()
        ).limit(20)
        
        sessions = []
        for session in sessions_query.all():
            # Parse recommendation_reason to extract display text and seeds
            reason = session.recommendation_reason or "General recommendation"
            display_text = reason
            seeds = {}
            
            try:
                reason_data = json.loads(reason)
                display_text = reason_data.get('display', reason)
                seeds = reason_data.get('seeds', {})
            except (json.JSONDecodeError, TypeError):
                # Old format - try to extract from text
                display_text = reason
                seeds = {}
            
            # Build better display text with artist/track names if available
            final_display = display_text
            if seeds.get('artist_names') or seeds.get('track_names'):
                # Use stored artist/track names if available
                artist_names = seeds.get('artist_names', [])
                track_names = seeds.get('track_names', [])
                genre_names = seeds.get('genres', [])
                parts = []
                if artist_names:
                    parts.extend(artist_names)
                if track_names:
                    parts.extend(track_names)
                if genre_names:
                    parts.extend(genre_names[:2])
                if parts:
                    final_display = f"Based on: {', '.join(parts)}"
            elif seeds.get('artists'):
                # If we have artist IDs but no names, try to fetch them now
                try:
                    token, _ = get_spotify_token()
                    if token:
                        from spotify_api import get_artist_info
                        artist_names = []
                        for aid in seeds.get('artists', [])[:3]:
                            try:
                                artist_info = get_artist_info(token, aid)
                                if artist_info and artist_info.get('name'):
                                    artist_name = artist_info['name']
                                    if artist_name not in artist_names:
                                        artist_names.append(artist_name)
                            except Exception as e:
                                print(f"Error fetching artist name for {aid} in session display: {str(e)}")
                                pass
                        if artist_names:
                            genre_names = seeds.get('genres', [])
                            parts = artist_names[:]
                            if genre_names:
                                parts.extend(genre_names[:2])
                            final_display = f"Based on: {', '.join(parts)}"
                except Exception as e:
                    print(f"Error fetching artist names for session display: {str(e)}")
                    pass
            
            # If we have track IDs but no track names, try to fetch them now
            if not final_display or final_display == display_text:
                if seeds.get('tracks') and not seeds.get('track_names'):
                    try:
                        token, _ = get_spotify_token()
                        if token:
                            track_names = []
                            for tid in seeds.get('tracks', [])[:3]:
                                try:
                                    url = f'https://api.spotify.com/v1/tracks/{tid}'
                                    headers = {'Authorization': f'Bearer {token}'}
                                    response = requests.get(url, headers=headers, timeout=5)
                                    if response.status_code == 200:
                                        track_info = response.json()
                                        track_name = track_info.get('name')
                                        if track_name and track_name not in track_names:
                                            track_names.append(track_name)
                                except Exception as e:
                                    print(f"Error fetching track name for {tid} in session display: {str(e)}")
                                    pass
                            if track_names:
                                genre_names = seeds.get('genres', [])
                                parts = track_names[:]
                                if genre_names:
                                    parts.extend(genre_names[:2])
                                final_display = f"Based on: {', '.join(parts)}"
                    except Exception as e:
                        print(f"Error fetching track names for session display: {str(e)}")
                        pass
            
            sessions.append({
                'reason': reason,  # Store full reason for fetching tracks
                'display': final_display,
                'seeds': seeds,
                'first_recommended': session.first_recommended.isoformat() if session.first_recommended else None,
                'last_recommended': session.last_recommended.isoformat() if session.last_recommended else None,
                'track_count': session.track_count
            })
        
        return jsonify({
            'sessions': sessions,
            'count': len(sessions)
        }), 200
        
    except Exception as e:
        print(f"Error getting recommendation sessions: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Failed to retrieve recommendation sessions'}), 500


@app.route('/api/public/recommendations/sessions', methods=['DELETE'])
@login_required
def delete_recommendation_session():
    """Delete a recommendation session (all tracks with a specific reason)"""
    try:
        data = request.get_json()
        if not data or 'reason' not in data:
            return jsonify({'error': 'reason parameter required'}), 400
        
        reason = data['reason']
        
        # Delete all recommendations with this reason for the current user
        deleted_count = RecommendationHistory.query.filter_by(
            user_id=current_user.id,
            recommendation_reason=reason
        ).delete()
        
        db.session.commit()
        
        return jsonify({
            'message': f'Deleted {deleted_count} recommendations',
            'deleted_count': deleted_count
        }), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting recommendation session: {str(e)}")
        return jsonify({'error': 'Failed to delete recommendation session'}), 500


@app.route('/api/public/recommendations/history', methods=['GET'])
def public_get_recommendation_history():
    """
    Get recommendation history for logged-in users.
    Works for both Spotify and non-Spotify users.
    No login required, but returns empty if not logged in.
    """
    if not current_user.is_authenticated:
        return jsonify({
            'recommendations': [],
            'count': 0,
            'message': 'Login required to view recommendation history'
        }), 200
    
    try:
        # Pagination parameters
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        # Filtering parameters
        rated_only = request.args.get('rated_only', 'false').lower() == 'true'
        saved_only = request.args.get('saved_only', 'false').lower() == 'true'
        dismissed_only = request.args.get('dismissed_only', 'false').lower() == 'true'
        
        # Build query
        query = current_user.recommendations
        
        if rated_only:
            query = query.filter(RecommendationHistory.user_rating.isnot(None))
        if saved_only:
            query = query.filter(RecommendationHistory.is_saved == True)
        if dismissed_only:
            query = query.filter(RecommendationHistory.is_dismissed == True)
        
        # Order by most recent first
        query = query.order_by(RecommendationHistory.recommended_at.desc())
        
        # Paginate
        paginated = query.paginate(page=page, per_page=per_page, error_out=False)
        
        recommendations = [{
            'id': rec.id,
            'track_id': rec.track_id,
            'track_name': rec.track_name,
            'artist_name': rec.artist_name,
            'album_name': rec.album_name,
            'track_image_url': rec.track_image_url,
            'preview_url': rec.preview_url,
            'spotify_url': rec.spotify_url,
            'user_rating': rec.user_rating,
            'is_saved': rec.is_saved,
            'is_dismissed': rec.is_dismissed,
            'recommended_at': rec.recommended_at.isoformat() if rec.recommended_at else None,
            'recommendation_reason': rec.recommendation_reason
        } for rec in paginated.items]
        
        return jsonify({
            'recommendations': recommendations,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': paginated.total,
                'pages': paginated.pages,
                'has_next': paginated.has_next,
                'has_prev': paginated.has_prev
            }
        }), 200
        
    except Exception as e:
        print(f"Error getting recommendation history: {str(e)}")
        return jsonify({'error': 'Failed to retrieve recommendation history'}), 500


def get_spotify_token():
    """
    Get the best available Spotify token (user token if logged in, otherwise app token).
    This helper function reduces code duplication across endpoints.
    
    Returns:
        tuple: (token, using_user_token) or (None, False) if failed
    """
    # Try to use user's Spotify token if logged in
    if current_user.is_authenticated:
        user_token = get_valid_spotify_token(current_user)
        if user_token:
            return user_token, True
    
    # Fall back to app access token
    app_token = get_app_access_token()
    if app_token:
        return app_token, False
    
    return None, False


def extract_track_data(rec):
    """
    Extract track data from recommendation dict, handling both standard and fallback formats.
    
    Args:
        rec: Track dictionary (either standard Spotify API format or fallback format)
    
    Returns:
        dict: Extracted track data with keys: track_id, track_name, artist_name, 
              album_name, track_image_url, spotify_url
    """
    track_id = rec.get('id')
    if not track_id:
        return None
    
    # Extract track name
    track_name = rec.get('name', 'Unknown Track')
    
    # Extract artist name - handle both formats
    artist_name = 'Unknown Artist'
    if 'artists' in rec and isinstance(rec['artists'], list) and len(rec['artists']) > 0:
        if isinstance(rec['artists'][0], dict):
            artist_name = rec['artists'][0].get('name', 'Unknown Artist')
        else:
            artist_name = str(rec['artists'][0])
    elif 'artist' in rec:
        artist_name = rec.get('artist', 'Unknown Artist')
    
    # Extract album name - handle both formats
    album_name = None
    if 'album' in rec:
        album_name = rec['album'].get('name') if isinstance(rec['album'], dict) else rec['album']
    
    # Extract image URL - handle both formats
    track_image_url = None
    if 'image_url' in rec:
        track_image_url = rec.get('image_url')
    elif 'album' in rec and isinstance(rec['album'], dict):
        images = rec['album'].get('images', [])
        if images:
            track_image_url = images[0].get('url')
    
    # Extract Spotify URL - handle both formats
    spotify_url = None
    if 'spotify_url' in rec:
        spotify_url = rec.get('spotify_url')
    elif 'external_urls' in rec and isinstance(rec['external_urls'], dict):
        spotify_url = rec['external_urls'].get('spotify')
    
    # Extract preview URL
    preview_url = rec.get('preview_url')
    
    return {
        'track_id': track_id,
        'track_name': track_name,
        'artist_name': artist_name,
        'album_name': album_name,
        'track_image_url': track_image_url,
        'spotify_url': spotify_url,
        'preview_url': preview_url
    }


def save_recommendations_to_history(recommendations, seed_artists=None, seed_genres=None, seed_tracks=None):
    """
    Save recommendations to user's history if logged in.
    
    Args:
        recommendations: List of track recommendation dictionaries
        seed_artists: List of artist IDs used as seeds
        seed_genres: List of genre names used as seeds
        seed_tracks: List of track IDs used as seeds
    
    Returns:
        int: Number of recommendations saved
    """
    if not current_user.is_authenticated:
        return 0
    
    saved_count = 0
    try:
        # Build recommendation reason with seeds for regeneration
        reason_parts = []
        seed_data = {}
        artist_names = []
        
        # Fetch artist names if we have artist IDs
        if seed_artists:
            token, _ = get_spotify_token()
            if token:
                from spotify_api import get_artist_info
                for aid in seed_artists[:3]:  # Get names for up to 3 artists
                    try:
                        artist_info = get_artist_info(token, aid)
                        if artist_info and artist_info.get('name'):
                            artist_name = artist_info['name']
                            if artist_name not in artist_names:  # Avoid duplicates
                                artist_names.append(artist_name)
                                reason_parts.append(artist_name)
                    except Exception as e:
                        print(f"Error fetching artist name for {aid}: {str(e)}")
                        # If we can't get name, just use ID
                        if f"artist:{aid}" not in reason_parts:
                            reason_parts.append(f"artist:{aid}")
            else:
                # Fallback to IDs if no token
                for aid in seed_artists[:2]:
                    if f"artist:{aid}" not in reason_parts:
                        reason_parts.append(f"artist:{aid}")
            seed_data['artists'] = seed_artists[:5]
            seed_data['artist_names'] = artist_names[:3] if artist_names else []
        
        if seed_genres:
            reason_parts.extend(seed_genres[:2])  # Use genre names directly
            seed_data['genres'] = seed_genres[:5]
        
        # Fetch track names if we have track IDs
        track_names = []
        if seed_tracks:
            token, _ = get_spotify_token()
            if token:
                for tid in seed_tracks[:3]:  # Get names for up to 3 tracks
                    try:
                        url = f'https://api.spotify.com/v1/tracks/{tid}'
                        headers = {'Authorization': f'Bearer {token}'}
                        response = requests.get(url, headers=headers, timeout=5)
                        if response.status_code == 200:
                            track_info = response.json()
                            track_name = track_info.get('name')
                            if track_name and track_name not in track_names:
                                track_names.append(track_name)
                                reason_parts.append(track_name)
                    except Exception as e:
                        print(f"Error fetching track name for {tid}: {str(e)}")
                        # If we can't get name, just use ID
                        if f"track:{tid}" not in reason_parts:
                            reason_parts.append(f"track:{tid}")
            else:
                # Fallback to IDs if no token
                for tid in seed_tracks[:2]:
                    if f"track:{tid}" not in reason_parts:
                        reason_parts.append(f"track:{tid}")
            seed_data['tracks'] = seed_tracks[:5]
            seed_data['track_names'] = track_names[:3] if track_names else []
        
        # Store seeds as JSON in recommendation_reason for regeneration
        display_text = f"Based on: {', '.join(reason_parts)}" if reason_parts else "General recommendation"
        recommendation_reason = json.dumps({
            'display': display_text,
            'seeds': seed_data
        })
        
        for rec in recommendations:
            if not isinstance(rec, dict):
                continue
            
            track_data = extract_track_data(rec)
            if not track_data:
                continue
            
            # Check if already exists
            existing = RecommendationHistory.query.filter_by(
                user_id=current_user.id,
                track_id=track_data['track_id']
            ).first()
            
            if not existing:
                new_rec = RecommendationHistory(
                    user_id=current_user.id,
                    track_id=track_data['track_id'],
                    track_name=track_data['track_name'],
                    artist_name=track_data['artist_name'],
                    album_name=track_data['album_name'],
                    track_image_url=track_data['track_image_url'],
                    preview_url=track_data['preview_url'],
                    spotify_url=track_data['spotify_url'],
                    recommendation_reason=recommendation_reason
                )
                db.session.add(new_rec)
                saved_count += 1
        
        if saved_count > 0:
            db.session.commit()
            print(f"Saved {saved_count} recommendations to history for user {current_user.username}")
    except Exception as e:
        db.session.rollback()
        import traceback
        print(f"Error saving recommendations to history: {str(e)}")
        traceback.print_exc()
    
    return saved_count


def enrich_tracks_with_previews(access_token, tracks, max_enrich=20):
    """
    Enrich tracks with preview URLs if they're missing.
    Only enriches a limited number to avoid too many API calls.
    
    Args:
        access_token: Spotify access token
        tracks: List of track dictionaries
        max_enrich: Maximum number of tracks to enrich (default 20, increased for better coverage)
    
    Returns:
        list: Tracks with preview URLs added where available
    """
    if not tracks or not access_token:
        return tracks
    
    enriched_count = 0
    for track in tracks:
        # Skip if already has preview URL or we've enriched enough
        if track.get('preview_url') or enriched_count >= max_enrich:
            continue
        
        track_id = track.get('id')
        if not track_id:
            continue
        
        try:
            # Fetch full track details to get preview URL
            url = f'https://api.spotify.com/v1/tracks/{track_id}'
            headers = {'Authorization': f'Bearer {access_token}'}
            response = requests.get(url, headers=headers, timeout=5)
            
            if response.status_code == 200:
                track_data = response.json()
                preview_url = track_data.get('preview_url')
                if preview_url:
                    track['preview_url'] = preview_url
                    enriched_count += 1
        except Exception as e:
            # Silently fail - preview URL enrichment is optional
            continue
    
    if enriched_count > 0:
        print(f"Enriched {enriched_count} tracks with preview URLs")
    
    return tracks


def get_app_access_token():
    """
    Get Spotify access token using Client Credentials flow.
    This allows the app to access public Spotify data without user login.
    Tokens are cached for 1 hour to reduce API calls.
    
    Returns:
        str: Access token, or None if failed
    """
    # Check cache first
    from spotify_api import _app_token_cache
    now = datetime.now(timezone.utc)
    
    if (_app_token_cache['token'] and 
        _app_token_cache['expires_at'] and 
        now < _app_token_cache['expires_at'] - timedelta(minutes=5)):  # 5 min buffer
        return _app_token_cache['token']
    
    try:
        token_url = 'https://accounts.spotify.com/api/token'
        
        client_id = app.config.get('SPOTIFY_CLIENT_ID')
        client_secret = app.config.get('SPOTIFY_CLIENT_SECRET')
        
        if not client_id or not client_secret:
            print("Missing Spotify credentials")
            return None
        
        # Request token using client credentials
        auth_response = requests.post(token_url, data={
            'grant_type': 'client_credentials',
            'client_id': client_id,
            'client_secret': client_secret
        }, timeout=10)
        
        auth_response.raise_for_status()
        token_data = auth_response.json()
        
        access_token = token_data['access_token']
        expires_in = token_data.get('expires_in', 3600)  # Default 1 hour
        
        # Cache the token
        _app_token_cache['token'] = access_token
        _app_token_cache['expires_at'] = now + timedelta(seconds=expires_in)
        
        print(f"✅ Cached new app access token (expires in {expires_in}s)")
        return access_token
        
    except requests.HTTPError as e:
        if e.response.status_code == 429:
            retry_after = int(e.response.headers.get('Retry-After', 60))
            print(f"Rate limited when getting app token. Wait {retry_after} seconds.")
        else:
            print(f"Error getting app access token: HTTP {e.response.status_code}")
        return None
    except Exception as e:
        print(f"Error getting app access token: {str(e)}")
        return None


def get_fallback_genres():
    """
    Return a hardcoded list of common Spotify genre seeds.
    Used as fallback when API is unavailable.
    """
    return [
        'acoustic', 'afrobeat', 'alt-rock', 'alternative', 'ambient', 'anime',
        'black-metal', 'bluegrass', 'blues', 'bossanova', 'brazil', 'breakbeat',
        'british', 'cantopop', 'chicago-house', 'children', 'chill', 'classical',
        'club', 'comedy', 'country', 'dance', 'dancehall', 'death-metal', 'deep-house',
        'detroit-techno', 'disco', 'disney', 'drum-and-bass', 'dub', 'dubstep',
        'edm', 'electro', 'electronic', 'emo', 'folk', 'forro', 'french', 'funk',
        'garage', 'german', 'gospel', 'goth', 'grindcore', 'groove', 'grunge',
        'guitar', 'happy', 'hard-rock', 'hardcore', 'hardstyle', 'heavy-metal',
        'hip-hop', 'holidays', 'honky-tonk', 'house', 'idm', 'indian', 'indie',
        'indie-pop', 'industrial', 'iranian', 'j-dance', 'j-idol', 'j-pop', 'j-rock',
        'jazz', 'k-pop', 'kids', 'latin', 'latino', 'malay', 'mandopop', 'metal',
        'metal-misc', 'metalcore', 'minimal-techno', 'movies', 'mpb', 'new-age',
        'new-release', 'opera', 'pagode', 'party', 'philippines-opm', 'piano',
        'pop', 'pop-film', 'post-dubstep', 'power-pop', 'progressive-house',
        'psych-rock', 'punk', 'punk-rock', 'r-n-b', 'rainy-day', 'reggae',
        'reggaeton', 'road-trip', 'rock', 'rock-n-roll', 'rockabilly', 'romance',
        'sad', 'salsa', 'samba', 'sertanejo', 'show-tunes', 'singer-songwriter',
        'ska', 'sleep', 'songwriter', 'soul', 'soundtracks', 'spanish', 'study',
        'summer', 'swedish', 'synth-pop', 'tango', 'techno', 'trance', 'trip-hop',
        'turkish', 'work-out', 'world-music'
    ]


# Error handlers
@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    import traceback
    error_trace = traceback.format_exc()
    print(f"500 Error: {str(error)}")
    print(f"Traceback: {error_trace}")
    flash('An internal server error occurred. Please try again later.', 'danger')
    return redirect(url_for('home')), 500


@app.errorhandler(404)
def not_found_error(error):
    flash('Page not found.', 'warning')
    return redirect(url_for('home')), 404


if __name__ == '__main__':
    init_db()

    port = int(os.environ.get('PORT', 5000))
    debug_env = os.environ.get('FLASK_DEBUG', '').lower()
    debug = debug_env in {'1', 'true', 'yes'}

    app.run(host='0.0.0.0', port=port, debug=debug)
