from datetime import datetime, timezone
import json
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(20), nullable=True)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(128), nullable=False)
    school = db.Column(db.String(128), nullable=True)
    grade = db.Column(db.String(32), nullable=True)  # e.g., '12 SMA', 'Gap Year', '11 SMA'
    photo_filename = db.Column(db.String(256), nullable=True)
    role = db.Column(db.String(20), default='peserta', nullable=False)  # 'admin', 'supervisor', 'peserta'
    must_change_password = db.Column(db.Boolean, default=False, nullable=False)  # True setelah password direset admin
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    created_questions = db.relationship('Question', backref='creator', lazy='dynamic')
    created_packages = db.relationship('TryoutPackage', backref='creator', lazy='dynamic')
    exam_sessions = db.relationship('ExamSession', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    activity_logs = db.relationship('ActivityLog', backref='user', lazy='dynamic', cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_supervisor(self):
        return self.role == 'supervisor'

    @property
    def is_peserta(self):
        return self.role == 'peserta'

    @property
    def avatar_url(self):
        if self.photo_filename:
            return f"/static/uploads/avatars/{self.photo_filename}"
        return f"https://ui-avatars.com/api/?name={self.full_name.replace(' ', '+')}&background=4f46e5&color=fff&size=128"

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"


class TestGroup(db.Model):
    """Tier 1: Kelompok Ujian / Kategori Utama (e.g. Tes Potensi Skolastik (TPS), Tes Literasi)"""
    __tablename__ = 'test_groups'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, unique=True)
    code = db.Column(db.String(32), nullable=True)
    description = db.Column(db.Text, nullable=True)
    order_num = db.Column(db.Integer, default=1)

    # Relationships
    subtests = db.relationship('Subtest', backref='test_group', lazy='joined', order_by='Subtest.order_num', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<TestGroup T1: {self.name}>"


class Subtest(db.Model):
    """Tier 2: Subtes / Bidang Ujian (e.g. Kemampuan Penalaran Umum, Pengetahuan Kuantitatif) - Wajib"""
    __tablename__ = 'subtests'

    id = db.Column(db.Integer, primary_key=True)
    test_group_id = db.Column(db.Integer, db.ForeignKey('test_groups.id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(128), nullable=False)
    code = db.Column(db.String(32), nullable=True)
    description = db.Column(db.Text, nullable=True)
    default_duration_minutes = db.Column(db.Integer, default=25, nullable=False)
    order_num = db.Column(db.Integer, default=1)

    # Relationships
    topics = db.relationship('Topic', backref='subtest', lazy='dynamic', cascade='all, delete-orphan')
    questions = db.relationship('Question', backref='subtest', lazy='dynamic')
    tryout_subtests = db.relationship('TryoutSubtest', backref='subtest', lazy='dynamic')

    def __repr__(self):
        return f"<Subtest T2: {self.name}>"


class Topic(db.Model):
    """Tier 3: Topik / Kompetensi / Materi Pokok (e.g. Penalaran Induktif, Aljabar) - Opsional"""
    __tablename__ = 'topics'

    id = db.Column(db.Integer, primary_key=True)
    subtest_id = db.Column(db.Integer, db.ForeignKey('subtests.id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # Relationships
    questions = db.relationship('Question', backref='topic', lazy='dynamic')

    def __repr__(self):
        return f"<Topic T3: {self.name}>"


class Question(db.Model):
    """Bank Soal mendukung 3 tipe: PG (A-E), PG Kompleks (Checklist), Isian Singkat"""
    __tablename__ = 'questions'

    id = db.Column(db.Integer, primary_key=True)
    subtest_id = db.Column(db.Integer, db.ForeignKey('subtests.id', ondelete='SET NULL'), nullable=True)
    topic_id = db.Column(db.Integer, db.ForeignKey('topics.id', ondelete='SET NULL'), nullable=True)
    
    # Types: 'pg' (pilihan ganda tunggal A-E), 'pg_kompleks' (pilihan berganda / multi-checklist), 'isian' (isian singkat)
    question_type = db.Column(db.String(20), default='pg', nullable=False)
    
    question_text = db.Column(db.Text, nullable=False)
    question_image = db.Column(db.String(256), nullable=True)
    
    # JSON encoded options:
    # For PG: [{"key": "A", "text": "opsi 1", "image": ""}, {"key": "B", ...}]
    # For PG Kompleks: [{"key": "A", "text": "Pernyataan 1", "image": ""}, ...]
    # For Isian: [] (empty or placeholder)
    options_json = db.Column(db.Text, default='[]', nullable=False)
    
    # JSON encoded correct answers:
    # For PG: "A"
    # For PG Kompleks: ["A", "C", "D"]
    # For Isian: ["25", "dua puluh lima"] (normalized list of accepted variations)
    correct_answer_json = db.Column(db.Text, default='""', nullable=False)
    
    explanation_text = db.Column(db.Text, nullable=True)
    explanation_image = db.Column(db.String(256), nullable=True)
    
    difficulty_level = db.Column(db.String(20), default='sedang')  # 'mudah', 'sedang', 'sulit'
    
    # IRT Parameters (calculated/calibrated empirically or preset)
    irt_a = db.Column(db.Float, default=1.0)  # Discrimination parameter
    irt_b = db.Column(db.Float, default=0.0)  # Difficulty parameter
    irt_c = db.Column(db.Float, default=0.0)  # Guessing parameter (e.g. 0.2 for 5-choice PG)
    
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    tryout_questions = db.relationship('TryoutQuestion', backref='question', cascade='all, delete-orphan')

    @property
    def options(self):
        try:
            return json.loads(self.options_json) if self.options_json else []
        except Exception:
            return []

    @options.setter
    def options(self, value):
        self.options_json = json.dumps(value, ensure_ascii=False)

    @property
    def correct_answer(self):
        try:
            return json.loads(self.correct_answer_json) if self.correct_answer_json else ""
        except Exception:
            return ""

    @correct_answer.setter
    def correct_answer(self, value):
        self.correct_answer_json = json.dumps(value, ensure_ascii=False)

    def is_answer_correct(self, user_answer):
        """Validasi apakah jawaban peserta benar berdasarkan tipe soal"""
        if user_answer is None:
            return False
            
        correct = self.correct_answer
        if self.question_type == 'pg':
            return str(user_answer).strip().upper() == str(correct).strip().upper()
            
        elif self.question_type == 'pg_kompleks':
            # User answer is expected to be a list of keys e.g. ['A', 'C']
            if isinstance(user_answer, str):
                try:
                    user_answer = json.loads(user_answer)
                except Exception:
                    user_answer = [user_answer]
            if not isinstance(user_answer, list):
                user_answer = [user_answer]
                
            correct_set = set(str(k).strip().upper() for k in (correct if isinstance(correct, list) else [correct]))
            user_set = set(str(k).strip().upper() for k in user_answer)
            return correct_set == user_set
            
        elif self.question_type == 'isian':
            # Case-insensitive and trimmed comparison
            user_val = str(user_answer).strip().lower()
            if isinstance(correct, list):
                return user_val in [str(c).strip().lower() for c in correct]
            return user_val == str(correct).strip().lower()
            
        return False

    def __repr__(self):
        return f"<Question {self.id} ({self.question_type}) Subtest:{self.subtest_id}>"


class TryoutPackage(db.Model):
    """Paket Tryout (menggabungkan subtes-subtes dengan konfigurasi timer dan soal-soal)"""
    __tablename__ = 'tryout_packages'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    banner_image = db.Column(db.String(256), nullable=True)
    
    start_time = db.Column(db.DateTime, nullable=True)
    end_time = db.Column(db.DateTime, nullable=True)
    
    is_published = db.Column(db.Boolean, default=False, nullable=False)
    is_irt_calculated = db.Column(db.Boolean, default=False, nullable=False)
    # True: peserta bebas memilih urutan subtes; False: wajib berurutan sesuai order_num (simulasi UTBK)
    free_subtest_order = db.Column(db.Boolean, default=True, nullable=False)

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    package_subtests = db.relationship('TryoutSubtest', backref='tryout_package', lazy='joined', order_by='TryoutSubtest.order_num', cascade='all, delete-orphan')
    package_questions = db.relationship('TryoutQuestion', backref='tryout_package', lazy='joined', order_by='TryoutQuestion.order_num', cascade='all, delete-orphan')
    exam_sessions = db.relationship('ExamSession', backref='tryout_package', lazy='dynamic', cascade='all, delete-orphan')

    @property
    def total_duration_minutes(self):
        return sum(ps.duration_minutes for ps in self.package_subtests)

    @property
    def total_questions_count(self):
        return len(self.package_questions)

    @property
    def pending_irt_count(self):
        """Peserta yang sudah selesai setelah kalkulasi IRT terakhir (skornya belum dihitung).
        Sesi uji coba akun admin/supervisor tidak dihitung karena tidak memengaruhi peringkat."""
        return self.exam_sessions.join(User, ExamSession.user_id == User.id).filter(
            ExamSession.status == 'completed',
            ExamSession.irt_scored_at.is_(None),
            User.role == 'peserta'
        ).count()

    def is_active_now(self):
        now = datetime.now(timezone.utc)
        if not self.is_published:
            return False
        if self.start_time and now < self.start_time.replace(tzinfo=timezone.utc if self.start_time.tzinfo is None else self.start_time.tzinfo):
            return False
        if self.end_time and now > self.end_time.replace(tzinfo=timezone.utc if self.end_time.tzinfo is None else self.end_time.tzinfo):
            return False
        return True

    def has_ended(self):
        if not self.end_time:
            return False
        end = self.end_time if self.end_time.tzinfo else self.end_time.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > end


class TryoutSubtest(db.Model):
    """Subtes yang diujikan dalam satu paket tryout beserta alokasi waktu per subtes"""
    __tablename__ = 'tryout_subtests'

    id = db.Column(db.Integer, primary_key=True)
    tryout_package_id = db.Column(db.Integer, db.ForeignKey('tryout_packages.id', ondelete='CASCADE'), nullable=False)
    subtest_id = db.Column(db.Integer, db.ForeignKey('subtests.id', ondelete='CASCADE'), nullable=False)
    duration_minutes = db.Column(db.Integer, default=25, nullable=False)  # Dedicated Timer for this Subtest
    order_num = db.Column(db.Integer, default=1, nullable=False)


class TryoutQuestion(db.Model):
    """Pemetaan butir soal ke paket tryout dengan nomor urut pengerjaan"""
    __tablename__ = 'tryout_questions'

    id = db.Column(db.Integer, primary_key=True)
    tryout_package_id = db.Column(db.Integer, db.ForeignKey('tryout_packages.id', ondelete='CASCADE'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id', ondelete='CASCADE'), nullable=False)
    order_num = db.Column(db.Integer, default=1, nullable=False)


class ExamSession(db.Model):
    """Sesi ujian peserta untuk sebuah paket tryout"""
    __tablename__ = 'exam_sessions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    tryout_package_id = db.Column(db.Integer, db.ForeignKey('tryout_packages.id', ondelete='CASCADE'), nullable=False)
    
    # Legacy (alur berurutan lama): progres subtes kini dicatat di ExamSubtestAttempt
    current_subtest_index = db.Column(db.Integer, default=0, nullable=False)
    current_subtest_start = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    start_time = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    submitted_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default='in_progress', nullable=False)  # 'in_progress', 'completed', 'expired'
    
    total_raw_score = db.Column(db.Float, default=0.0)
    total_irt_score = db.Column(db.Float, default=0.0)
    national_rank = db.Column(db.Integer, nullable=True)
    irt_scored_at = db.Column(db.DateTime, nullable=True)  # Diisi saat ikut kalkulasi IRT; None = skor belum dihitung
    ip_address = db.Column(db.String(64), nullable=True)

    # Relationships
    answers = db.relationship('ExamAnswer', backref='exam_session', lazy='joined', cascade='all, delete-orphan')
    subtest_scores = db.relationship('SubtestScore', backref='exam_session', lazy='joined', cascade='all, delete-orphan')
    subtest_attempts = db.relationship('ExamSubtestAttempt', backref='exam_session', lazy='select', cascade='all, delete-orphan')

    @property
    def answered_count(self):
        return sum(1 for a in self.answers if a.user_answer_json not in (None, '""', 'null', '[]'))

    @property
    def active_attempt(self):
        return next((a for a in self.subtest_attempts if a.status == 'in_progress'), None)

    @property
    def attempted_subtest_ids(self):
        """Subtes yang pernah dibuka peserta (sedang berjalan atau sudah selesai)"""
        return {a.subtest_id for a in self.subtest_attempts}

    @property
    def is_full_attempt(self):
        """True bila seluruh subtes dalam paket sudah dikerjakan (syarat masuk peringkat)"""
        package_subtest_ids = {ts.subtest_id for ts in self.tryout_package.package_subtests}
        return package_subtest_ids <= self.attempted_subtest_ids

    def __repr__(self):
        return f"<ExamSession {self.id} User:{self.user_id} Status:{self.status}>"


class ExamSubtestAttempt(db.Model):
    """Status pengerjaan satu subtes dalam sesi ujian. Subtes yang belum dibuka tidak memiliki baris."""
    __tablename__ = 'exam_subtest_attempts'
    __table_args__ = (db.UniqueConstraint('exam_session_id', 'subtest_id', name='uq_attempt_session_subtest'),)

    id = db.Column(db.Integer, primary_key=True)
    exam_session_id = db.Column(db.Integer, db.ForeignKey('exam_sessions.id', ondelete='CASCADE'), nullable=False)
    subtest_id = db.Column(db.Integer, db.ForeignKey('subtests.id', ondelete='CASCADE'), nullable=False)
    status = db.Column(db.String(20), default='in_progress', nullable=False)  # 'in_progress', 'finished'
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    finished_at = db.Column(db.DateTime, nullable=True)

    subtest = db.relationship('Subtest', lazy='joined')


class ExamAnswer(db.Model):
    """Jawaban peserta per butir soal dalam sesi ujian"""
    __tablename__ = 'exam_answers'

    id = db.Column(db.Integer, primary_key=True)
    exam_session_id = db.Column(db.Integer, db.ForeignKey('exam_sessions.id', ondelete='CASCADE'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id', ondelete='CASCADE'), nullable=False)
    
    user_answer_json = db.Column(db.Text, default='null', nullable=True)
    is_correct = db.Column(db.Boolean, default=False, nullable=False)
    is_marked_doubtful = db.Column(db.Boolean, default=False, nullable=False)  # Ragu-ragu
    score_weight = db.Column(db.Float, default=0.0)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    question = db.relationship('Question', lazy='joined')

    @property
    def user_answer(self):
        try:
            return json.loads(self.user_answer_json) if self.user_answer_json else None
        except Exception:
            return self.user_answer_json

    @user_answer.setter
    def user_answer(self, value):
        self.user_answer_json = json.dumps(value, ensure_ascii=False)


class SubtestScore(db.Model):
    """Breakdown nilai per subtes untuk tiap peserta"""
    __tablename__ = 'subtest_scores'

    id = db.Column(db.Integer, primary_key=True)
    exam_session_id = db.Column(db.Integer, db.ForeignKey('exam_sessions.id', ondelete='CASCADE'), nullable=False)
    subtest_id = db.Column(db.Integer, db.ForeignKey('subtests.id', ondelete='CASCADE'), nullable=False)
    
    raw_correct = db.Column(db.Integer, default=0)
    raw_total = db.Column(db.Integer, default=0)
    irt_score = db.Column(db.Float, default=0.0)

    subtest = db.relationship('Subtest', lazy='joined')


class ActivityLog(db.Model):
    """Log aktivitas sistem untuk audit dan tracking visual penggunaan akun"""
    __tablename__ = 'activity_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=True)
    action = db.Column(db.String(64), nullable=False)  # 'LOGIN', 'REGISTER', 'START_EXAM', 'AUTOSAVE', 'SUBMIT_EXAM', 'CALC_IRT'
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<ActivityLog {self.action} User:{self.user_id}>"


def normalize_phone(phone):
    """08xx / +62 8xx / 62-8xx -> 628xx (format wa.me). None bila kosong."""
    digits = ''.join(ch for ch in (phone or '') if ch.isdigit())
    if digits.startswith('0'):
        digits = '62' + digits[1:]
    return digits or None


class PasswordResetRequest(db.Model):
    """Permintaan Lupa Password dari user. Diproses manual oleh admin (password sementara dikirim via WA/telepon)."""
    __tablename__ = 'password_reset_requests'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    contact_phone = db.Column(db.String(20), nullable=True)  # Nomor yang diisi di form (bisa berbeda dari profil)
    note = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='pending', nullable=False)  # 'pending', 'resolved', 'rejected'
    ip_address = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolved_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    user = db.relationship('User', foreign_keys=[user_id],
                           backref=db.backref('password_reset_requests', lazy='dynamic', cascade='all, delete-orphan'))
    resolved_by = db.relationship('User', foreign_keys=[resolved_by_id])

    @property
    def contact_differs(self):
        """Nomor di form berbeda dari nomor terdaftar: admin perlu verifikasi identitas dulu"""
        return bool(self.contact_phone) and normalize_phone(self.contact_phone) != normalize_phone(self.user.phone)
