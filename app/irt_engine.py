import math
from datetime import datetime, timezone
import numpy as np
from scipy.optimize import minimize_scalar
from app import db
from app.models import ExamSession, ExamAnswer, Question, SubtestScore, TryoutPackage, Subtest
from app.subtest_flow import close_idle_sessions

def icc_probability(theta, a, b, c=0.0):
    """
    3-Parameter Logistic (3PL) Item Characteristic Curve:
    P(theta) = c + (1 - c) / (1 + exp(-a * (theta - b)))
    """
    z = a * (theta - b)
    # Clip z to prevent numerical overflow in exp
    z = np.clip(z, -35.0, 35.0)
    return c + (1.0 - c) / (1.0 + np.exp(-z))


def log_posterior_ability(theta, responses, item_params):
    """
    Computes negative log-posterior of theta with standard normal prior N(0,1) for MAP estimation
    """
    log_lik = 0.0
    for is_correct, a, b, c in zip(responses, item_params['a'], item_params['b'], item_params['c']):
        p = icc_probability(theta, a, b, c)
        p = np.clip(p, 1e-7, 1.0 - 1e-7)
        if is_correct:
            log_lik += math.log(p)
        else:
            log_lik += math.log(1.0 - p)
    
    # Log-prior log N(0, 1) = -0.5 * theta^2 + const
    log_prior = -0.5 * (theta ** 2)
    return -(log_lik + log_prior)


def estimate_theta(responses, item_params):
    """
    Estimates theta (ability latent) using Maximum A Posteriori (MAP) bounded in [-4.0, 4.0]
    """
    if responses is None or len(responses) == 0:
        return 0.0
    
    # If all 0 or all 1, optimization still converges thanks to N(0,1) prior
    res = minimize_scalar(
        log_posterior_ability,
        bounds=(-4.0, 4.0),
        args=(responses, item_params),
        method='bounded'
    )
    return float(res.x) if res.success else 0.0


def assign_national_ranks(package_id):
    """
    Menyusun ulang peringkat dari skor IRT yang tersimpan, tanpa kalibrasi ulang.
    Yang berhak: akun peserta (bukan admin/supervisor), sudah dinilai IRT, dan mengerjakan seluruh subtes.
    Mengembalikan jumlah sesi yang mendapat peringkat; commit diserahkan ke pemanggil.
    """
    sessions = ExamSession.query.filter_by(
        tryout_package_id=package_id,
        status='completed'
    ).order_by(ExamSession.id).all()

    ranked_sessions = []
    for session in sessions:
        session.national_rank = None
        if (session.user.is_peserta and session.irt_scored_at
                and session.total_irt_score is not None and session.is_full_attempt):
            ranked_sessions.append(session)

    # Urutkan berdasarkan skor IRT tertinggi, lalu raw score
    ranked_sessions.sort(key=lambda s: (s.total_irt_score, s.total_raw_score), reverse=True)
    for rank, session in enumerate(ranked_sessions, start=1):
        session.national_rank = rank
    return len(ranked_sessions)


