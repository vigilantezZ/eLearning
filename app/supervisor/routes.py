import os
import uuid
import json
from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.models import (
    User, TestGroup, Subtest, Topic, Question, 
    TryoutPackage, ExamSession, ExamAnswer, SubtestScore, ActivityLog
)

from PIL import Image

supervisor_bp = Blueprint('supervisor', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_optimized_image(file, target_folder, prefix='img', max_dimension=1600):
    """
    Saves and optimizes uploaded images (auto-resizes huge images, strips metadata, optimizes compression)
    to prevent lag, speed up uploads, and save disk space.
    """
    try:
        ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'png'
        filename = f"{prefix}_{uuid.uuid4().hex}.{ext}"
        target_path = os.path.join(target_folder, filename)
        
        # Open with PIL
        img = Image.open(file.stream)
        
        # Auto convert RGBA to RGB if saving as JPEG
        if ext in ['jpg', 'jpeg'] and img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
            
        # Resize if width or height exceeds max_dimension
        if img.width > max_dimension or img.height > max_dimension:
            img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
            
        # Save optimized
        if ext in ['jpg', 'jpeg']:
            img.save(target_path, 'JPEG', quality=85, optimize=True)
        elif ext == 'png':
            img.save(target_path, 'PNG', optimize=True)
        elif ext == 'webp':
            img.save(target_path, 'WEBP', quality=85)
        else:
            img.save(target_path)
            
        return filename
    except Exception:
        # Fallback to direct raw save if PIL encounters uncommon format
        filename = f"{prefix}_{uuid.uuid4().hex}_{secure_filename(file.filename)}"
        target_path = os.path.join(target_folder, filename)
        file.seek(0)
        file.save(target_path)
        return filename

def supervisor_or_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login', next=request.url))
        if not (current_user.is_supervisor or current_user.is_admin):
            flash('Akses ditolak: Halaman ini hanya untuk Supervisor dan Admin.', 'danger')
            return redirect(url_for('exam.catalog'))
        return f(*args, **kwargs)
    return decorated_function


@supervisor_bp.route('/')
@supervisor_bp.route('/dashboard')
@login_required
@supervisor_or_admin_required
def dashboard():
    total_questions = Question.query.count()
    my_questions = Question.query.filter_by(created_by_id=current_user.id).count()
    
    # Counts by type
    pg_count = Question.query.filter_by(question_type='pg').count()
    pg_kompleks_count = Question.query.filter_by(question_type='pg_kompleks').count()
    isian_count = Question.query.filter_by(question_type='isian').count()
    
    # Subtests and groups
    groups = TestGroup.query.order_by(TestGroup.order_num).all()
    subtests = Subtest.query.order_by(Subtest.order_num).all()
    topics = Topic.query.all()
    
    recent_questions = Question.query.order_by(Question.created_at.desc()).limit(8).all()
    packages = TryoutPackage.query.order_by(TryoutPackage.created_at.desc()).limit(5).all()

    return render_template(
        'supervisor/dashboard.html',
        total_questions=total_questions,
        my_questions=my_questions,
        pg_count=pg_count,
        pg_kompleks_count=pg_kompleks_count,
        isian_count=isian_count,
        groups=groups,
        subtests=subtests,
        topics=topics,
        recent_questions=recent_questions,
        packages=packages
    )


# ==========================================
# 3-Tier Structure Management (T1 - T3)
# ==========================================

@supervisor_bp.route('/structure')
@login_required
@supervisor_or_admin_required
def structure_manager():
    groups = TestGroup.query.order_by(TestGroup.order_num).all()
    subtests = Subtest.query.order_by(Subtest.order_num).all()
    return render_template('supervisor/structure_manager.html', groups=groups, subtests=subtests)


@supervisor_bp.route('/structure/group/add', methods=['POST'])
@login_required
@supervisor_or_admin_required
def add_test_group():
    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip()
    description = request.form.get('description', '').strip()
    order_num = int(request.form.get('order_num', 1))

    if not name:
        flash('Nama Kelompok Ujian (Tier 1) wajib diisi.', 'danger')
        return redirect(url_for('supervisor.structure_manager'))

    if TestGroup.query.filter_by(name=name).first():
        flash('Kelompok Ujian dengan nama tersebut sudah ada.', 'warning')
        return redirect(url_for('supervisor.structure_manager'))

    tg = TestGroup(name=name, code=code, description=description, order_num=order_num)
    db.session.add(tg)
    db.session.commit()
    flash(f"Kelompok Ujian '{name}' (Tier 1) berhasil ditambahkan.", 'success')
    return redirect(url_for('supervisor.structure_manager'))


@supervisor_bp.route('/structure/subtest/add', methods=['POST'])
@login_required
@supervisor_or_admin_required
def add_subtest():
    test_group_id = request.form.get('test_group_id', type=int)
    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip()
    description = request.form.get('description', '').strip()
    default_duration = int(request.form.get('default_duration_minutes', 25))
    order_num = int(request.form.get('order_num', 1))

    if not test_group_id or not name:
        flash('Kelompok Ujian dan Nama Subtes (Tier 2) wajib diisi.', 'danger')
        return redirect(url_for('supervisor.structure_manager'))

    subtest = Subtest(
        test_group_id=test_group_id,
        name=name,
        code=code,
        description=description,
        default_duration_minutes=default_duration,
        order_num=order_num
    )
    db.session.add(subtest)
    db.session.commit()
    flash(f"Subtes '{name}' (Tier 2) dengan durasi {default_duration} menit berhasil ditambahkan.", 'success')
    return redirect(url_for('supervisor.structure_manager'))


@supervisor_bp.route('/structure/topic/add', methods=['POST'])
@login_required
@supervisor_or_admin_required
def add_topic():
    subtest_id = request.form.get('subtest_id', type=int)
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()

    if not subtest_id or not name:
        flash('Subtes dan Nama Topik (Tier 3) wajib diisi.', 'danger')
        return redirect(url_for('supervisor.structure_manager'))

    topic = Topic(subtest_id=subtest_id, name=name, description=description)
    db.session.add(topic)
    db.session.commit()
    flash(f"Topik '{name}' (Tier 3 Opsional) berhasil ditambahkan.", 'success')
    return redirect(url_for('supervisor.structure_manager'))


@supervisor_bp.route('/structure/delete/<tier>/<int:item_id>', methods=['POST'])
@login_required
@supervisor_or_admin_required
def delete_structure_item(tier, item_id):
    if tier == 'group':
        item = TestGroup.query.get_or_404(item_id)
        name = item.name
        db.session.delete(item)
    elif tier == 'subtest':
        item = Subtest.query.get_or_404(item_id)
        name = item.name
        db.session.delete(item)
    elif tier == 'topic':
        item = Topic.query.get_or_404(item_id)
        name = item.name
        db.session.delete(item)
    else:
        flash('Tier tidak valid.', 'danger')
        return redirect(url_for('supervisor.structure_manager'))

    db.session.commit()
    flash(f"Data {tier.upper()} '{name}' berhasil dihapus.", 'info')
    return redirect(url_for('supervisor.structure_manager'))


# ==========================================
# Question Bank (Bank Soal)
# ==========================================

@supervisor_bp.route('/questions')
@login_required
@supervisor_or_admin_required
def questions():
    subtest_id = request.args.get('subtest_id', type=int)
    topic_id = request.args.get('topic_id', type=int)
    q_type = request.args.get('type', '')
    difficulty = request.args.get('difficulty', '')
    search = request.args.get('search', '').strip()

    query = Question.query

    if subtest_id:
        query = query.filter_by(subtest_id=subtest_id)
    if topic_id:
        query = query.filter_by(topic_id=topic_id)
    if q_type:
        query = query.filter_by(question_type=q_type)
    if difficulty:
        query = query.filter_by(difficulty_level=difficulty)
    if search:
        query = query.filter(Question.question_text.ilike(f"%{search}%"))

    questions_list = query.order_by(Question.created_at.desc()).all()
    subtests = Subtest.query.order_by(Subtest.order_num).all()
    topics = Topic.query.all()

    return render_template(
        'supervisor/questions.html',
        questions=questions_list,
        subtests=subtests,
        topics=topics,
        current_subtest=subtest_id,
        current_topic=topic_id,
        current_type=q_type,
        current_difficulty=difficulty,
        search_query=search
    )


@supervisor_bp.route('/questions/new', methods=['GET', 'POST'])
@login_required
@supervisor_or_admin_required
def question_new():
    if request.method == 'POST':
        subtest_id = request.form.get('subtest_id', type=int)
        topic_id = request.form.get('topic_id', type=int) or None
        question_type = request.form.get('question_type', 'pg')
        question_text = request.form.get('question_text', '').strip()
        explanation_text = request.form.get('explanation_text', '').strip()
        difficulty_level = request.form.get('difficulty_level', 'sedang')

        if not subtest_id or not question_text:
            flash('Subtes (Tier 2) dan Teks Soal wajib diisi.', 'danger')
            return redirect(request.url)

        # Process question image upload with automatic optimization
        question_image = None
        if 'question_image' in request.files:
            file = request.files['question_image']
            if file and file.filename != '' and allowed_file(file.filename):
                question_image = save_optimized_image(file, current_app.config['UPLOAD_FOLDER_QUESTIONS'], prefix='q')

        # Process explanation image upload with automatic optimization
        explanation_image = None
        if 'explanation_image' in request.files:
            file = request.files['explanation_image']
            if file and file.filename != '' and allowed_file(file.filename):
                explanation_image = save_optimized_image(file, current_app.config['UPLOAD_FOLDER_EXPLANATIONS'], prefix='exp')

        # Process Options and Correct Answer according to question_type
        options_data = []
        correct_answer_data = None

        if question_type == 'pg':
            # Single choice A-E
            keys = ['A', 'B', 'C', 'D', 'E']
            for k in keys:
                opt_text = request.form.get(f'opt_text_{k}', '').strip()
                if opt_text:
                    options_data.append({'key': k, 'text': opt_text})
            correct_answer_data = request.form.get('correct_pg', 'A')

        elif question_type == 'pg_kompleks':
            # Multiple checkboxes A-E
            keys = ['A', 'B', 'C', 'D', 'E']
            for k in keys:
                opt_text = request.form.get(f'opt_kompleks_text_{k}', '').strip()
                if opt_text:
                    options_data.append({'key': k, 'text': opt_text})
            correct_keys = request.form.getlist('correct_kompleks')
            correct_answer_data = correct_keys if correct_keys else []

        elif question_type == 'isian':
            # Short answer / simple number / words
            accepted_answers = request.form.get('isian_answers', '').strip()
            # Split by comma or semicolon into list of valid variations
            correct_answer_data = [ans.strip() for ans in accepted_answers.replace(';', ',').split(',') if ans.strip()]
            options_data = []

        q = Question(
            subtest_id=subtest_id,
            topic_id=topic_id,
            question_type=question_type,
            question_text=question_text,
            question_image=question_image,
            options_json=json.dumps(options_data, ensure_ascii=False),
            correct_answer_json=json.dumps(correct_answer_data, ensure_ascii=False),
            explanation_text=explanation_text,
            explanation_image=explanation_image,
            difficulty_level=difficulty_level,
            created_by_id=current_user.id
        )
        db.session.add(q)
        db.session.commit()
        flash('Butir soal berhasil ditambahkan ke Bank Soal!', 'success')
        return redirect(url_for('supervisor.questions'))

    subtests = Subtest.query.order_by(Subtest.order_num).all()
    topics = Topic.query.all()
    return render_template('supervisor/question_form.html', subtests=subtests, topics=topics, question=None)


@supervisor_bp.route('/questions/<int:question_id>/edit', methods=['GET', 'POST'])
@login_required
@supervisor_or_admin_required
def question_edit(question_id):
    q = Question.query.get_or_404(question_id)

    if request.method == 'POST':
        q.subtest_id = request.form.get('subtest_id', type=int)
        q.topic_id = request.form.get('topic_id', type=int) or None
        q.question_type = request.form.get('question_type', 'pg')
        q.question_text = request.form.get('question_text', '').strip()
        q.explanation_text = request.form.get('explanation_text', '').strip()
        q.difficulty_level = request.form.get('difficulty_level', 'sedang')

        # Handle image replacement with optimization
        if 'question_image' in request.files:
            file = request.files['question_image']
            if file and file.filename != '' and allowed_file(file.filename):
                q.question_image = save_optimized_image(file, current_app.config['UPLOAD_FOLDER_QUESTIONS'], prefix='q')

        if 'explanation_image' in request.files:
            file = request.files['explanation_image']
            if file and file.filename != '' and allowed_file(file.filename):
                q.explanation_image = save_optimized_image(file, current_app.config['UPLOAD_FOLDER_EXPLANATIONS'], prefix='exp')

        # Process options and correct answers
        options_data = []
        correct_answer_data = None

        if q.question_type == 'pg':
            keys = ['A', 'B', 'C', 'D', 'E']
            for k in keys:
                opt_text = request.form.get(f'opt_text_{k}', '').strip()
                if opt_text:
                    options_data.append({'key': k, 'text': opt_text})
            correct_answer_data = request.form.get('correct_pg', 'A')

        elif q.question_type == 'pg_kompleks':
            keys = ['A', 'B', 'C', 'D', 'E']
            for k in keys:
                opt_text = request.form.get(f'opt_kompleks_text_{k}', '').strip()
                if opt_text:
                    options_data.append({'key': k, 'text': opt_text})
            correct_keys = request.form.getlist('correct_kompleks')
            correct_answer_data = correct_keys if correct_keys else []

        elif q.question_type == 'isian':
            accepted_answers = request.form.get('isian_answers', '').strip()
            correct_answer_data = [ans.strip() for ans in accepted_answers.replace(';', ',').split(',') if ans.strip()]
            options_data = []

        q.options_json = json.dumps(options_data, ensure_ascii=False)
        q.correct_answer_json = json.dumps(correct_answer_data, ensure_ascii=False)

        db.session.commit()
        flash('Perubahan soal berhasil disimpan!', 'success')
        return redirect(url_for('supervisor.questions'))

    subtests = Subtest.query.order_by(Subtest.order_num).all()
    topics = Topic.query.all()
    return render_template('supervisor/question_form.html', subtests=subtests, topics=topics, question=q)


@supervisor_bp.route('/questions/<int:question_id>/delete', methods=['POST'])
@login_required
@supervisor_or_admin_required
def question_delete(question_id):
    q = Question.query.get_or_404(question_id)
    db.session.delete(q)
    db.session.commit()
    flash(f"Soal #{question_id} berhasil dihapus dari Bank Soal.", 'info')
    return redirect(url_for('supervisor.questions'))


@supervisor_bp.route('/questions/<int:question_id>/preview')
@login_required
@supervisor_or_admin_required
def question_preview(question_id):
    q = Question.query.get_or_404(question_id)
    return render_template('supervisor/question_preview.html', question=q)


# ==========================================
# Analytics & Leaderboard for Supervisor
# ==========================================

@supervisor_bp.route('/analytics')
@login_required
@supervisor_or_admin_required
def analytics():
    packages = TryoutPackage.query.order_by(TryoutPackage.created_at.desc()).all()
    selected_package_id = request.args.get('package_id', type=int)
    
    if not selected_package_id and packages:
        selected_package_id = packages[0].id

    selected_package = TryoutPackage.query.get(selected_package_id) if selected_package_id else None
    sessions = []
    subtest_stats = []
    
    if selected_package:
        sessions = ExamSession.query.filter_by(
            tryout_package_id=selected_package.id,
            status='completed'
        ).order_by(ExamSession.national_rank.asc()).all()

        # Calculate average score per subtest
        for ts in selected_package.package_subtests:
            scores = SubtestScore.query.join(ExamSession).filter(
                ExamSession.tryout_package_id == selected_package.id,
                ExamSession.status == 'completed',
                SubtestScore.subtest_id == ts.subtest_id
            ).all()
            
            if scores:
                avg_irt = sum(s.irt_score for s in scores) / len(scores)
                avg_raw = sum(s.raw_correct for s in scores) / len(scores)
            else:
                avg_irt = 0.0
                avg_raw = 0.0
                
            subtest_stats.append({
                'subtest': ts.subtest,
                'avg_irt': round(avg_irt, 1),
                'avg_raw': round(avg_raw, 1),
                'duration': ts.duration_minutes
            })

    return render_template(
        'supervisor/analytics.html',
        packages=packages,
        selected_package=selected_package,
        sessions=sessions,
        subtest_stats=subtest_stats
    )


# ==========================================
# User Test History & Live Monitor
# ==========================================

@supervisor_bp.route('/user-history')
@login_required
@supervisor_or_admin_required
def user_history():
    search = request.args.get('search', '').strip()
    query = User.query.filter_by(role='peserta')
    
    if search:
        query = query.filter(
            (User.full_name.ilike(f"%{search}%")) |
            (User.username.ilike(f"%{search}%")) |
            (User.school.ilike(f"%{search}%"))
        )
    
    users = query.order_by(User.created_at.desc()).all()
    return render_template('supervisor/user_history.html', users=users, search=search)


@supervisor_bp.route('/user-history/<int:user_id>')
@login_required
@supervisor_or_admin_required
def user_detail_history(user_id):
    target_user = User.query.get_or_404(user_id)
    sessions = ExamSession.query.filter_by(user_id=user_id).order_by(ExamSession.start_time.desc()).all()
    logs = ActivityLog.query.filter_by(user_id=user_id).order_by(ActivityLog.created_at.desc()).limit(20).all()
    return render_template('supervisor/user_detail_history.html', target_user=target_user, sessions=sessions, logs=logs)


# API endpoint for dynamic topic filtering by subtest
@supervisor_bp.route('/api/topics-by-subtest/<int:subtest_id>')
def api_topics(subtest_id):
    topics = Topic.query.filter_by(subtest_id=subtest_id).all()
    return jsonify([{'id': t.id, 'name': t.name} for t in topics])
