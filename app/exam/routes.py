import json
from datetime import datetime, timezone, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from app import db
from app.models import (
    TryoutPackage, TryoutSubtest, TryoutQuestion,
    ExamSession, ExamAnswer, SubtestScore, Question, ActivityLog, Subtest
)
from app.subtest_flow import (
    AUTOSAVE_GRACE_SECONDS, as_utc, attempt_deadline, subtest_durations, remaining_seconds,
    sync_expired_attempts, subtest_states, start_subtest_attempt, finalize_session,
    all_subtests_finished, close_if_package_ended
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

    # Check for existing session
    session = ExamSession.query.filter_by(
        user_id=current_user.id,
        tryout_package_id=package_id
    ).first()

    if session:
        if session.status == 'completed':
            return redirect(url_for('exam.result', session_id=session.id))
        # Resume active session
        return redirect(url_for('exam.subtest_menu', session_id=session.id))

    if not pkg.is_active_now():
        flash('Paket tryout ini belum dibuka atau sudah ditutup.', 'warning')
        return redirect(url_for('exam.package_detail', package_id=pkg.id))

    # Create new session (subtes dibuka satu per satu dari menu pilih subtes)
    now = datetime.now(timezone.utc)
    new_session = ExamSession(
        user_id=current_user.id,
        tryout_package_id=package_id,
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
    return redirect(url_for('exam.subtest_menu', session_id=new_session.id))


@exam_bp.route('/cbt/<int:session_id>/menu')
@login_required
def subtest_menu(session_id):
    session = ExamSession.query.get_or_404(session_id)

    # Permission check
    if session.user_id != current_user.id and not (current_user.is_admin or current_user.is_supervisor):
        flash('Anda tidak memiliki izin mengakses sesi ujian ini.', 'danger')
        return redirect(url_for('exam.catalog'))

    pkg = session.tryout_package
    if not pkg.package_subtests:
        flash('Paket ujian ini tidak memiliki subtes yang dikonfigurasi.', 'danger')
        return redirect(url_for('exam.catalog'))

    if session.status == 'in_progress':
        changed = sync_expired_attempts(session)

        if close_if_package_ended(session):
            db.session.commit()
            log_activity('SUBMIT_EXAM', f"Exam session #{session.id} auto-submitted: package schedule closed")
            flash('Jadwal paket tryout telah ditutup. Sesi ujian Anda otomatis diselesaikan.', 'info')
            return redirect(url_for('exam.result', session_id=session.id))

        if all_subtests_finished(session):
            finalize_session(session)
            db.session.commit()
            log_activity('SUBMIT_EXAM', f"Exam session #{session.id} auto-submitted: all subtests finished. Raw score: {int(session.total_raw_score)}")
            flash('Semua subtes telah selesai dikerjakan. Lembar ujian otomatis dikumpulkan.', 'success')
            return redirect(url_for('exam.result', session_id=session.id))

        if changed:
            db.session.commit()

    if session.status == 'completed':
        return redirect(url_for('exam.result', session_id=session.id))

    states = subtest_states(session)
    return render_template(
        'exam/subtest_menu.html',
        session=session,
        package=pkg,
        states=states,
        active_state=next((s for s in states if s['status'] == 'in_progress'), None),
        not_started_count=sum(1 for s in states if s['status'] == 'not_started')
    )


@exam_bp.route('/cbt/<int:session_id>/subtest/<int:subtest_id>/start', methods=['POST'])
@login_required
def start_subtest(session_id, subtest_id):
    session = ExamSession.query.get_or_404(session_id)
    if session.user_id != current_user.id:
        flash('Akses ditolak.', 'danger')
        return redirect(url_for('exam.catalog'))

    if session.status == 'completed':
        return redirect(url_for('exam.result', session_id=session.id))

    attempt, error = start_subtest_attempt(session, subtest_id)
    if error:
        db.session.commit()  # simpan penguncian subtes yang timernya sudah habis
        flash(error, 'warning')
        return redirect(url_for('exam.subtest_menu', session_id=session.id))

    is_new_attempt = attempt.id is None
    try:
        db.session.commit()
    except IntegrityError:
        # Klik ganda: subtes sudah dibuka oleh request sebelumnya
        db.session.rollback()
        return redirect(url_for('exam.cbt_room', session_id=session.id))

    if is_new_attempt:
        log_activity('START_SUBTEST', f"Exam session #{session.id} started subtest '{attempt.subtest.name}'")
    return redirect(url_for('exam.cbt_room', session_id=session.id))


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

    if sync_expired_attempts(session):
        db.session.commit()
        flash('Waktu subtes telah habis. Jawaban Anda sudah tersimpan dan subtes dikunci.', 'info')

    # Tidak ada subtes yang sedang berjalan -> kembali ke menu pilih subtes
    attempt = session.active_attempt
    if not attempt:
        return redirect(url_for('exam.subtest_menu', session_id=session.id))

    pkg = session.tryout_package
    subtests_list = pkg.package_subtests
    subtest_position, active_tryout_subtest = next(
        (pos, ts) for pos, ts in enumerate(subtests_list, start=1) if ts.subtest_id == attempt.subtest_id
    )
    active_subtest = active_tryout_subtest.subtest

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
        active_subtest=active_subtest,
        subtest_position=subtest_position,
        total_subtests=len(subtests_list),
        remaining_seconds=remaining_seconds(attempt, active_tryout_subtest.duration_minutes),
        questions_in_subtest=questions_in_subtest
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

    question = Question.query.get(question_id)
    package_question_ids = {tq.question_id for tq in session.tryout_package.package_questions}
    if not question or question.id not in package_question_ids:
        return jsonify({'status': 'error', 'message': 'Soal tidak termasuk dalam paket ini.'}), 400

    # Jawaban hanya diterima untuk subtes yang sedang berjalan. Subtes yang terkunci karena timer
    # habis masih menerima autosave yang terlambat dalam batas toleransi jaringan.
    now = datetime.now(timezone.utc)
    attempt = next((a for a in session.subtest_attempts if a.subtest_id == question.subtest_id), None)
    duration = subtest_durations(session.tryout_package).get(question.subtest_id)
    accepted = False
    if attempt and duration is not None:
        deadline = attempt_deadline(attempt, duration)
        within_time = now <= deadline + timedelta(seconds=AUTOSAVE_GRACE_SECONDS)
        locked_by_timer = attempt.status == 'finished' and attempt.finished_at and as_utc(attempt.finished_at) >= deadline
        accepted = within_time and (attempt.status == 'in_progress' or locked_by_timer)

    if not accepted:
        if sync_expired_attempts(session, now):
            db.session.commit()
        return jsonify({'status': 'error', 'message': 'Subtes ini tidak sedang aktif atau waktunya sudah habis.'}), 403

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
    answer_rec.is_correct = question.is_answer_correct(user_answer)

    db.session.commit()
    return jsonify({
        'status': 'success',
        'question_id': question_id,
        'has_answer': user_answer not in (None, '', [], 'null')
    })


@exam_bp.route('/cbt/<int:session_id>/finish-subtest', methods=['POST'])
@login_required
def finish_subtest(session_id):
    session = ExamSession.query.get_or_404(session_id)
    if session.user_id != current_user.id and not current_user.is_admin:
        flash('Akses ditolak.', 'danger')
        return redirect(url_for('exam.catalog'))

    if session.status == 'completed':
        return redirect(url_for('exam.result', session_id=session.id))

    now = datetime.now(timezone.utc)
    sync_expired_attempts(session, now)
    attempt = session.active_attempt
    if attempt:
        attempt.status = 'finished'
        attempt.finished_at = now
    db.session.commit()

    if attempt:
        log_activity('FINISH_SUBTEST', f"Exam session #{session.id} finished subtest '{attempt.subtest.name}'")
        flash(f"Subtes '{attempt.subtest.name}' selesai dan dikunci.", 'success')
    return redirect(url_for('exam.subtest_menu', session_id=session.id))


@exam_bp.route('/cbt/<int:session_id>/submit', methods=['POST'])
@login_required
def submit_exam(session_id):
    session = ExamSession.query.get_or_404(session_id)
    if session.user_id != current_user.id and not current_user.is_admin:
        flash('Akses ditolak.', 'danger')
        return redirect(url_for('exam.catalog'))

    if session.status != 'completed':
        finalize_session(session)
        db.session.commit()
        attempted = len(session.attempted_subtest_ids)
        total = len(session.tryout_package.package_subtests)
        log_activity('SUBMIT_EXAM', f"Submitted exam session #{session.id}. Raw score: {int(session.total_raw_score)}. Subtests attempted: {attempted}/{total}")
        flash('Ujian telah berhasil diselesaikan dan disimpan!', 'success')

    return redirect(url_for('exam.result', session_id=session.id))


@exam_bp.route('/result/<int:session_id>')
@login_required
def result(session_id):
    session = ExamSession.query.get_or_404(session_id)
    if session.user_id != current_user.id and not (current_user.is_admin or current_user.is_supervisor):
        flash('Akses ditolak.', 'danger')
        return redirect(url_for('exam.catalog'))

    if session.status == 'in_progress':
        return redirect(url_for('exam.subtest_menu', session_id=session.id))

    scores_by_subtest = {sc.subtest_id: sc for sc in session.subtest_scores}
    attempted_ids = session.attempted_subtest_ids
    subtest_rows = [
        {
            'subtest': ts.subtest,
            'score': scores_by_subtest.get(ts.subtest_id),
            'attempted': ts.subtest_id in attempted_ids
        }
        for ts in session.tryout_package.package_subtests
    ]
    ranked_participants = ExamSession.query.filter(
        ExamSession.tryout_package_id == session.tryout_package_id,
        ExamSession.status == 'completed',
        ExamSession.national_rank.isnot(None)
    ).count()

    return render_template(
        'exam/result.html',
        session=session,
        subtest_rows=subtest_rows,
        attempted_count=sum(1 for r in subtest_rows if r['attempted']),
        ranked_participants=ranked_participants
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
    # Hanya peserta yang mengerjakan seluruh subtes yang mendapat peringkat
    sessions = ExamSession.query.filter(
        ExamSession.tryout_package_id == package_id,
        ExamSession.status == 'completed',
        ExamSession.national_rank.isnot(None)
    ).order_by(ExamSession.national_rank.asc()).all()

    return render_template('exam/leaderboard.html', package=pkg, sessions=sessions, pending_count=pkg.pending_irt_count)
