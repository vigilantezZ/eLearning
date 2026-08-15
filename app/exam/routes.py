import json
from datetime import datetime, timezone, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import (
    TryoutPackage, TryoutSubtest, TryoutQuestion, 
    ExamSession, ExamAnswer, SubtestScore, Question, ActivityLog, Subtest
)

exam_bp = Blueprint('exam', __name__)

def log_activity(action, details):
    try:
        ip = request.remote_addr
        log = ActivityLog(
            user_id=current_user.id if current_user.is_authenticated else None,
            action=action,
            details=details,
            ip_address=ip
        )
        db.session.add(log)
        db.session.commit()
    except Exception:
        db.session.rollback()


@exam_bp.route('/')
def catalog():
    packages = TryoutPackage.query.filter_by(is_published=True).order_by(TryoutPackage.created_at.desc()).all()
    user_sessions = {}
    if current_user.is_authenticated:
        sessions = ExamSession.query.filter_by(user_id=current_user.id).all()
        user_sessions = {s.tryout_package_id: s for s in sessions}

    return render_template('exam/catalog.html', packages=packages, user_sessions=user_sessions)


@exam_bp.route('/package/<int:package_id>')
def package_detail(package_id):
    pkg = TryoutPackage.query.get_or_404(package_id)
    user_session = None
    if current_user.is_authenticated:
        user_session = ExamSession.query.filter_by(
            user_id=current_user.id, 
            tryout_package_id=package_id
        ).first()

    return render_template('exam/package_detail.html', package=pkg, user_session=user_session)


@exam_bp.route('/exam/start/<int:package_id>', methods=['POST'])
@login_required
def start_exam(package_id):
    pkg = TryoutPackage.query.get_or_404(package_id)

    if not pkg.is_published:
        flash('Paket tryout ini belum dibuka.', 'warning')
        return redirect(url_for('exam.catalog'))

    # Check for existing session
    session = ExamSession.query.filter_by(
        user_id=current_user.id,
        tryout_package_id=package_id
    ).first()

    if session:
        if session.status == 'completed':
            return redirect(url_for('exam.result', session_id=session.id))
        # Resume active session
        return redirect(url_for('exam.cbt_room', session_id=session.id))

    # Create new session
    now = datetime.now(timezone.utc)
    new_session = ExamSession(
        user_id=current_user.id,
        tryout_package_id=package_id,
        current_subtest_index=0,
        current_subtest_start=now,
        start_time=now,
        status='in_progress',
        ip_address=request.remote_addr
    )
    db.session.add(new_session)
    db.session.flush()

    # Pre-create empty ExamAnswer entries for all questions in package
    for tq in pkg.package_questions:
        if tq.question:
            ans = ExamAnswer(
                exam_session_id=new_session.id,
                question_id=tq.question_id,
                user_answer_json='null',
                is_correct=False,
                is_marked_doubtful=False
            )
            db.session.add(ans)

    db.session.commit()
    log_activity('START_EXAM', f"Started exam session #{new_session.id} for package '{pkg.title}'")
    return redirect(url_for('exam.cbt_room', session_id=new_session.id))


@exam_bp.route('/cbt/<int:session_id>')
@login_required
def cbt_room(session_id):
    session = ExamSession.query.get_or_404(session_id)

    # Permission check
    if session.user_id != current_user.id and not (current_user.is_admin or current_user.is_supervisor):
        flash('Anda tidak memiliki izin mengakses sesi ujian ini.', 'danger')
        return redirect(url_for('exam.catalog'))

    if session.status == 'completed':
        return redirect(url_for('exam.result', session_id=session.id))

    pkg = session.tryout_package
    subtests_list = pkg.package_subtests
    
    if not subtests_list:
        flash('Paket ujian ini tidak memiliki subtes yang dikonfigurasi.', 'danger')
        return redirect(url_for('exam.catalog'))

    current_index = session.current_subtest_index
    if current_index >= len(subtests_list):
        # All subtests finished -> Auto-submit
        return redirect(url_for('exam.submit_exam', session_id=session.id))

    active_tryout_subtest = subtests_list[current_index]
    active_subtest = active_tryout_subtest.subtest

    # Calculate remaining seconds for the active subtest timer
    now = datetime.now(timezone.utc)
    subtest_start = session.current_subtest_start or session.start_time
    if subtest_start.tzinfo is None:
        subtest_start = subtest_start.replace(tzinfo=timezone.utc)

    duration_seconds = active_tryout_subtest.duration_minutes * 60
    elapsed_seconds = (now - subtest_start).total_seconds()
    remaining_seconds = max(0, int(duration_seconds - elapsed_seconds))

    # Auto advance if timer already reached zero
    if remaining_seconds <= 0:
        return redirect(url_for('exam.next_subtest', session_id=session.id))

    # Fetch questions belonging to this subtest in the package
    questions_in_subtest = []
    answers_map = {a.question_id: a for a in session.answers}

    for tq in pkg.package_questions:
        if tq.question and tq.question.subtest_id == active_subtest.id:
            ans_rec = answers_map.get(tq.question_id)
            questions_in_subtest.append({
                'order': len(questions_in_subtest) + 1,
                'question': tq.question,
                'answer': ans_rec
            })

    return render_template(
        'exam/cbt_room.html',
        session=session,
        package=pkg,
        subtests_list=subtests_list,
        current_subtest_index=current_index,
        active_subtest=active_subtest,
        active_duration_minutes=active_tryout_subtest.duration_minutes,
        remaining_seconds=remaining_seconds,
        questions_in_subtest=questions_in_subtest,
        total_subtests=len(subtests_list)
    )


