import json
from datetime import datetime, timezone, timedelta
from app import create_app, db
from app.models import (
    User, TestGroup, Subtest, Topic, Question, 
    TryoutPackage, TryoutSubtest, TryoutQuestion, 
    ExamSession, ExamAnswer, SubtestScore, ActivityLog
)
from app.irt_engine import calculate_irt_for_package

def seed_database():
    app = create_app()
    with app.app_context():
        # Drop all & create fresh tables
        db.drop_all()
        db.create_all()
        print("Database tables created cleanly.")

        # ==========================================
        # 1. Seed Users (Admin, Supervisor, Peserta)
        # ==========================================
        admin = User(
            username='admin',
            email='admin@bmp.or.id',
            full_name='Administrator Utama',
            phone='081234567890',
            school='Beasiswa Muda Purbalingga',
            grade='Admin',
            role='admin'
        )
        admin.set_password('admin123')
        db.session.add(admin)

        spv = User(
            username='supervisor',
            email='supervisor@bmp.or.id',
            full_name='Supervisor CBT BMP',
            phone='081298765432',
            school='Departemen Akademik BMP',
            grade='Supervisor',
            role='supervisor'
        )
        spv.set_password('spv123')
        db.session.add(spv)

        students_data = [
            ('peserta1', 'peserta1@gmail.com', 'Budi Pratama', 'SMAN 1 Jakarta', '12 SMA / SMK', '081311112222'),
            ('peserta2', 'peserta2@gmail.com', 'Siti Rahma', 'SMAN 3 Bandung', '12 SMA / SMK', '081333334444'),
            ('peserta3', 'peserta3@gmail.com', 'Ahmad Fauzi', 'SMA Taruna Nusantara', 'Gap Year', '081355556666'),
            ('peserta4', 'peserta4@gmail.com', 'Dewi Lestari', 'SMAN 8 Jakarta', '12 SMA / SMK', '081377778888'),
            ('peserta5', 'peserta5@gmail.com', 'Rian Hidayat', 'SMA Labschool Kebayoran', '12 SMA / SMK', '081399990000'),
        ]

        created_students = []
        for uname, email, fname, school, grade, phone in students_data:
            st = User(
                username=uname,
                email=email,
                full_name=fname,
                school=school,
                grade=grade,
                phone=phone,
                role='peserta'
            )
            st.set_password('peserta123')
            db.session.add(st)
            created_students.append(st)

        db.session.commit()
        print("Users seeded (Admin, Supervisor, 5 Peserta).")

        # ==========================================
        # 2. Seed 3-Tier Hierarchy (T1, T2, T3)
        # ==========================================
        # Tier 1: Kelompok Ujian
        t1_tps = TestGroup(
            name='Tes Potensi Skolastik (TPS)',
            code='TPS',
            description='Mengukur kemampuan kognitif yang dianggap penting untuk keberhasilan di pendidikan tinggi.',
            order_num=1
        )
        t1_literasi = TestGroup(
            name='Tes Literasi & Penalaran',
            code='TL',
            description='Mengukur kemampuan bernalar dalam konteks bahasa dan matematika.',
            order_num=2
        )
        db.session.add_all([t1_tps, t1_literasi])
        db.session.commit()

        # Tier 2: 7 Subtes Standar UTBK SNBT
        sub_pu = Subtest(test_group_id=t1_tps.id, name='Kemampuan Penalaran Umum (PU)', code='PU', default_duration_minutes=30, order_num=1)
        sub_ppu = Subtest(test_group_id=t1_tps.id, name='Pengetahuan dan Pemahaman Umum (PPU)', code='PPU', default_duration_minutes=15, order_num=2)
        sub_pbm = Subtest(test_group_id=t1_tps.id, name='Pemahaman Bacaan dan Menulis (PBM)', code='PBM', default_duration_minutes=25, order_num=3)
        sub_pk = Subtest(test_group_id=t1_tps.id, name='Pengetahuan Kuantitatif (PK)', code='PK', default_duration_minutes=20, order_num=4)

        sub_indo = Subtest(test_group_id=t1_literasi.id, name='Literasi dalam Bahasa Indonesia', code='L-IND', default_duration_minutes=30, order_num=5)
        sub_ing = Subtest(test_group_id=t1_literasi.id, name='Literasi dalam Bahasa Inggris', code='L-ENG', default_duration_minutes=30, order_num=6)
        sub_pm = Subtest(test_group_id=t1_literasi.id, name='Penalaran Matematika (PM)', code='PM', default_duration_minutes=30, order_num=7)

        db.session.add_all([sub_pu, sub_ppu, sub_pbm, sub_pk, sub_indo, sub_ing, sub_pm])
        db.session.commit()

        # Tier 3: Topik / Kompetensi (Opsional)
        t3_induktif = Topic(subtest_id=sub_pu.id, name='Penalaran Induktif', description='Menarik simpulan dari pola kejadian/fakta')
        t3_deduktif = Topic(subtest_id=sub_pu.id, name='Penalaran Deduktif', description='Menarik simpulan logis berdasarkan premis mutlak')
        t3_kuanti_pu = Topic(subtest_id=sub_pu.id, name='Penalaran Kuantitatif Logis', description='Pola bilangan dan grafik kuantitatif')
        
        t3_aljabar = Topic(subtest_id=sub_pk.id, name='Aljabar & Fungsi', description='Persamaan, pertidaksamaan, dan fungsi kuadrat')
        t3_geometri = Topic(subtest_id=sub_pk.id, name='Geometri & Pengukuran', description='Sudut, luas bangun datar, dan volume')
        
        t3_lit_bacaan = Topic(subtest_id=sub_indo.id, name='Ide Pokok & Simpulan Teks', description='Analisis isi bacaan kritis')
        t3_mat_nyata = Topic(subtest_id=sub_pm.id, name='Aplikasi Masalah Nyata', description='Pemodelan matematika kehidupan sehari-hari')

        db.session.add_all([t3_induktif, t3_deduktif, t3_kuanti_pu, t3_aljabar, t3_geometri, t3_lit_bacaan, t3_mat_nyata])
        db.session.commit()
        print("3-Tier Hierarchy (T1 - T3) and 7 Subtests seeded.")

        # ==========================================
        # 3. Seed Questions (All 3 Question Types)
        # ==========================================
        sample_questions = [
            # Soal 1: PU - Pilihan Ganda (A-E)
            Question(
                subtest_id=sub_pu.id,
                topic_id=t3_deduktif.id,
                question_type='pg',
                question_text=(
                    "Semua peserta tryout yang lolos passing grade akan mendapatkan sertifikat prestasi. "
                    "Sebagian siswa kelas 12 SMAN 1 tidak mendapatkan sertifikat prestasi.\n\n"
                    "Simpulan yang PALING TEPAT adalah..."
                ),
                options_json=json.dumps([
                    {'key': 'A', 'text': 'Semua siswa kelas 12 SMAN 1 tidak lolos passing grade.'},
                    {'key': 'B', 'text': 'Sebagian siswa kelas 12 SMAN 1 tidak lolos passing grade.'},
                    {'key': 'C', 'text': 'Semua peserta tryout yang tidak mendapat sertifikat adalah siswa SMAN 1.'},
                    {'key': 'D', 'text': 'Sebagian siswa yang mendapat sertifikat bukan peserta tryout.'},
                    {'key': 'E', 'text': 'Tidak dapat ditarik simpulan yang pasti.'}
                ], ensure_ascii=False),
                correct_answer_json=json.dumps('B', ensure_ascii=False),
                explanation_text=(
                    "Berdasarkan silogisme kategoris:\n"
                    "Premis 1: Lolos -> Sertifikat\n"
                    "Premis 2: Sebagian siswa SMAN 1 tidak mendapat sertifikat (~Sertifikat).\n"
                    "Modus Tollens pada sebagian kelompok: Jika tidak mendapat sertifikat, maka tidak lolos passing grade.\n"
                    "Maka simpulan yang valid: Sebagian siswa kelas 12 SMAN 1 tidak lolos passing grade (Pilihan B)."
                ),
                difficulty_level='sedang',
                created_by_id=spv.id
            ),

            # Soal 2: PU - Pilihan Berganda (Checklist Kompleks)
            Question(
                subtest_id=sub_pu.id,
                topic_id=t3_induktif.id,
                question_type='pg_kompleks',
                question_text=(
                    "Diberikan deret bilangan: 3, 6, 12, 24, 48, ...\n"
                    "Manakah di antara pernyataan berikut yang BENAR terkait pola bilangan tersebut? "
                    "(Pilihlah semua jawaban yang benar)"
                ),
                options_json=json.dumps([
                    {'key': 'A', 'text': 'Rasio antar suku bernilai tetap, yaitu 2.'},
                    {'key': 'B', 'text': 'Suku ke-7 dari deret tersebut adalah 192.'},
                    {'key': 'C', 'text': 'Deret tersebut merupakan barisan aritmatika dengan beda 3.'},
                    {'key': 'D', 'text': 'Rumus suku ke-n adalah Un = 3 * (2^(n-1)).'},
                    {'key': 'E', 'text': 'Jumlah 4 suku pertama deret tersebut adalah 45.'}
                ], ensure_ascii=False),
                correct_answer_json=json.dumps(['A', 'B', 'D', 'E'], ensure_ascii=False),
                explanation_text=(
                    "Analisis butir pernyataan:\n"
                    "A. BENAR: Rasio r = 6/3 = 12/6 = 2.\n"
                    "B. BENAR: U7 = 3 * (2^6) = 3 * 64 = 192.\n"
                    "C. SALAH: Barisan tersebut adalah geometri, bukan aritmatika.\n"
                    "D. BENAR: Rumus Un barisan geometri adalah a * r^(n-1) = 3 * (2^(n-1)).\n"
                    "E. BENAR: S4 = 3 + 6 + 12 + 24 = 45.\n"
                    "Maka jawaban benar adalah: A, B, D, E."
                ),
                difficulty_level='sedang',
                created_by_id=spv.id
            ),

            # Soal 3: PK - Isian Singkat (Angka)
            Question(
                subtest_id=sub_pk.id,
                topic_id=t3_aljabar.id,
                question_type='isian',
                question_text=(
                    "Jika fungsi f(x) = 2x^2 - 4x + 7 memiliki nilai minimum f(p) = q, "
                    "berapakah nilai dari p + q?\n"
                    "(Tuliskan jawaban hanya berupa bilangan angka)"
                ),
                options_json='[]',
                correct_answer_json=json.dumps(['6', '6.0', 'enam'], ensure_ascii=False),
                explanation_text=(
                    "Fungsi kuadrat f(x) = 2x^2 - 4x + 7 dengan a=2, b=-4, c=7.\n"
                    "Titik puncak x_p = -b / (2a) = -(-4) / (2*2) = 4 / 4 = 1. Jadi p = 1.\n"
                    "Nilai minimum q = f(1) = 2(1)^2 - 4(1) + 7 = 2 - 4 + 7 = 5. Jadi q = 5.\n"
                    "Nilai p + q = 1 + 5 = 6."
                ),
                difficulty_level='sulit',
                created_by_id=spv.id
            ),

            # Soal 4: PK - Pilihan Ganda (A-E)
            Question(
                subtest_id=sub_pk.id,
                topic_id=t3_geometri.id,
                question_type='pg',
                question_text=(
                    "Sebuah persegi panjang memiliki keliling 48 cm. Jika panjangnya 6 cm lebih panjang dari lebarnya, "
                    "berapakah luas persegi panjang tersebut?"
                ),
                options_json=json.dumps([
                    {'key': 'A', 'text': '125 cm²'},
                    {'key': 'B', 'text': '135 cm²'},
                    {'key': 'C', 'text': '144 cm²'},
                    {'key': 'D', 'text': '150 cm²'},
                    {'key': 'E', 'text': '160 cm²'}
                ], ensure_ascii=False),
                correct_answer_json=json.dumps('B', ensure_ascii=False),
                explanation_text=(
                    "Misalkan lebar = l, maka panjang p = l + 6.\n"
                    "Keliling = 2(p + l) = 48 -> p + l = 24.\n"
                    "(l + 6) + l = 24 -> 2l = 18 -> l = 9 cm.\n"
                    "Maka panjang p = 9 + 6 = 15 cm.\n"
                    "Luas = p * l = 15 * 9 = 135 cm² (Pilihan B)."
                ),
                difficulty_level='mudah',
                created_by_id=spv.id
            ),

            # Soal 5: Literasi Bahasa Indonesia - Pilihan Ganda (A-E)
            Question(
                subtest_id=sub_indo.id,
                topic_id=t3_lit_bacaan.id,
                question_type='pg',
                question_text=(
                    "Pemberian subsidi kendaraan listrik bertujuan untuk mempercepat transisi energi bersih serta menurunkan tingkat polusi emisi karbon di kota-kota besar. Namun, sejumlah pengamat menilai bahwa pembangunan infrastruktur transportasi publik berbasis rel dan bus listrik jauh lebih mendesak dan berdampak luas bagi masyarakat kelas menengah ke bawah.\n\n"
                    "Gagasan utama paragraf tersebut adalah..."
                ),
                options_json=json.dumps([
                    {'key': 'A', 'text': 'Kegagalan subsidi kendaraan listrik dalam menurunkan polusi.'},
                    {'key': 'B', 'text': 'Pentingnya subsidi kendaraan listrik sebagai solusi utama energi bersih.'},
                    {'key': 'C', 'text': 'Perbedaan pandangan terkait prioritas subsidi kendaraan listrik versus transportasi publik.'},
                    {'key': 'D', 'text': 'Kondisi masyarakat menengah bawah yang tidak mampu membeli kendaraan listrik.'},
                    {'key': 'E', 'text': 'Kebutuhan mendesak pengadaan bus listrik di seluruh kota besar di Indonesia.'}
                ], ensure_ascii=False),
                correct_answer_json=json.dumps('C', ensure_ascii=False),
                explanation_text=(
                    "Teks menyajikan tujuan pemerintah memberikan subsidi kendaraan listrik, diikuti oleh pandangan pengamat mengenai urgensi transportasi publik. Maka gagasan utama adalah perbedaan pandangan mengenai prioritas kebijakan antara subsidi kendaraan pribadi listrik versus angkutan publik (Pilihan C)."
                ),
                difficulty_level='sedang',
                created_by_id=spv.id
            ),

            # Soal 6: Penalaran Matematika - Isian Singkat (Angka)
            Question(
                subtest_id=sub_pm.id,
                topic_id=t3_mat_nyata.id,
                question_type='isian',
                question_text=(
                    "Sebuah tangki air berbentuk silinder terisi 3/5 bagian. Setelah diambil sebanyak 12 liter air, "
                    "tangki tersebut kini tersisa 1/2 bagian. Berapakah kapasitas total tangki air tersebut dalam satuan liter?\n"
                    "(Tuliskan jawaban hanya berupa angka)"
                ),
                options_json='[]',
                correct_answer_json=json.dumps(['120', '120.0', 'seratus dua puluh'], ensure_ascii=False),
                explanation_text=(
                    "Misalkan kapasitas tangki = T.\n"
                    "(3/5)T - 12 = (1/2)T\n"
                    "(3/5 - 1/2)T = 12\n"
                    "(6/10 - 5/10)T = 12\n"
                    "(1/10)T = 12 -> T = 120 Liter."
                ),
                difficulty_level='sedang',
                created_by_id=spv.id
            )
        ]

        for q in sample_questions:
            db.session.add(q)
        db.session.commit()
        print(f"Sample questions created ({len(sample_questions)} items across 3 question types).")

        # ==========================================
        # 4. Seed Tryout Package with Subtest Timers
        # ==========================================
        pkg = TryoutPackage(
            title='Simulasi Akbar UTBK-SNBT 2026 - Paket 1',
            description=(
                'Simulasi lengkap seleksi nasional berbasis tes (SNBT) berstandar resmi BP3/BPPP Kemendikbud. '
                'Dilengkapi sistem timer mandiri per subtes, variasi soal PG, PG Kompleks, dan Isian, '
                'serta pembobotan nilai Item Response Theory (IRT).'
            ),
            is_published=True,
            created_by_id=admin.id
        )
        db.session.add(pkg)
        db.session.flush()

        # Link subtests with dedicated duration timers
        subtest_timer_configs = [
            (sub_pu.id, 25, 1),
            (sub_pk.id, 20, 2),
            (sub_indo.id, 25, 3),
            (sub_pm.id, 25, 4),
        ]

        for sub_id, duration, order_idx in subtest_timer_configs:
            ts = TryoutSubtest(
                tryout_package_id=pkg.id,
                subtest_id=sub_id,
                duration_minutes=duration,
                order_num=order_idx
            )
            db.session.add(ts)

        # Link all created sample questions to package
        for q_order, q in enumerate(sample_questions, start=1):
            tq = TryoutQuestion(
                tryout_package_id=pkg.id,
                question_id=q.id,
                order_num=q_order
            )
            db.session.add(tq)

        db.session.commit()
        print(f"Tryout Package '{pkg.title}' created with dedicated subtest timers.")

        # ==========================================
        # 5. Seed Realistic Completed Exam Sessions for IRT Calibration Demo
        # ==========================================
        # Create completed sessions for peserta2, peserta3, peserta4, peserta5 with varying answers
        # Peserta 2 (High ability - mostly correct)
        p2_answers = {'1': 'B', '2': ['A', 'B', 'D', 'E'], '3': '6', '4': 'B', '5': 'C', '6': '120'}
        # Peserta 3 (Medium-High ability)
        p3_answers = {'1': 'B', '2': ['A', 'B', 'D'], '3': '6', '4': 'B', '5': 'C', '6': '100'}
        # Peserta 4 (Medium ability)
        p4_answers = {'1': 'A', '2': ['A', 'B', 'D', 'E'], '3': '5', '4': 'B', '5': 'C', '6': '120'}
        # Peserta 5 (Beginner ability)
        p5_answers = {'1': 'C', '2': ['A', 'C'], '3': '12', '4': 'A', '5': 'B', '6': '50'}

        simulation_students = [
            (created_students[1], p2_answers),  # peserta2
            (created_students[2], p3_answers),  # peserta3
            (created_students[3], p4_answers),  # peserta4
            (created_students[4], p5_answers),  # peserta5
        ]

        now = datetime.now(timezone.utc)

        for student, ans_map in simulation_students:
            session = ExamSession(
                user_id=student.id,
                tryout_package_id=pkg.id,
                current_subtest_index=len(subtest_timer_configs),
                start_time=now - timedelta(minutes=60),
                submitted_at=now - timedelta(minutes=5),
                status='completed',
                ip_address='127.0.0.1'
            )
            db.session.add(session)
            db.session.flush()

            raw_correct = 0
            for q_idx, q in enumerate(sample_questions, start=1):
                user_choice = ans_map.get(str(q_idx))
                is_correct = q.is_answer_correct(user_choice)
                if is_correct:
                    raw_correct += 1

                ans_record = ExamAnswer(
                    exam_session_id=session.id,
                    question_id=q.id,
                    user_answer_json=json.dumps(user_choice, ensure_ascii=False) if user_choice is not None else 'null',
                    is_correct=is_correct,
                    is_marked_doubtful=False
                )
                db.session.add(ans_record)

            session.total_raw_score = float(raw_correct)

        db.session.commit()
        print("Completed participant sessions seeded for IRT demonstration.")

        # Run IRT Calibration on the package right away so initial scores are ready
        success, msg = calculate_irt_for_package(pkg.id)
        print(f"IRT Calibration Engine Run: {msg}")

        print("\n==========================================")
        print("SEEDING COMPLETED SUCCESSFULLY!")
        print("Credentials:")
        print("  Admin       : admin / admin123")
        print("  Supervisor  : supervisor / spv123")
        print("  Peserta Demo: peserta1 / peserta123")
        print("==========================================\n")

if __name__ == '__main__':
    seed_database()