def calculate_irt_for_package(package_id):
    """
    Menghitung kalibrasi parameter butir soal (a, b, c) dan kemampuan peserta (theta -> Nilai Skala 200-1000)
    untuk seluruh peserta yang telah menyelesaikan paket tryout tertentu.

    Subtes yang tidak dikerjakan peserta (tidak pernah dibuka) diperlakukan sebagai data kosong:
    tidak ikut kalibrasi butir dan tidak mendapat skor. Soal yang dikosongkan di subtes yang dibuka tetap dihitung salah.

    Sesi akun admin/supervisor (uji coba) tetap dinilai, tetapi tidak ikut kalibrasi butir dan tidak masuk peringkat.
    """
    package = TryoutPackage.query.get(package_id)
    if not package:
        return False, "Paket tryout tidak ditemukan."

    # Sesi yang ditinggal di menu pilih subtes ikut ditutup agar nilainya keluar
    closed_count, running_count = close_idle_sessions(package)
    db.session.flush()

    running_note = ""
    if running_count:
        running_note = f" {running_count} peserta masih mengerjakan subtes dan belum diikutkan; jalankan ulang setelah mereka selesai."

    completed_sessions = ExamSession.query.filter_by(
        tryout_package_id=package_id,
        status='completed'
    ).order_by(ExamSession.id).all()

    if not completed_sessions:
        return False, "Belum ada peserta yang menyelesaikan paket tryout ini." + running_note

    # Kumpulkan semua soal dalam paket ini terurut
    package_questions = [tq.question for tq in package.package_questions if tq.question is not None]
    if not package_questions:
        return False, "Paket tryout tidak memiliki butir soal."

    question_id_map = {q.id: idx for idx, q in enumerate(package_questions)}
    num_items = len(package_questions)
    num_students = len(completed_sessions)

    subtest_item_indices = {}
    for q_idx, q in enumerate(package_questions):
        subtest_item_indices.setdefault(q.subtest_id, []).append(q_idx)

    # 1. Bangun Matriks Jawaban (Response Matrix) X: [num_students, num_items]
    #    1 = benar, 0 = salah/kosong, NaN = subtes tidak dikerjakan
    response_matrix = np.full((num_students, num_items), np.nan)

    for s_idx, session in enumerate(completed_sessions):
        attempted = session.attempted_subtest_ids
        for subtest_id, indices in subtest_item_indices.items():
            if subtest_id in attempted:
                response_matrix[s_idx, indices] = 0.0

        for answer in session.answers:
            if answer.question_id in question_id_map:
                q_idx = question_id_map[answer.question_id]
                # Verifikasi dan perbarui status kebenaran jawaban
                is_correct = answer.question.is_answer_correct(answer.user_answer)
                answer.is_correct = is_correct
                if not np.isnan(response_matrix[s_idx, q_idx]):
                    response_matrix[s_idx, q_idx] = 1.0 if is_correct else 0.0

    observed = ~np.isnan(response_matrix)
    # Hanya jawaban akun peserta yang dipakai untuk kalibrasi butir
    participant_rows = np.array([session.user.is_peserta for session in completed_sessions])
    num_participants = int(participant_rows.sum())

    # 2. Kalibrasi Parameter Butir Soal (Item Calibration)
    item_params = {'a': [], 'b': [], 'c': []}

    for q_idx, question in enumerate(package_questions):
        # c parameter (Guessing): 0.20 untuk PG (5 pilihan), 0 untuk yang lain
        c_calc = 0.20 if question.question_type == 'pg' else 0.0

        takers = observed[:, q_idx] & participant_rows
        if not takers.any():
            # Tidak ada peserta yang mengerjakan subtes soal ini: parameter tersimpan tidak diubah
            item_params['a'].append(question.irt_a if question.irt_a is not None else 1.0)
            item_params['b'].append(question.irt_b if question.irt_b is not None else 0.0)
            item_params['c'].append(c_calc)
            continue

        item_responses = response_matrix[takers, q_idx]
        p_val = np.mean(item_responses)  # Tingkat proporsi benar

        # Clip p_val agar logit tidak inf
        p_clipped = np.clip(p_val, 0.05, 0.95)

        # b parameter (Difficulty): logit terbalik (soal sulit -> p rendah -> b tinggi)
        b_calc = float(-np.log(p_clipped / (1.0 - p_clipped)))

        # a parameter (Discrimination): Point-biserial correlation terhadap skor subtes yang sama
        subtest_scores = response_matrix[takers][:, subtest_item_indices[question.subtest_id]].mean(axis=1)
        std_score = np.std(subtest_scores)
        if std_score > 0 and (p_val > 0 and p_val < 1):
            y1 = np.mean(subtest_scores[item_responses == 1])
            y0 = np.mean(subtest_scores[item_responses == 0])
            r_pbis = ((y1 - y0) / std_score) * math.sqrt(p_val * (1.0 - p_val))
            # Normalisasi a ke rentang [0.5, 2.5]
            a_calc = float(np.clip(1.0 + r_pbis * 1.5, 0.4, 2.5))
        else:
            a_calc = 1.0

        # Simpan ke database
        question.irt_a = round(a_calc, 3)
        question.irt_b = round(b_calc, 3)
        question.irt_c = round(c_calc, 3)

        item_params['a'].append(a_calc)
        item_params['b'].append(b_calc)
        item_params['c'].append(c_calc)

    # 3. Estimasi Kemampuan Theta Peserta per Subtes yang dikerjakan
    package_subtest_ids = [ts.subtest_id for ts in package.package_subtests if ts.subtest]
    scored_at = datetime.now(timezone.utc)

    for s_idx, session in enumerate(completed_sessions):
        attempted = session.attempted_subtest_ids
        existing_scores = {sc.subtest_id: sc for sc in session.subtest_scores}
        session_subtest_scores = []

        for subtest_id in package_subtest_ids:
            subtest_q_indices = subtest_item_indices.get(subtest_id, [])
            sub_score_rec = existing_scores.pop(subtest_id, None)

            if subtest_id not in attempted or not subtest_q_indices:
                # Subtes tidak dikerjakan: tidak mendapat skor
                if sub_score_rec:
                    session.subtest_scores.remove(sub_score_rec)
                continue

            sub_resp = response_matrix[s_idx, subtest_q_indices]
            sub_params = {
                'a': [item_params['a'][i] for i in subtest_q_indices],
                'b': [item_params['b'][i] for i in subtest_q_indices],
                'c': [item_params['c'][i] for i in subtest_q_indices],
            }
            sub_theta = estimate_theta(sub_resp, sub_params)

            if not sub_score_rec:
                sub_score_rec = SubtestScore(subtest_id=subtest_id)
                session.subtest_scores.append(sub_score_rec)

            sub_score_rec.raw_correct = int(np.sum(sub_resp))
            sub_score_rec.raw_total = len(subtest_q_indices)
            # Subtest scaled score: base 500 + 100 * theta (clamped 200 - 1000)
            sub_score_rec.irt_score = round(float(np.clip(500.0 + (sub_theta * 100.0), 200.0, 1000.0)), 1)
            session_subtest_scores.append(sub_score_rec.irt_score)

        # Skor subtes yang sudah tidak ada di paket ikut dibersihkan
        for stale_rec in existing_scores.values():
            session.subtest_scores.remove(stale_rec)

        # 4. Skor Total = rata-rata skor subtes (seperti UTBK)
        session.total_raw_score = float(np.nansum(response_matrix[s_idx]))
        session.total_irt_score = round(float(np.mean(session_subtest_scores)), 1) if session_subtest_scores else None
        session.irt_scored_at = scored_at

    # 5. Peringkat Nasional hanya untuk akun peserta yang mengerjakan seluruh subtes
    ranked_count = assign_national_ranks(package_id)

    package.is_irt_calculated = True
    db.session.commit()

    message = (
        f"Kalkulasi IRT berhasil diselesaikan untuk {num_participants} peserta dan {num_items} butir soal "
        f"({ranked_count} peserta mengerjakan lengkap dan masuk peringkat)."
    )
    staff_count = num_students - num_participants
    if staff_count:
        message += (
            f" {staff_count} sesi akun admin/supervisor tetap dinilai, "
            "tetapi tidak ikut kalibrasi soal maupun peringkat."
        )
    if closed_count:
        message += f" {closed_count} sesi yang belum diselesaikan peserta ditutup otomatis."
    return True, message + running_note