@exam_bp.route('/api/cbt/autosave', methods=['POST'])
@login_required
def api_autosave():
    data = request.get_json() or {}
    session_id = data.get('session_id')
    question_id = data.get('question_id')
    user_answer = data.get('user_answer')
    is_marked_doubtful = bool(data.get('is_marked_doubtful', False))

    session = ExamSession.query.get(session_id)
    if not session or session.user_id != current_user.id or session.status != 'in_progress':
        return jsonify({'status': 'error', 'message': 'Sesi ujian tidak valid.'}), 403

    answer_rec = ExamAnswer.query.filter_by(
        exam_session_id=session.id,
        question_id=question_id
    ).first()

    if not answer_rec:
        answer_rec = ExamAnswer(
            exam_session_id=session.id,
            question_id=question_id
        )
        db.session.add(answer_rec)

    answer_rec.user_answer = user_answer
    answer_rec.is_marked_doubtful = is_marked_doubtful
    
    # Calculate correctness
    if answer_rec.question:
        answer_rec.is_correct = answer_rec.question.is_answer_correct(user_answer)

    db.session.commit()
    return jsonify({
        'status': 'success',
        'question_id': question_id,
        'has_answer': user_answer not in (None, '', [], 'null')
    })


@exam_bp.route('/cbt/<int:session_id>/next-subtest', methods=['POST', 'GET'])
@login_required
def next_subtest(session_id):
    session = ExamSession.query.get_or_404(session_id)
    if session.user_id != current_user.id and not current_user.is_admin:
        flash('Akses ditolak.', 'danger')
        return redirect(url_for('exam.catalog'))

    if session.status == 'completed':
        return redirect(url_for('exam.result', session_id=session.id))

    pkg = session.tryout_package
    total_subtests = len(pkg.package_subtests)
    next_index = session.current_subtest_index + 1

    if next_index >= total_subtests:
        # Reached end of all subtests -> Submit exam
        return redirect(url_for('exam.submit_exam', session_id=session.id))

    # Move to next subtest & reset timer anchor
    session.current_subtest_index = next_index
    session.current_subtest_start = datetime.now(timezone.utc)
    db.session.commit()

    flash(f"Beralih ke Subtes ke-{next_index + 1}: {pkg.package_subtests[next_index].subtest.name}", 'info')
    return redirect(url_for('exam.cbt_room', session_id=session.id))


@exam_bp.route('/cbt/<int:session_id>/submit', methods=['POST', 'GET'])
@login_required
def submit_exam(session_id):
    session = ExamSession.query.get_or_404(session_id)
    if session.user_id != current_user.id and not current_user.is_admin:
        flash('Akses ditolak.', 'danger')
        return redirect(url_for('exam.catalog'))

    if session.status != 'completed':
        session.status = 'completed'
        session.submitted_at = datetime.now(timezone.utc)
        
        # Calculate raw correct answers
        raw_correct_count = 0
        for ans in session.answers:
            if ans.question:
                ans.is_correct = ans.question.is_answer_correct(ans.user_answer)
                if ans.is_correct:
                    raw_correct_count += 1
        
        session.total_raw_score = float(raw_correct_count)
        db.session.commit()
        log_activity('SUBMIT_EXAM', f"Submitted exam session #{session.id}. Raw score: {raw_correct_count}")
        flash('Ujian telah berhasil diselesaikan dan disimpan!', 'success')

    return redirect(url_for('exam.result', session_id=session.id))


@exam_bp.route('/result/<int:session_id>')
@login_required
def result(session_id):
    session = ExamSession.query.get_or_404(session_id)
    if session.user_id != current_user.id and not (current_user.is_admin or current_user.is_supervisor):
        flash('Akses ditolak.', 'danger')
        return redirect(url_for('exam.catalog'))

    subtest_scores = SubtestScore.query.filter_by(exam_session_id=session.id).all()
    total_participants = ExamSession.query.filter_by(
        tryout_package_id=session.tryout_package_id,
        status='completed'
    ).count()

    return render_template(
        'exam/result.html',
        session=session,
        subtest_scores=subtest_scores,
        total_participants=total_participants
    )


@exam_bp.route('/review/<int:session_id>')
@login_required
def review_pembahasan(session_id):
    session = ExamSession.query.get_or_404(session_id)
    if session.user_id != current_user.id and not (current_user.is_admin or current_user.is_supervisor):
        flash('Akses ditolak.', 'danger')
        return redirect(url_for('exam.catalog'))

    pkg = session.tryout_package
    answers = session.answers

    # Group answers by subtest
    subtest_grouped = {}
    for ans in answers:
        if ans.question and ans.question.subtest:
            sub_id = ans.question.subtest.id
            if sub_id not in subtest_grouped:
                subtest_grouped[sub_id] = {
                    'subtest': ans.question.subtest,
                    'answers': []
                }
            subtest_grouped[sub_id]['answers'].append(ans)

    return render_template(
        'exam/review_pembahasan.html',
        session=session,
        package=pkg,
        subtest_grouped=subtest_grouped
    )


@exam_bp.route('/leaderboard/<int:package_id>')
def leaderboard(package_id):
    pkg = TryoutPackage.query.get_or_404(package_id)
    sessions = ExamSession.query.filter_by(
        tryout_package_id=package_id,
        status='completed'
    ).order_by(ExamSession.national_rank.asc()).all()

    return render_template('exam/leaderboard.html', package=pkg, sessions=sessions)
