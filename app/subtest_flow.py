from datetime import datetime, timezone, timedelta
from app import db
from app.models import ExamSubtestAttempt

# Toleransi autosave yang terlambat karena jaringan setelah timer subtes habis
AUTOSAVE_GRACE_SECONDS = 10


def as_utc(value):
    """Database menyimpan timestamp naive UTC"""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def subtest_durations(package):
    return {ts.subtest_id: ts.duration_minutes for ts in package.package_subtests}


def attempt_deadline(attempt, duration_minutes):
    return as_utc(attempt.started_at) + timedelta(minutes=duration_minutes)


def remaining_seconds(attempt, duration_minutes, now=None):
    now = now or datetime.now(timezone.utc)
    return max(0, int((attempt_deadline(attempt, duration_minutes) - now).total_seconds()))


def has_answer(answer):
    return answer.user_answer_json not in (None, '""', 'null', '[]')


def sync_expired_attempts(session, now=None):
    """Mengunci subtes yang timernya sudah habis. Return True bila ada perubahan (caller yang commit)."""
    now = now or datetime.now(timezone.utc)
    durations = subtest_durations(session.tryout_package)
    changed = False
    for attempt in session.subtest_attempts:
        if attempt.status != 'in_progress':
            continue
        duration = durations.get(attempt.subtest_id)
        # Subtes yang sudah dikeluarkan admin dari paket langsung dikunci
        deadline = attempt_deadline(attempt, duration) if duration is not None else now
        if now >= deadline:
            attempt.status = 'finished'
            attempt.finished_at = deadline
            changed = True
    return changed


def subtest_states(session, now=None):
    """Status tiap subtes paket (urut sesuai paket) untuk menu pilih subtes"""
    now = now or datetime.now(timezone.utc)
    package = session.tryout_package
    attempts = {a.subtest_id: a for a in session.subtest_attempts}
    has_active = any(a.status == 'in_progress' for a in attempts.values())
    package_open = package.is_active_now()

    question_totals = {}
    for tq in package.package_questions:
        if tq.question:
            question_totals[tq.question.subtest_id] = question_totals.get(tq.question.subtest_id, 0) + 1
    answered_totals = {}
    for ans in session.answers:
        if ans.question and has_answer(ans):
            answered_totals[ans.question.subtest_id] = answered_totals.get(ans.question.subtest_id, 0) + 1

    states = []
    earlier_not_started = False
    for position, ts in enumerate(package.package_subtests, start=1):
        attempt = attempts.get(ts.subtest_id)
        status = attempt.status if attempt else 'not_started'

        lock_reason = None
        if status == 'not_started':
            if not package_open:
                lock_reason = 'Paket tryout sudah ditutup'
            elif has_active:
                lock_reason = 'Selesaikan dulu subtes yang sedang berjalan'
            elif earlier_not_started and not package.free_subtest_order:
                lock_reason = 'Kerjakan subtes sesuai urutan'
            earlier_not_started = True

        states.append({
            'position': position,
            'tryout_subtest': ts,
            'subtest': ts.subtest,
            'status': status,
            'attempt': attempt,
            'remaining_seconds': remaining_seconds(attempt, ts.duration_minutes, now) if status == 'in_progress' else 0,
            'answered': answered_totals.get(ts.subtest_id, 0),
            'total': question_totals.get(ts.subtest_id, 0),
            'can_start': status == 'not_started' and lock_reason is None,
            'lock_reason': lock_reason,
        })
    return states


def start_subtest_attempt(session, subtest_id, now=None):
    """Membuka subtes baru bila aturan mode paket mengizinkan. Return (attempt, pesan_error)."""
    now = now or datetime.now(timezone.utc)
    sync_expired_attempts(session, now)
    state = next((s for s in subtest_states(session, now) if s['subtest'].id == subtest_id), None)
    if state is None:
        return None, 'Subtes tidak ditemukan dalam paket ini.'
    if state['status'] == 'finished':
        return None, 'Subtes ini sudah selesai dan terkunci.'
    if state['status'] == 'in_progress':
        return state['attempt'], None
    if not state['can_start']:
        return None, f"{state['lock_reason']}."

    attempt = ExamSubtestAttempt(
        exam_session_id=session.id,
        subtest_id=subtest_id,
        status='in_progress',
        started_at=now
    )
    session.subtest_attempts.append(attempt)
    return attempt, None


def finalize_session(session, now=None):
    """Menutup sesi ujian: subtes yang masih berjalan dikunci, lalu skor mentah dihitung"""
    now = now or datetime.now(timezone.utc)
    sync_expired_attempts(session, now)
    for attempt in session.subtest_attempts:
        if attempt.status == 'in_progress':
            attempt.status = 'finished'
            attempt.finished_at = now

    raw_correct_count = 0
    for ans in session.answers:
        if ans.question:
            ans.is_correct = ans.question.is_answer_correct(ans.user_answer)
            if ans.is_correct:
                raw_correct_count += 1

    session.total_raw_score = float(raw_correct_count)
    session.status = 'completed'
    session.submitted_at = now


def all_subtests_finished(session):
    finished_ids = {a.subtest_id for a in session.subtest_attempts if a.status == 'finished'}
    return {ts.subtest_id for ts in session.tryout_package.package_subtests} <= finished_ids


def close_idle_sessions(package, now=None):
    """Menutup sesi in_progress yang tidak sedang mengerjakan subtes (diam di menu / ditinggal).
    Return (jumlah_ditutup, jumlah_masih_mengerjakan). Caller yang commit."""
    now = now or datetime.now(timezone.utc)
    closed = running = 0
    for session in package.exam_sessions.filter_by(status='in_progress').all():
        sync_expired_attempts(session, now)
        if session.active_attempt:
            running += 1
        else:
            finalize_session(session, now)
            closed += 1
    return closed, running


def close_if_package_ended(session, now=None):
    """Setelah jadwal paket ditutup, sesi yang tidak sedang mengerjakan subtes otomatis diselesaikan.
    Return True bila sesi ditutup (caller yang commit)."""
    if session.status != 'in_progress' or not session.tryout_package.has_ended():
        return False
    sync_expired_attempts(session, now)
    if session.active_attempt:
        return False
    finalize_session(session, now)
    return True
