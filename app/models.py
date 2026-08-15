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

    def is_active_now(self):
        now = datetime.now(timezone.utc)
        if not self.is_published:
            return False
        if self.start_time and now < self.start_time.replace(tzinfo=timezone.utc if self.start_time.tzinfo is None else self.start_time.tzinfo):
            return False
        if self.end_time and now > self.end_time.replace(tzinfo=timezone.utc if self.end_time.tzinfo is None else self.end_time.tzinfo):
            return False
        return True


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
    
    current_subtest_index = db.Column(db.Integer, default=0, nullable=False)  # Pointer to active subtest
    current_subtest_start = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))  # Start time for current subtest timer
    
    start_time = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    submitted_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default='in_progress', nullable=False)  # 'in_progress', 'completed', 'expired'
    
    total_raw_score = db.Column(db.Float, default=0.0)
    total_irt_score = db.Column(db.Float, default=0.0)
    national_rank = db.Column(db.Integer, nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)

    # Relationships
    answers = db.relationship('ExamAnswer', backref='exam_session', lazy='joined', cascade='all, delete-orphan')
    subtest_scores = db.relationship('SubtestScore', backref='exam_session', lazy='joined', cascade='all, delete-orphan')

    @property
    def answered_count(self):
        return sum(1 for a in self.answers if a.user_answer_json not in (None, '""', 'null', '[]'))

    def __repr__(self):
        return f"<ExamSession {self.id} User:{self.user_id} Status:{self.status}>"


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
