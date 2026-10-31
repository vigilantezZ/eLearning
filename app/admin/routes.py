import os
import uuid
import secrets
from datetime import datetime, timezone, timedelta
from functools import wraps
from urllib.parse import quote
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify, make_response
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.models import (
    User, TestGroup, Subtest, Topic, Question, 
    TryoutPackage, TryoutSubtest, TryoutQuestion, 
    ExamSession, ExamAnswer, SubtestScore, ActivityLog, PasswordResetRequest, normalize_phone
)
from app.irt_engine import calculate_irt_for_package, assign_national_ranks
from app.subtest_flow import sync_expired_attempts

admin_bp = Blueprint('admin', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
WIB = timezone(timedelta(hours=7))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def parse_wib_datetime(value):
    """Input datetime-local form (WIB) -> naive UTC, sesuai format penyimpanan database"""
    if not value:
        return None
    local_dt = datetime.strptime(value, '%Y-%m-%dT%H:%M').replace(tzinfo=WIB)
    return local_dt.astimezone(timezone.utc).replace(tzinfo=None)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login', next=request.url))
        if not current_user.is_admin:
            flash('Akses ditolak: Area ini memerlukan hak akses Administrator.', 'danger')
            return redirect(url_for('exam.catalog'))
        return f(*args, **kwargs)
    return decorated_function

def supervisor_or_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login', next=request.url))
        if not (current_user.is_admin or current_user.is_supervisor):
            flash('Akses ditolak: Area ini memerlukan hak akses Supervisor atau Administrator.', 'danger')
            return redirect(url_for('exam.catalog'))
        return f(*args, **kwargs)
    return decorated_function


@admin_bp.route('/')
@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    total_users = User.query.count()
    total_peserta = User.query.filter_by(role='peserta').count()
    total_supervisor = User.query.filter_by(role='supervisor').count()
    total_packages = TryoutPackage.query.count()
    total_questions = Question.query.count()
    total_completed_exams = ExamSession.query.filter_by(status='completed').count()
    total_active_exams = ExamSession.query.filter_by(status='in_progress').count()

    recent_activities = ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(10).all()
    packages = TryoutPackage.query.order_by(TryoutPackage.created_at.desc()).limit(5).all()

    return render_template(
        'admin/dashboard.html',
        total_users=total_users,
        total_peserta=total_peserta,
        total_supervisor=total_supervisor,
        total_packages=total_packages,
        total_questions=total_questions,
        total_completed_exams=total_completed_exams,
        total_active_exams=total_active_exams,
        recent_activities=recent_activities,
        packages=packages
    )


# ==========================================
# User Management (CRUD)
# ==========================================

@admin_bp.route('/users')
@login_required
@admin_required
def users():
    role_filter = request.args.get('role', '')
    search = request.args.get('search', '').strip()

    query = User.query
    if role_filter:
        query = query.filter_by(role=role_filter)
    if search:
        query = query.filter(
            (User.username.ilike(f"%{search}%")) |
            (User.email.ilike(f"%{search}%")) |
            (User.full_name.ilike(f"%{search}%")) |
            (User.school.ilike(f"%{search}%"))
        )

    users_list = query.order_by(User.created_at.desc()).all()
    return render_template(
        'admin/users.html',
        users=users_list,
        current_role=role_filter,
        search_query=search
    )


@admin_bp.route('/users/new', methods=['GET', 'POST'])
@login_required
@admin_required
def user_new():
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        email = request.form.get('email', '').strip().lower()
        full_name = request.form.get('full_name', '').strip()
        phone = request.form.get('phone', '').strip()
        school = request.form.get('school', '').strip()
        grade = request.form.get('grade', '').strip()
        role = request.form.get('role', 'peserta')
        password = request.form.get('password', '')

        if not username or not email or not full_name or not password:
            flash('Username, Email, Nama Lengkap, dan Password wajib diisi.', 'danger')
            return render_template('admin/user_form.html', user=None)

        if User.query.filter_by(username=username).first():
            flash('Username sudah digunakan.', 'danger')
            return render_template('admin/user_form.html', user=None)

        if User.query.filter_by(email=email).first():
            flash('Email sudah terdaftar.', 'danger')
            return render_template('admin/user_form.html', user=None)

        # Handle avatar
        photo_filename = None
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename != '' and allowed_file(file.filename):
                photo_filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER_AVATARS'], photo_filename))

        new_user = User(
            username=username,
            email=email,
            full_name=full_name,
            phone=phone,
            school=school,
            grade=grade,
            role=role,
            photo_filename=photo_filename
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        flash(f"Pengguna '{full_name}' dengan peran '{role}' berhasil dibuat!", 'success')
        return redirect(url_for('admin.users'))

    return render_template('admin/user_form.html', user=None)


@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def user_edit(user_id):
    target_user = User.query.get_or_404(user_id)

    if request.method == 'POST':
        target_user.full_name = request.form.get('full_name', '').strip()
        target_user.phone = request.form.get('phone', '').strip()
        target_user.school = request.form.get('school', '').strip()
        target_user.grade = request.form.get('grade', '').strip()
        old_role = target_user.role
        target_user.role = request.form.get('role', target_user.role)

        password = request.form.get('password', '')
        if password:
            if len(password) < 6:
                flash('Password baru minimal 6 karakter.', 'danger')
                return render_template('admin/user_form.html', user=target_user)
            target_user.set_password(password)
            flash('Password pengguna berhasil direset.', 'info')

        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename != '' and allowed_file(file.filename):
                photo_filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER_AVATARS'], photo_filename))
                target_user.photo_filename = photo_filename

        # Peringkat hanya untuk akun peserta: susun ulang paket yang pernah dikerjakan bila role berubah
        if target_user.role != old_role:
            for package_id in {s.tryout_package_id for s in target_user.exam_sessions.filter_by(status='completed')}:
                assign_national_ranks(package_id)

        db.session.commit()
        flash(f"Data pengguna '{target_user.username}' berhasil diperbarui.", 'success')
        return redirect(url_for('admin.users'))

    return render_template('admin/user_form.html', user=target_user)


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def user_delete(user_id):
    if user_id == current_user.id:
        flash('Anda tidak dapat menghapus akun Anda sendiri.', 'danger')
        return redirect(url_for('admin.users'))

    target_user = User.query.get_or_404(user_id)
    username = target_user.username
    ranked_package_ids = {
        s.tryout_package_id for s in target_user.exam_sessions.filter(ExamSession.national_rank.isnot(None))
    }
    db.session.delete(target_user)
    db.session.flush()
    # Peringkat peserta lain dirapatkan agar tidak ada nomor yang bolong
    for package_id in ranked_package_ids:
        assign_national_ranks(package_id)
    db.session.commit()
    flash(f"Pengguna '{username}' berhasil dihapus.", 'info')
    return redirect(url_for('admin.users'))


# ==========================================
# Lupa Password (Permintaan Reset oleh User)
# ==========================================

# Tanpa karakter yang mudah tertukar saat dibacakan/diketik (0/O, 1/l/I)
TEMP_PASSWORD_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789'

def generate_temp_password(length=8):
    return ''.join(secrets.choice(TEMP_PASSWORD_ALPHABET) for _ in range(length))


@admin_bp.route('/password-resets')
@login_required
@admin_required
def password_resets():
    pending_requests = PasswordResetRequest.query.filter_by(status='pending').order_by(PasswordResetRequest.created_at.asc()).all()
    processed_requests = PasswordResetRequest.query.filter(
        PasswordResetRequest.status != 'pending'
    ).order_by(PasswordResetRequest.resolved_at.desc()).limit(20).all()

    return render_template(
        'admin/password_resets.html',
        pending_requests=pending_requests,
        processed_requests=processed_requests
    )


@admin_bp.route('/password-resets/<int:request_id>/approve', methods=['POST'])
@login_required
@admin_required
def password_reset_approve(request_id):
    reset_req = PasswordResetRequest.query.get_or_404(request_id)
    if reset_req.status != 'pending':
        flash('Permintaan ini sudah diproses sebelumnya.', 'info')
        return redirect(url_for('admin.password_resets'))

    target_user = reset_req.user
    temp_password = generate_temp_password()
    target_user.set_password(temp_password)
    target_user.must_change_password = True

    reset_req.status = 'resolved'
    reset_req.resolved_at = datetime.now(timezone.utc)
    reset_req.resolved_by_id = current_user.id

    db.session.add(ActivityLog(
        user_id=current_user.id,
        action='PASSWORD_RESET',
        details=f"Admin {current_user.username} reset the password of {target_user.username} (forgot-password request #{reset_req.id})",
        ip_address=request.remote_addr
    ))
    db.session.commit()

    wa_number = normalize_phone(target_user.phone)
    wa_url = None
    if wa_number:
        wa_message = (
            f"Halo {target_user.full_name}, password sementara akun BMP Tryout Anda (username: {target_user.username}) "
            f"adalah: {temp_password}\nSilakan login lalu buat password baru."
        )
        wa_url = f"https://wa.me/{wa_number}?text={quote(wa_message)}"

    # Password sementara hanya ditampilkan sekali dan tidak boleh tersimpan di cache browser
    response = make_response(render_template(
        'admin/password_reset_done.html',
        target_user=target_user,
        temp_password=temp_password,
        wa_url=wa_url
    ))
    response.headers['Cache-Control'] = 'no-store'
    return response


@admin_bp.route('/password-resets/<int:request_id>/reject', methods=['POST'])
@login_required
@admin_required
def password_reset_reject(request_id):
    reset_req = PasswordResetRequest.query.get_or_404(request_id)
    if reset_req.status != 'pending':
        flash('Permintaan ini sudah diproses sebelumnya.', 'info')
        return redirect(url_for('admin.password_resets'))

    reset_req.status = 'rejected'
    reset_req.resolved_at = datetime.now(timezone.utc)
    reset_req.resolved_by_id = current_user.id
    db.session.add(ActivityLog(
        user_id=current_user.id,
        action='PASSWORD_RESET_REJECTED',
        details=f"Admin {current_user.username} rejected forgot-password request #{reset_req.id} for {reset_req.user.username}",
        ip_address=request.remote_addr
    ))
    db.session.commit()

    flash(f"Permintaan reset password untuk '{reset_req.user.username}' ditolak.", 'info')
    return redirect(url_for('admin.password_resets'))


# ==========================================
# Tryout Package Management (CRUD)
# ==========================================

@admin_bp.route('/packages')
@login_required
@supervisor_or_admin_required
def packages():
    packages_list = TryoutPackage.query.order_by(TryoutPackage.created_at.desc()).all()
    return render_template('admin/packages.html', packages=packages_list)


@admin_bp.route('/packages/new', methods=['GET', 'POST'])
@login_required
@supervisor_or_admin_required
def package_new():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        is_published = bool(request.form.get('is_published'))
        free_subtest_order = request.form.get('subtest_order_mode', 'free') != 'sequential'

        start_time = parse_wib_datetime(request.form.get('start_time'))
        end_time = parse_wib_datetime(request.form.get('end_time'))

        if not title:
            flash('Judul Paket Tryout wajib diisi.', 'danger')
            return redirect(request.url)

        pkg = TryoutPackage(
            title=title,
            description=description,
            start_time=start_time,
            end_time=end_time,
            is_published=is_published,
            free_subtest_order=free_subtest_order,
            created_by_id=current_user.id
        )
        db.session.add(pkg)
        db.session.flush()  # to get pkg.id

        # Subtests selection and duration configuration
        subtest_ids = request.form.getlist('subtest_ids')
        for order_idx, sub_id in enumerate(subtest_ids, start=1):
            sub_id = int(sub_id)
            duration = int(request.form.get(f'duration_{sub_id}', 25))
            ts = TryoutSubtest(
                tryout_package_id=pkg.id,
                subtest_id=sub_id,
                duration_minutes=duration,
                order_num=order_idx
            )
            db.session.add(ts)

        # Question IDs selection
        question_ids = request.form.getlist('question_ids')
        for q_order, q_id in enumerate(question_ids, start=1):
            tq = TryoutQuestion(
                tryout_package_id=pkg.id,
                question_id=int(q_id),
                order_num=q_order
            )
            db.session.add(tq)

        db.session.commit()
        flash(f"Paket Tryout '{title}' berhasil dibuat dengan {len(question_ids)} butir soal!", 'success')
        return redirect(url_for('admin.packages'))

    all_subtests = Subtest.query.order_by(Subtest.order_num).all()
    all_questions = Question.query.order_by(Question.subtest_id, Question.id).all()
    return render_template(
        'admin/package_form.html',
        package=None,
        subtests=all_subtests,
        questions=all_questions,
        selected_subtest_ids=[],
        selected_question_ids=[]
    )


@admin_bp.route('/packages/<int:package_id>/edit', methods=['GET', 'POST'])
@login_required
@supervisor_or_admin_required
def package_edit(package_id):
    pkg = TryoutPackage.query.get_or_404(package_id)

    if request.method == 'POST':
        pkg.title = request.form.get('title', '').strip()
        pkg.description = request.form.get('description', '').strip()
        pkg.is_published = bool(request.form.get('is_published'))
        pkg.free_subtest_order = request.form.get('subtest_order_mode', 'free') != 'sequential'

        pkg.start_time = parse_wib_datetime(request.form.get('start_time'))
        pkg.end_time = parse_wib_datetime(request.form.get('end_time'))

        # Re-sync subtests and durations
        TryoutSubtest.query.filter_by(tryout_package_id=pkg.id).delete()
        subtest_ids = request.form.getlist('subtest_ids')
        for order_idx, sub_id in enumerate(subtest_ids, start=1):
            sub_id = int(sub_id)
            duration = int(request.form.get(f'duration_{sub_id}', 25))
            ts = TryoutSubtest(
                tryout_package_id=pkg.id,
                subtest_id=sub_id,
                duration_minutes=duration,
                order_num=order_idx
            )
            db.session.add(ts)

        # Re-sync questions
        TryoutQuestion.query.filter_by(tryout_package_id=pkg.id).delete()
        question_ids = request.form.getlist('question_ids')
        for q_order, q_id in enumerate(question_ids, start=1):
            tq = TryoutQuestion(
                tryout_package_id=pkg.id,
                question_id=int(q_id),
                order_num=q_order
            )
            db.session.add(tq)

        db.session.commit()
        flash(f"Paket Tryout '{pkg.title}' berhasil diperbarui!", 'success')
        return redirect(url_for('admin.packages'))

    all_subtests = Subtest.query.order_by(Subtest.order_num).all()
    all_questions = Question.query.order_by(Question.subtest_id, Question.id).all()
    selected_subtest_ids = [ts.subtest_id for ts in pkg.package_subtests]
    selected_question_ids = [tq.question_id for tq in pkg.package_questions]
    subtest_durations = {ts.subtest_id: ts.duration_minutes for ts in pkg.package_subtests}

    return render_template(
        'admin/package_form.html',
        package=pkg,
        subtests=all_subtests,
        questions=all_questions,
        selected_subtest_ids=selected_subtest_ids,
        selected_question_ids=selected_question_ids,
        subtest_durations=subtest_durations
    )


@admin_bp.route('/packages/<int:package_id>/delete', methods=['POST'])
@login_required
@supervisor_or_admin_required
def package_delete(package_id):
    pkg = TryoutPackage.query.get_or_404(package_id)
    title = pkg.title
    db.session.delete(pkg)
    db.session.commit()
    flash(f"Paket Tryout '{title}' berhasil dihapus.", 'info')
    return redirect(url_for('admin.packages'))


# ==========================================
# Item Response Theory (IRT) Controller
# ==========================================

@admin_bp.route('/irt')
@login_required
@supervisor_or_admin_required
def irt_calculator():
    packages = TryoutPackage.query.order_by(TryoutPackage.created_at.desc()).all()
    selected_package_id = request.args.get('package_id', type=int)
    
    if not selected_package_id and packages:
        selected_package_id = packages[0].id

    selected_package = TryoutPackage.query.get(selected_package_id) if selected_package_id else None
    completed_sessions = []
    package_questions = []
    in_progress_count = 0

    if selected_package:
        # Peserta berperingkat di atas, peserta tidak lengkap (tanpa peringkat) di bawah
        completed_sessions = ExamSession.query.filter_by(
            tryout_package_id=selected_package.id,
            status='completed'
        ).order_by(ExamSession.national_rank.is_(None), ExamSession.national_rank.asc()).all()
        package_questions = [tq.question for tq in selected_package.package_questions if tq.question is not None]
        in_progress_count = selected_package.exam_sessions.filter_by(status='in_progress').count()

    return render_template(
        'admin/irt_calculator.html',
        packages=packages,
        selected_package=selected_package,
        completed_sessions=completed_sessions,
        package_questions=package_questions,
        in_progress_count=in_progress_count
    )


@admin_bp.route('/irt/calculate/<int:package_id>', methods=['POST'])
@login_required
@supervisor_or_admin_required
def run_irt_calculation(package_id):
    success, message = calculate_irt_for_package(package_id)
    if success:
        flash(message, 'success')
        # Log activity
        log = ActivityLog(
            user_id=current_user.id,
            action='CALC_IRT',
            details=f"User #{current_user.id} ({current_user.role}) calculated IRT for Package #{package_id}",
            ip_address=request.remote_addr
        )
        db.session.add(log)
        db.session.commit()
    else:
        flash(message, 'warning')
    return redirect(url_for('admin.irt_calculator', package_id=package_id))


# ==========================================
# Live Proctoring & Activity Logs
# ==========================================

@admin_bp.route('/live-monitor')
@login_required
@supervisor_or_admin_required
def live_monitor():
    active_sessions = ExamSession.query.filter_by(status='in_progress').order_by(ExamSession.start_time.desc()).all()
    # Kunci subtes yang timernya sudah habis agar kolom "Subtes Aktif" akurat
    if any([sync_expired_attempts(s) for s in active_sessions]):
        db.session.commit()
    completed_sessions = ExamSession.query.filter_by(status='completed').order_by(ExamSession.submitted_at.desc()).limit(15).all()
    recent_logs = ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(30).all()

    return render_template(
        'admin/live_monitor.html',
        active_sessions=active_sessions,
        completed_sessions=completed_sessions,
        recent_logs=recent_logs
    )


# ==========================================
# Storage Protection & Data Housekeeping
# ==========================================

def get_dir_size_bytes(path):
    total = 0
    if os.path.exists(path):
        for root, dirs, files in os.walk(path):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
    return total

def format_bytes(size):
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.2f} KB"
    else:
        return f"{size / (1024 * 1024):.2f} MB"

@admin_bp.route('/storage')
@login_required
@admin_required
def storage_manager():
    from datetime import datetime, timezone, timedelta
    now_utc = datetime.now(timezone.utc)
    
    # 1. Database file size
    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    db_file = None
    if 'sqlite:///' in db_uri:
        db_file = db_uri.split('sqlite:///')[-1]
    elif 'sqlite://' in db_uri:
        db_file = db_uri.split('sqlite://')[-1]
        
    db_size_bytes = 0
    if db_file and os.path.exists(db_file):
        try:
            db_size_bytes = os.path.getsize(db_file)
        except OSError:
            db_size_bytes = 0
    db_size_formatted = format_bytes(db_size_bytes)
    
    # 2. Uploads folder size
    upload_avatars = current_app.config.get('UPLOAD_FOLDER_AVATARS', '')
    upload_questions = current_app.config.get('UPLOAD_FOLDER_QUESTIONS', '')
    upload_explanations = current_app.config.get('UPLOAD_FOLDER_EXPLANATIONS', '')
    
    avatars_size = get_dir_size_bytes(upload_avatars)
    questions_size = get_dir_size_bytes(upload_questions)
    explanations_size = get_dir_size_bytes(upload_explanations)
    total_uploads_bytes = avatars_size + questions_size + explanations_size
    total_uploads_formatted = format_bytes(total_uploads_bytes)
    
    # 3. Database row counts
    total_logs = ActivityLog.query.count()
    logs_older_30d = ActivityLog.query.filter(ActivityLog.created_at < (now_utc - timedelta(days=30))).count()
    logs_older_7d = ActivityLog.query.filter(ActivityLog.created_at < (now_utc - timedelta(days=7))).count()
    
    total_sessions = ExamSession.query.count()
    completed_sessions = ExamSession.query.filter_by(status='completed').count()
    abandoned_sessions = ExamSession.query.filter(
        ExamSession.status == 'in_progress',
        ExamSession.start_time < (now_utc - timedelta(days=3))
    ).count()
    
    total_answers = ExamAnswer.query.count()
    total_scores = SubtestScore.query.count()
    
    # 4. Orphaned files count
    active_avatars = set(u.photo_filename for u in User.query.filter(User.photo_filename.isnot(None)).all())
    active_q_images = set(q.question_image for q in Question.query.filter(Question.question_image.isnot(None)).all())
    active_exp_images = set(q.explanation_image for q in Question.query.filter(Question.explanation_image.isnot(None)).all())
    
    orphan_files_count = 0
    for folder, active_set in [
        (upload_avatars, active_avatars),
        (upload_questions, active_q_images),
        (upload_explanations, active_exp_images)
    ]:
        if os.path.exists(folder):
            for fname in os.listdir(folder):
                if os.path.isfile(os.path.join(folder, fname)) and fname not in active_set and fname != '.gitkeep':
                    orphan_files_count += 1

    packages = TryoutPackage.query.order_by(TryoutPackage.created_at.desc()).all()

    return render_template(
        'admin/storage.html',
        db_size_formatted=db_size_formatted,
        total_uploads_formatted=total_uploads_formatted,
        avatars_size_formatted=format_bytes(avatars_size),
        questions_size_formatted=format_bytes(questions_size),
        explanations_size_formatted=format_bytes(explanations_size),
        total_logs=total_logs,
        logs_older_30d=logs_older_30d,
        logs_older_7d=logs_older_7d,
        total_sessions=total_sessions,
        completed_sessions=completed_sessions,
        abandoned_sessions=abandoned_sessions,
        total_answers=total_answers,
        total_scores=total_scores,
        orphan_files_count=orphan_files_count,
        packages=packages
    )


@admin_bp.route('/storage/cleanup-logs', methods=['POST'])
@login_required
@admin_required
def cleanup_logs():
    from datetime import datetime, timezone, timedelta
    days = request.form.get('days', '30')
    now_utc = datetime.now(timezone.utc)
    
    deleted_count = 0
    if days == 'all_except_100':
        # Keep latest 100 logs
        keep_ids = [l.id for l in ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(100).all()]
        if keep_ids:
            deleted_count = ActivityLog.query.filter(~ActivityLog.id.in_(keep_ids)).delete(synchronize_session=False)
        else:
            deleted_count = ActivityLog.query.delete(synchronize_session=False)
    else:
        days_int = int(days)
        cutoff = now_utc - timedelta(days=days_int)
        deleted_count = ActivityLog.query.filter(ActivityLog.created_at < cutoff).delete(synchronize_session=False)
    
    db.session.commit()
    
    # Record new activity log
    log = ActivityLog(
        user_id=current_user.id,
        action='STORAGE_CLEANUP',
        details=f"Admin cleaned up {deleted_count} old activity log records (Option: {days} days).",
        ip_address=request.remote_addr
    )
    db.session.add(log)
    db.session.commit()
    
    flash(f"Berhasil membersihkan {deleted_count} rekaman log aktivitas lama.", 'success')
    return redirect(url_for('admin.storage_manager'))


@admin_bp.route('/storage/cleanup-sessions', methods=['POST'])
@login_required
@admin_required
def cleanup_sessions():
    from datetime import datetime, timezone, timedelta
    target = request.form.get('target', 'abandoned')
    now_utc = datetime.now(timezone.utc)
    
    deleted_sessions = 0
    deleted_answers = 0
    
    if target == 'abandoned':
        # In-progress sessions older than 3 days
        cutoff = now_utc - timedelta(days=3)
        sessions_to_del = ExamSession.query.filter(
            ExamSession.status == 'in_progress',
            ExamSession.start_time < cutoff
        ).all()
    elif target == 'package':
        package_id = request.form.get('package_id', type=int)
        if not package_id:
            flash("Silakan pilih paket tryout yang ingin dibersihkan.", "warning")
            return redirect(url_for('admin.storage_manager'))
        sessions_to_del = ExamSession.query.filter_by(package_id=package_id).all()
    else:
        # All completed older than 90 days
        cutoff = now_utc - timedelta(days=90)
        sessions_to_del = ExamSession.query.filter(
            ExamSession.status == 'completed',
            ExamSession.submitted_at < cutoff
        ).all()
        
    for s in sessions_to_del:
        deleted_answers += ExamAnswer.query.filter_by(session_id=s.id).delete()
        SubtestScore.query.filter_by(session_id=s.id).delete()
        db.session.delete(s)
        deleted_sessions += 1
        
    db.session.commit()
    
    log = ActivityLog(
        user_id=current_user.id,
        action='STORAGE_CLEANUP',
        details=f"Admin cleaned up {deleted_sessions} sessions and {deleted_answers} answer rows (Target: {target}).",
        ip_address=request.remote_addr
    )
    db.session.add(log)
    db.session.commit()
    
    flash(f"Berhasil menghapus {deleted_sessions} sesi ujian dan {deleted_answers} rincian jawaban pengerjaan.", 'success')
    return redirect(url_for('admin.storage_manager'))


@admin_bp.route('/storage/cleanup-orphaned-files', methods=['POST'])
@login_required
@admin_required
def cleanup_orphaned_files():
    upload_avatars = current_app.config.get('UPLOAD_FOLDER_AVATARS', '')
    upload_questions = current_app.config.get('UPLOAD_FOLDER_QUESTIONS', '')
    upload_explanations = current_app.config.get('UPLOAD_FOLDER_EXPLANATIONS', '')
    
    active_avatars = set(u.photo_filename for u in User.query.filter(User.photo_filename.isnot(None)).all())
    active_q_images = set(q.question_image for q in Question.query.filter(Question.question_image.isnot(None)).all())
    active_exp_images = set(q.explanation_image for q in Question.query.filter(Question.explanation_image.isnot(None)).all())
    
    deleted_files = 0
    reclaimed_bytes = 0
    
    for folder, active_set in [
        (upload_avatars, active_avatars),
        (upload_questions, active_q_images),
        (upload_explanations, active_exp_images)
    ]:
        if os.path.exists(folder):
            for fname in os.listdir(folder):
                fp = os.path.join(folder, fname)
                if os.path.isfile(fp) and fname not in active_set and fname != '.gitkeep':
                    try:
                        reclaimed_bytes += os.path.getsize(fp)
                        os.remove(fp)
                        deleted_files += 1
                    except OSError:
                        pass
                        
    log = ActivityLog(
        user_id=current_user.id,
        action='STORAGE_CLEANUP',
        details=f"Admin cleaned up {deleted_files} orphaned upload files ({format_bytes(reclaimed_bytes)} reclaimed).",
        ip_address=request.remote_addr
    )
    db.session.add(log)
    db.session.commit()
    
    flash(f"Berhasil menghapus {deleted_files} file gambar tidak terpakai (Hemat ruang: {format_bytes(reclaimed_bytes)}).", 'success')
    return redirect(url_for('admin.storage_manager'))


@admin_bp.route('/storage/vacuum-db', methods=['POST'])
@login_required
@admin_required
def vacuum_db():
    try:
        db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
        db_file = db_uri.replace('sqlite:///', '')
        size_before = os.path.getsize(db_file) if os.path.exists(db_file) else 0
        
        # SQLite vacuum optimization
        db.session.close()
        db.engine.raw_connection().cursor().execute("VACUUM")
        
        size_after = os.path.getsize(db_file) if os.path.exists(db_file) else 0
        saved = max(0, size_before - size_after)
        
        flash(f"Optimalisasi database (VACUUM) berhasil! Ukuran database saat ini: {format_bytes(size_after)} (Ruang dihemat: {format_bytes(saved)}).", 'success')
    except Exception as e:
        flash(f"Gagal melakukan optimalisasi database: {str(e)}", 'danger')
        
    return redirect(url_for('admin.storage_manager'))
