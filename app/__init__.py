import os
import sys
from flask import Flask, redirect, url_for, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

db = SQLAlchemy()
login_manager = LoginManager()

def get_base_dir():
    """Returns directory of the executable if frozen with PyInstaller, or project root if script."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

def get_bundle_dir():
    """Returns internal temp bundle dir for PyInstaller or app folder for script."""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.abspath(os.path.dirname(__file__))

def create_app(config_override=None):
    bundle_dir = get_bundle_dir()
    base_dir = get_base_dir()

    template_folder = os.path.join(bundle_dir, 'app', 'templates') if getattr(sys, 'frozen', False) else os.path.join(bundle_dir, 'templates')
    static_folder = os.path.join(bundle_dir, 'app', 'static') if getattr(sys, 'frozen', False) else os.path.join(bundle_dir, 'static')

    app = Flask(
        __name__,
        template_folder=template_folder,
        static_folder=static_folder
    )
    
    # Base configuration
    app.config['SECRET_KEY'] = 'bmp-tryout-cbt-secret-key-2026-xyz987'
    from datetime import timedelta
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
    
    # Persistent database in instance/ relative to .exe
    instance_dir = os.path.join(base_dir, 'instance')
    os.makedirs(instance_dir, exist_ok=True)
    db_path = os.path.join(instance_dir, 'tryout.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{db_path.replace(os.sep, '/')}"
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Persistent uploads folder next to .exe or inside static
    persistent_uploads = os.path.join(base_dir, 'uploads')
    app.config['UPLOAD_FOLDER_AVATARS'] = os.path.join(persistent_uploads, 'avatars')
    app.config['UPLOAD_FOLDER_QUESTIONS'] = os.path.join(persistent_uploads, 'questions')
    app.config['UPLOAD_FOLDER_EXPLANATIONS'] = os.path.join(persistent_uploads, 'explanations')
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max
    
    os.makedirs(app.config['UPLOAD_FOLDER_AVATARS'], exist_ok=True)
    os.makedirs(app.config['UPLOAD_FOLDER_QUESTIONS'], exist_ok=True)
    os.makedirs(app.config['UPLOAD_FOLDER_EXPLANATIONS'], exist_ok=True)

    if config_override:
        app.config.update(config_override)

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Silakan login terlebih dahulu untuk mengakses halaman ini.'
    login_manager.login_message_category = 'warning'

    # Route to serve persistent uploaded media files
    @app.route('/static/uploads/<folder>/<filename>')
    def serve_uploaded_media(folder, filename):
        target_dir = os.path.join(persistent_uploads, folder)
        if os.path.exists(os.path.join(target_dir, filename)):
            return send_from_directory(target_dir, filename)
        # Fallback to internal static if any
        bundled_static_upload = os.path.join(static_folder, 'uploads', folder)
        if os.path.exists(os.path.join(bundled_static_upload, filename)):
            return send_from_directory(bundled_static_upload, filename)
        return "File tidak ditemukan", 404

    # Register blueprints
    from app.auth.routes import auth_bp
    from app.supervisor.routes import supervisor_bp
    from app.admin.routes import admin_bp
    from app.exam.routes import exam_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(supervisor_bp, url_prefix='/supervisor')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(exam_bp, url_prefix='/')

    # Create missing tables/columns on existing databases
    from app.schema_upgrade import upgrade_schema
    with app.app_context():
        upgrade_schema()

    # Register custom template filters (GMT+7 / WIB PC Time)
    @app.template_filter('datetime_format')
    def datetime_format(value, format='%d %b %Y %H:%M'):
        if value is None:
            return '-'
        from datetime import datetime, timezone, timedelta
        if isinstance(value, datetime):
            if value.tzinfo is None:
                # Database stores naive UTC timestamp -> treat as UTC
                value = value.replace(tzinfo=timezone.utc)
            # Convert to GMT+7 (WIB / Local PC Timezone)
            local_tz = timezone(timedelta(hours=7))
            local_dt = value.astimezone(local_tz)
            return local_dt.strftime(format)
        return str(value)

    @app.template_filter('format_score')
    def format_score(value):
        if value is None:
            return '-'
        return f"{float(value):.1f}"

    @app.template_filter('format_text')
    def format_text_filter(value):
        if value is None:
            return ""
        text = str(value)
        import re, html
        from markupsafe import Markup

        # 1. Protect math blocks ($...$ and $$...$$) from HTML escaping or markdown replacements
        math_blocks = []
        def save_math(m):
            math_blocks.append(m.group(0))
            return f"___MATH_BLOCK_{len(math_blocks)-1}___"

        text = re.sub(r'\$\$.*?\$\$|\$.*?\$', save_math, text, flags=re.DOTALL)

        # 2. Markdown formatting: **bold** and *italic*
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'(?<!\*)\*([^\*\n]+?)\*(?!\*)', r'<i>\1</i>', text)

        # 3. Sanitize HTML tags: allow only safe tags: b, i, u, strong, em, mark, sub, sup, br
        def sanitize(match):
            tag = match.group(0)
            m = re.match(r'^<\s*(/?)\s*([a-zA-Z0-9]+)', tag)
            if m:
                slash, name = m.group(1), m.group(2).lower()
                if name in {'b', 'strong', 'i', 'em', 'u', 'mark', 'sub', 'sup', 'br'}:
                    return f"<{slash}{name}>" if slash else (f"<{name}>" if name != 'br' else "<br>")
            return html.escape(tag)

        text = re.sub(r'<[^>]+>', sanitize, text)

        # 4. Restore math blocks
        for i, mb in enumerate(math_blocks):
            text = text.replace(f"___MATH_BLOCK_{i}___", mb)

        return Markup(text)

    @login_manager.user_loader
    def load_user(user_id):
        from app.models import User
        return User.query.get(int(user_id))

    # Badge jumlah permintaan Lupa Password di navigasi admin
    @app.context_processor
    def inject_pending_password_resets():
        from flask_login import current_user
        from app.models import PasswordResetRequest
        if current_user.is_authenticated and current_user.is_admin:
            return {'pending_password_resets': PasswordResetRequest.query.filter_by(status='pending').count()}
        return {'pending_password_resets': 0}

    return app
