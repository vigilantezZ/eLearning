import math
import numpy as np
from scipy.optimize import minimize_scalar
from app import db
from app.models import ExamSession, ExamAnswer, Question, SubtestScore, TryoutPackage, Subtest

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


def calculate_irt_for_package(package_id):
    """
    Menghitung kalibrasi parameter butir soal (a, b, c) dan kemampuan peserta (theta -> Nilai Skala 200-1000)
    untuk seluruh peserta yang telah menyelesaikan paket tryout tertentu.
    """
    package = TryoutPackage.query.get(package_id)
    if not package:
        return False, "Paket tryout tidak ditemukan."

    completed_sessions = ExamSession.query.filter_by(
        tryout_package_id=package_id,
        status='completed'
    ).all()

    if not completed_sessions:
        return False, "Belum ada peserta yang menyelesaikan paket tryout ini."

    # Kumpulkan semua soal dalam paket ini terurut
    package_questions = [tq.question for tq in package.package_questions if tq.question is not None]
    if not package_questions:
        return False, "Paket tryout tidak memiliki butir soal."

    question_id_map = {q.id: idx for idx, q in enumerate(package_questions)}
    num_items = len(package_questions)
    num_students = len(completed_sessions)

    # 1. Bangun Matriks Jawaban (Response Matrix) X: [num_students, num_items]
    response_matrix = np.zeros((num_students, num_items), dtype=int)
    
    for s_idx, session in enumerate(completed_sessions):
        for answer in session.answers:
            if answer.question_id in question_id_map:
                q_idx = question_id_map[answer.question_id]
                # Verifikasi dan perbarui status kebenaran jawaban
                is_correct = answer.question.is_answer_correct(answer.user_answer)
                answer.is_correct = is_correct
                response_matrix[s_idx, q_idx] = 1 if is_correct else 0

    # Total raw scores per participant
    raw_scores = response_matrix.sum(axis=1)

    # 2. Kalibrasi Parameter Butir Soal (Item Calibration)
    item_params = {'a': [], 'b': [], 'c': []}
    
    for q_idx, question in enumerate(package_questions):
        item_responses = response_matrix[:, q_idx]
        p_val = np.mean(item_responses)  # Tingkat proporsi benar
        
        # Clip p_val agar logit tidak inf
        p_clipped = np.clip(p_val, 0.05, 0.95)
        
        # b parameter (Difficulty): logit terbalik (soal sulit -> p rendah -> b tinggi)
        b_calc = float(-np.log(p_clipped / (1.0 - p_clipped)))
        
        # a parameter (Discrimination): Point-biserial correlation
        std_raw = np.std(raw_scores)
        if std_raw > 0 and (p_val > 0 and p_val < 1):
            y1 = np.mean(raw_scores[item_responses == 1]) if np.sum(item_responses == 1) > 0 else 0
            y0 = np.mean(raw_scores[item_responses == 0]) if np.sum(item_responses == 0) > 0 else 0
            r_pbis = ((y1 - y0) / std_raw) * math.sqrt(p_val * (1.0 - p_val))
            # Normalisasi a ke rentang [0.5, 2.5]
            a_calc = float(np.clip(1.0 + r_pbis * 1.5, 0.4, 2.5))
        else:
            a_calc = 1.0
            
        # c parameter (Guessing): 0.20 untuk PG (5 pilihan), 0 untuk yang lain
        if question.question_type == 'pg':
            c_calc = 0.20
        else:
            c_calc = 0.0

        # Simpan ke database
        question.irt_a = round(a_calc, 3)
        question.irt_b = round(b_calc, 3)
        question.irt_c = round(c_calc, 3)
        
        item_params['a'].append(a_calc)
        item_params['b'].append(b_calc)
        item_params['c'].append(c_calc)

    # 3. Estimasi Kemampuan Theta Peserta (Overall & Per Subtest)
    subtests = {ts.subtest_id: ts.subtest for ts in package.package_subtests if ts.subtest}
    session_thetas = []

    for s_idx, session in enumerate(completed_sessions):
        # Overall Theta
        student_responses = response_matrix[s_idx, :]
        theta = estimate_theta(student_responses, item_params)
        session_thetas.append(theta)
        
        # Subtest-specific Theta & Breakdown
        for subtest_id, subtest in subtests.items():
            subtest_q_indices = [
                q_idx for q_idx, q in enumerate(package_questions) 
                if q.subtest_id == subtest_id
            ]
            if subtest_q_indices:
                sub_resp = student_responses[subtest_q_indices]
                sub_params = {
                    'a': [item_params['a'][i] for i in subtest_q_indices],
                    'b': [item_params['b'][i] for i in subtest_q_indices],
                    'c': [item_params['c'][i] for i in subtest_q_indices],
                }
                sub_theta = estimate_theta(sub_resp, sub_params)
                
                # Raw correct
                correct_count = int(np.sum(sub_resp))
                total_count = len(subtest_q_indices)
                
                # Cari atau buat record SubtestScore
                sub_score_rec = SubtestScore.query.filter_by(
                    exam_session_id=session.id,
                    subtest_id=subtest_id
                ).first()
                if not sub_score_rec:
                    sub_score_rec = SubtestScore(
                        exam_session_id=session.id,
                        subtest_id=subtest_id
                    )
                    db.session.add(sub_score_rec)
                
                sub_score_rec.raw_correct = correct_count
                sub_score_rec.raw_total = total_count
                # Subtest scaled score: base 500 + 100 * theta (clamped 200 - 1000)
                sub_score_rec.irt_score = round(float(np.clip(500.0 + (sub_theta * 100.0), 200.0, 1000.0)), 1)

    # 4. Standardisasi Nilai Total Skala UTBK (200 - 1000)
    theta_array = np.array(session_thetas)
    mean_theta = np.mean(theta_array)
    std_theta = np.std(theta_array)
    
    scaled_scores = []
    for theta in session_thetas:
        if std_theta > 0.01:
            # Standarisasi z-score -> Mean 600, SD 120 (Standard SNBT Distribution)
            z = (theta - mean_theta) / std_theta
            scaled = 600.0 + (z * 120.0)
        else:
            scaled = 500.0 + (theta * 100.0)
            
        scaled_clamped = float(np.clip(scaled, 200.0, 1000.0))
        scaled_scores.append(round(scaled_clamped, 1))

    # 5. Tetapkan Skor Akhir dan Peringkat Nasional
    session_score_pairs = list(zip(completed_sessions, scaled_scores, raw_scores))
    # Urutkan berdasarkan skor IRT tertinggi, lalu raw score
    session_score_pairs.sort(key=lambda x: (x[1], x[2]), reverse=True)

    for rank, (session, scaled_score, raw_score) in enumerate(session_score_pairs, start=1):
        session.total_irt_score = scaled_score
        session.total_raw_score = float(raw_score)
        session.national_rank = rank

    package.is_irt_calculated = True
    db.session.commit()
    
    return True, f"Kalkulasi IRT berhasil diselesaikan untuk {num_students} peserta dan {num_items} butir soal."
