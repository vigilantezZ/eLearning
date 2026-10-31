import os
import uuid
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.models import User, ActivityLog, PasswordResetRequest

auth_bp = Blueprint('auth', __name__)

# Halaman yang tetap boleh dibuka selama user wajib mengganti password
PASSWORD_CHANGE_ALLOWED_ENDPOINTS = {'auth.change_password', 'auth.logout', 'static', 'serve_uploaded_media'}

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def log_user_activity(user_id, action, details):
    try:
        ip = request.remote_addr
        log = ActivityLog(user_id=user_id, action=action, details=details, ip_address=ip)
        db.session.add(log)
        db.session.commit()
    except Exception:
        db.session.rollback()

def home_url(user):
    if user.is_admin:
        return url_for('admin.dashboard')
    elif user.is_supervisor:
        return url_for('supervisor.dashboard')
    return url_for('exam.catalog')


@auth_bp.before_app_request
def enforce_password_change():
    """User yang passwordnya baru direset admin wajib membuat password sendiri sebelum memakai aplikasi"""
    if not current_user.is_authenticated or not current_user.must_change_password:
        return None
    if request.endpoint is None or request.endpoint in PASSWORD_CHANGE_ALLOWED_ENDPOINTS:
        return None
    return redirect(url_for('auth.change_password'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for('admin.dashboard'))
        elif current_user.is_supervisor:
            return redirect(url_for('supervisor.dashboard'))
        return redirect(url_for('exam.catalog'))

    if request.method == 'POST':
        login_input = request.form.get('login_input', '').strip()
        password = request.form.get('password', '')
        remember = bool(request.form.get('remember'))

        # Allow login via username or email
        user = User.query.filter(
            (User.username == login_input) | (User.email == login_input)
        ).first()

        if user and user.check_password(password):
            from flask import session
            session.permanent = True
            login_user(user, remember=remember)
            log_user_activity(user.id, 'LOGIN', f"User {user.username} logged in successfully.")

            if user.must_change_password:
                flash('Anda masuk dengan password sementara dari admin. Silakan buat password baru terlebih dahulu.', 'warning')
                return redirect(url_for('auth.change_password'))

            flash(f"Selamat datang kembali, {user.full_name}!", 'success')

            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)

            if user.is_admin:
                return redirect(url_for('admin.dashboard'))
            elif user.is_supervisor:
                return redirect(url_for('supervisor.dashboard'))
            return redirect(url_for('exam.catalog'))
        else:
            flash('Username/Email atau password salah. Silakan coba lagi.', 'danger')

    return render_template('auth/login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('exam.catalog'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        full_name = request.form.get('full_name', '').strip()
        school = request.form.get('school', '').strip()
        grade = request.form.get('grade', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        # Validations
        if not username or not email or not password or not full_name:
            flash('Mohon lengkapi semua bidang wajib.', 'warning')
            return render_template('auth/register.html')

        if password != confirm_password:
            flash('Konfirmasi password tidak cocok.', 'danger')
            return render_template('auth/register.html')

        if len(password) < 6:
            flash('Password minimal harus 6 karakter.', 'danger')
            return render_template('auth/register.html')

        if User.query.filter_by(username=username).first():
            flash('Username sudah digunakan. Silakan pilih username lain.', 'danger')
            return render_template('auth/register.html')

        if User.query.filter_by(email=email).first():
            flash('Email sudah terdaftar. Silakan gunakan email lain atau login.', 'danger')
            return render_template('auth/register.html')

        # Handle optional photo upload
        photo_filename = None
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename != '' and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                photo_filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER_AVATARS'], photo_filename))

        new_user = User(
            username=username,
            email=email,
            phone=phone,
            full_name=full_name,
            school=school,
            grade=grade,
            photo_filename=photo_filename,
            role='peserta'
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        log_user_activity(new_user.id, 'REGISTER', f"New participant registered: {username}")
        flash('Pendaftaran akun berhasil! Silakan login untuk memulai tryout.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html')


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('auth.profile'))

    if request.method == 'POST':
        login_input = request.form.get('login_input', '').strip().lower()
        contact_phone = request.form.get('contact_phone', '').strip()[:20]
        note = request.form.get('note', '').strip()[:500]

        if not login_input:
            flash('Masukkan username atau email akun Anda.', 'warning')
            return render_template('auth/forgot_password.html')

        user = User.query.filter(
            (db.func.lower(User.username) == login_input) | (db.func.lower(User.email) == login_input)
        ).first()

        if user:
            # Satu permintaan aktif per user: permintaan ulang hanya memperbarui kontak & catatan
            pending = PasswordResetRequest.query.filter_by(user_id=user.id, status='pending').first()
            if pending:
                pending.contact_phone = contact_phone or pending.contact_phone
                pending.note = note or pending.note
            else:
                db.session.add(PasswordResetRequest(
                    user_id=user.id,
                    contact_phone=contact_phone or None,
                    note=note or None,
                    ip_address=request.remote_addr
                ))
            db.session.commit()
            log_user_activity(user.id, 'FORGOT_PASSWORD_REQUEST', f"Password reset requested for {user.username}.")

        # Pesan dibuat sama untuk akun ada / tidak ada agar username terdaftar tidak bisa ditebak
        flash('Permintaan reset password sudah diteruskan ke admin (jika akun ditemukan). '
              'Admin akan menghubungi Anda melalui nomor HP yang terdaftar di akun untuk memberikan password sementara.', 'info')
        return redirect(url_for('auth.login'))

    return render_template('auth/forgot_password.html')


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if not current_user.must_change_password:
        return redirect(url_for('auth.profile'))

    if request.method == 'POST':
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if len(new_password) < 6:
            flash('Password baru minimal 6 karakter.', 'danger')
            return render_template('auth/change_password.html')
        if new_password != confirm_password:
            flash('Konfirmasi password baru tidak cocok.', 'danger')
            return render_template('auth/change_password.html')
        if current_user.check_password(new_password):
            flash('Password baru tidak boleh sama dengan password sementara dari admin.', 'danger')
            return render_template('auth/change_password.html')

        current_user.set_password(new_password)
        current_user.must_change_password = False
        db.session.commit()
        log_user_activity(current_user.id, 'PASSWORD_CHANGED', f"User {current_user.username} set a new password after admin reset.")
        flash('Password baru berhasil disimpan. Selamat datang kembali!', 'success')
        return redirect(home_url(current_user))

    return render_template('auth/change_password.html')


@auth_bp.route('/logout')
@login_required
def logout():
    reason = request.args.get('reason')
    if reason == 'timeout':
        log_user_activity(current_user.id, 'TIMEOUT_LOGOUT', f"User {current_user.username} auto-logged out due to inactivity.")
        logout_user()
        flash('Sesi Anda telah berakhir otomatis karena tidak ada aktivitas selama 30 menit. Silakan login kembali.', 'warning')
    else:
        log_user_activity(current_user.id, 'LOGOUT', f"User {current_user.username} logged out.")
        logout_user()
        flash('Anda telah berhasil keluar.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        phone = request.form.get('phone', '').strip()
        school = request.form.get('school', '').strip()
        grade = request.form.get('grade', '').strip()
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not full_name:
            flash('Nama lengkap tidak boleh kosong.', 'warning')
            return render_template('auth/profile.html')

        current_user.full_name = full_name
        current_user.phone = phone
        current_user.school = school
        current_user.grade = grade

        # Optional change password
        if new_password:
            if new_password != confirm_password:
                flash('Konfirmasi password baru tidak cocok.', 'danger')
                return render_template('auth/profile.html')
            if len(new_password) < 6:
                flash('Password baru minimal 6 karakter.', 'danger')
                return render_template('auth/profile.html')
            current_user.set_password(new_password)
            flash('Password berhasil diperbarui.', 'info')

        # Optional photo update
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename != '' and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                photo_filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER_AVATARS'], photo_filename))
                current_user.photo_filename = photo_filename

        db.session.commit()
        log_user_activity(current_user.id, 'UPDATE_PROFILE', f"User {current_user.username} updated their profile.")
        flash('Profil Anda berhasil diperbarui!', 'success')
        return redirect(url_for('auth.profile'))

    return render_template('auth/profile.html')
