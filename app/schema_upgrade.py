from datetime import timedelta
import sqlalchemy as sa
from app import db


def upgrade_schema():
    """Pembaruan skema ringan untuk database lama (aplikasi tidak memakai alat migrasi).
    Aman dijalankan berulang kali setiap aplikasi start."""
    from app.models import ExamSession  # memastikan semua model terdaftar sebelum create_all

    inspector = sa.inspect(db.engine)
    had_sessions_table = inspector.has_table('exam_sessions')
    had_attempts_table = inspector.has_table('exam_subtest_attempts')

    db.create_all()

    # Kolom baru dulu, baru kemudian migrasi data lewat ORM
    added_subtest_order = _add_column_if_missing('tryout_packages', 'free_subtest_order', 'BOOLEAN NOT NULL DEFAULT 1')
    _add_column_if_missing('users', 'must_change_password', 'BOOLEAN NOT NULL DEFAULT 0')
    added_irt_scored_at = _add_column_if_missing('exam_sessions', 'irt_scored_at', 'DATETIME')

    if added_subtest_order:
        _shift_package_schedule_to_utc()

    if added_irt_scored_at:
        _backfill_irt_scored_sessions()

    if had_sessions_table and not had_attempts_table:
        _backfill_subtest_attempts()

    _unrank_staff_sessions()


def _add_column_if_missing(table, column, ddl):
    """Return True bila kolom baru saja ditambahkan"""
    columns = {c['name'] for c in sa.inspect(db.engine).get_columns(table)}
    if column in columns:
        return False
    with db.engine.begin() as conn:
        conn.execute(sa.text(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}'))
    return True


def _backfill_irt_scored_sessions():
    """Sesi yang sudah pernah ikut kalkulasi IRT (punya peringkat atau skor subtes) ditandai sudah dinilai.
    Sesi yang selesai setelah kalkulasi terakhir tetap None sampai IRT dihitung ulang."""
    from app.models import ExamSession

    for session in ExamSession.query.filter_by(status='completed').all():
        package = session.tryout_package
        if package and package.is_irt_calculated and (session.national_rank is not None or session.subtest_scores):
            session.irt_scored_at = session.submitted_at or session.start_time
    db.session.commit()


def _unrank_staff_sessions():
    """Versi lama memberi peringkat juga ke akun admin/supervisor. Paket yang terdampak disusun ulang
    peringkatnya dari skor tersimpan; tidak melakukan apa pun bila datanya sudah benar."""
    from app.models import ExamSession, User
    from app.irt_engine import assign_national_ranks

    affected_package_ids = {
        package_id for (package_id,) in db.session.query(ExamSession.tryout_package_id)
        .join(User, ExamSession.user_id == User.id)
        .filter(User.role != 'peserta', ExamSession.national_rank.isnot(None))
        .distinct()
    }
    for package_id in affected_package_ids:
        assign_national_ranks(package_id)
    if affected_package_ids:
        db.session.commit()


def _shift_package_schedule_to_utc():
    """Versi lama menyimpan jadwal paket dari form sebagai jam WIB naive; kini disimpan sebagai UTC naive"""
    from app.models import TryoutPackage

    for pkg in TryoutPackage.query.all():
        if pkg.start_time:
            pkg.start_time -= timedelta(hours=7)
        if pkg.end_time:
            pkg.end_time -= timedelta(hours=7)
    db.session.commit()


def _backfill_subtest_attempts():
    """Konversi progres sesi dari alur berurutan lama (current_subtest_index) ke ExamSubtestAttempt"""
    from app.models import ExamSession, ExamSubtestAttempt

    for session in ExamSession.query.all():
        if not session.tryout_package:
            continue
        pointer = session.current_subtest_index or 0
        for idx, ts in enumerate(session.tryout_package.package_subtests):
            if idx > pointer:
                break
            if idx < pointer:
                attempt = ExamSubtestAttempt(
                    subtest_id=ts.subtest_id,
                    status='finished',
                    started_at=session.start_time,
                    finished_at=session.current_subtest_start or session.start_time
                )
            else:
                started_at = session.current_subtest_start or session.start_time
                running = session.status == 'in_progress'
                attempt = ExamSubtestAttempt(
                    subtest_id=ts.subtest_id,
                    status='in_progress' if running else 'finished',
                    started_at=started_at,
                    finished_at=None if running else (session.submitted_at or started_at)
                )
            session.subtest_attempts.append(attempt)
    db.session.commit()
