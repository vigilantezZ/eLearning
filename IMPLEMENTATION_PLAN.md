# Dokumentasi & Rencana Implementasi: Website CBT Tryout (Flask + IRT Scoring)

Dokumen ini berisi spesifikasi arsitektur, struktur database, logika Item Response Theory (IRT), hierarki 3-Tier soal, hak akses peran (Role Management), dan alur pengerjaan CBT. File ini berfungsi sebagai referensi pengembangan utama (Single Source of Truth) bagi pengembang dan AI.

---

## 1. Arsitektur & Hierarki Soal 3-Tier (T1 - T3)

Struktur soal diorganisir dalam 3 tingkatan (Tier) fleksibel dengan sistem **Timer Mandiri per Subtes**:

| Tier | Nama Resmi | Contoh Standar UTBK/SNBT | Keterangan & Aturan Timer |
| :--- | :--- | :--- | :--- |
| **Tier 1 (T1)** | **Kelompok Ujian / Kategori Utama** (*Main Test Category*) | - Tes Potensi Skolastik (TPS)<br>- Tes Literasi & Penalaran<br>- Tes Kemampuan Akademik (TKA) | Mengelompokkan subtes ke dalam kategori besar/sesi. |
| **Tier 2 (T2)** | **Subtes / Bidang Ujian** (*Subtest / Subject Domain*) [Wajib] | 1. Kemampuan Penalaran Umum (30 mnt)<br>2. Pengetahuan & Pemahaman Umum (15 mnt)<br>3. Pemahaman Bacaan & Menulis (25 mnt)<br>4. Pengetahuan Kuantitatif (20 mnt)<br>5. Literasi Bahasa Indonesia (30 mnt)<br>6. Literasi Bahasa Inggris (30 mnt)<br>7. Penalaran Matematika (30 mnt) | **Wajib diisi & Memiliki Timer Independen**.<br>Saat timer habis, sistem auto-save, mengunci subtes aktif, dan otomatis berpindah ke subtes berikutnya (seperti sistem resmi UTBK). |
| **Tier 3 (T3)** | **Topik / Kompetensi / Materi Pokok** (*Topic / Competency*) [Opsional] | *Di bawah Penalaran:*<br>- Penalaran Induktif<br>- Penalaran Deduktif<br>- Penalaran Kuantitatif<br>*Di bawah Penalaran Matematika:*<br>- Aljabar & Fungsi<br>- Geometri & Pengukuran | **Opsional (Tergantung SPV)**.<br>Digunakan untuk memetakan analitik kelemahan/kelebihan peserta pada topik tertentu. |

---

## 2. Tipe Soal yang Didukung

Sistem mendukung 3 tipe soal interaktif:
1. **Pilihan Ganda (Single Choice / A - E)**: 1 jawaban benar dari pilihan opsi.
2. **Pilihan Berganda / Majemuk (Multiple Checkbox / Asosiasi)**: Peserta dapat memilih satu atau beberapa pilihan yang benar.
3. **Isian Singkat (Short Answer)**: Khusus angka atau kata/frasa sederhana (dengan normalisasi case-insensitive & whitespace trimming).

---

## 3. Matriks Peran & Hak Akses (User Management)

| Fitur / Modul | Peserta | Supervisor | Admin |
| :--- | :---: | :---: | :---: |
| Registrasi & Lengkapi Profil (Foto, Asal Sekolah, Kelas) | ✅ | ✅ | ✅ |
| Pilih & Kerjakan Paket Tryout (CBT Room + Timer) | ✅ | ❌ | ❌ |
| Lihat Hasil Skor IRT & Pembahasan Lengkap | ✅ (Paket Sendiri) | ✅ (Semua) | ✅ (Semua) |
| Manajemen Soal & Jawaban (T1-T3, Gambar, Pembahasan) | ❌ | ✅ | ✅ |
| Analisis Statistik, Distribusi Nilai & Leaderboard | ❌ | ✅ | ✅ |
| Live Monitor Ujian Peserta (Proctoring) | ❌ | ✅ | ✅ |
| Visual History & Timeline Pengerjaan Peserta | ❌ | ✅ | ✅ |
| Manajemen Pengguna (Tambah/Edit/Hapus Akun SPV/Peserta) | ❌ | ❌ | ✅ |
| Manajemen Paket Tryout (Jadwal, Timer Subtes, Soal) | ❌ | ❌ | ✅ |
| Eksekusi Kalkulasi Item Response Theory (IRT) Batch | ❌ | ❌ | ✅ |
| System Audit Trail & Activity Logs Lengkap | ❌ | ❌ | ✅ |

---

## 4. Engine Penilaian Item Response Theory (IRT)

Penilaian menggunakan model Item Response Theory (2PL / 3PL) standar UTBK SNBT:
1. **Model Karakteristik Butir Soal (Item Characteristic Curve - ICC)**:
   $$P_j(\theta) = c_j + \frac{1 - c_j}{1 + \exp\left(-a_j(\theta - b_j)\right)}$$
   - $\theta$: Tingkat kemampuan laten peserta (*latent ability*).
   - $b_j$: Tingkat kesulitan soal (*item difficulty*), dihitung dari proporsi jawaban benar empiris seluruh peserta ($P_j$).
   - $a_j$: Daya pembeda soal (*item discrimination*), dihitung dari korelasi biserial antara skor butir dan skor total peserta.
   - $c_j$: Tingkat tebakan (*pseudo-guessing parameter*), $c \approx 0.2$ untuk PG 5 opsi, $0$ untuk Isian/Checklist.

2. **Estimasi Kemampuan ($\theta$)**:
   - Diestimasi menggunakan optimasi fungsi log-likelihood berbasis vektor respons jawaban peserta terhadap seluruh butir soal.

3. **Standardisasi Skor Skala Nasional (200 - 1000)**:
   $$\text{Skor Akhir} = 500 + 100 \times \left(\frac{\theta - \bar{\theta}}{\sigma_{\theta}}\right)$$
   (Dibatasi pada rentang terstandarisasi 200 s/d 1000).

---

## 5. Skema Relasi Database (Entity Relationship)

- **`users`**: `id`, `username`, `email`, `phone`, `password_hash`, `full_name`, `school`, `grade`, `photo_filename`, `role` ('admin', 'supervisor', 'peserta'), `created_at`.
- **`test_groups` (Tier 1)**: `id`, `name`, `description`.
- **`subtests` (Tier 2)**: `id`, `test_group_id`, `name`, `default_duration_minutes`, `order_num`.
- **`topics` (Tier 3 - Opsional)**: `id`, `subtest_id`, `name`, `description`.
- **`questions`**: `id`, `subtest_id`, `topic_id` (nullable), `question_type` ('pg', 'pg_kompleks', 'isian'), `question_text`, `question_image`, `options_json`, `correct_answer_json`, `explanation_text`, `explanation_image`, `difficulty_level`, `irt_a`, `irt_b`, `irt_c`, `created_by`.
- **`tryout_packages`**: `id`, `title`, `description`, `banner_image`, `start_time`, `end_time`, `is_published`, `is_irt_calculated`, `created_by`.
- **`tryout_subtests`**: `id`, `tryout_package_id`, `subtest_id`, `duration_minutes`, `order_num`.
- **`tryout_questions`**: `id`, `tryout_package_id`, `question_id`, `order_num`.
- **`exam_sessions`**: `id`, `user_id`, `tryout_package_id`, `current_subtest_index`, `current_subtest_start`, `start_time`, `submitted_at`, `status` ('in_progress', 'completed', 'expired'), `total_raw_score`, `total_irt_score`, `national_rank`.
- **`exam_answers`**: `id`, `exam_session_id`, `question_id`, `user_answer_json`, `is_correct`, `is_marked_doubtful`, `updated_at`.
- **`subtest_scores`**: `id`, `exam_session_id`, `subtest_id`, `raw_correct`, `raw_total`, `irt_score`.
- **`activity_logs`**: `id`, `user_id`, `action`, `details`, `ip_address`, `created_at`.

---

## 6. Alur Pengerjaan Peserta (CBT Flow)

1. **Registrasi / Login & Profil**: Peserta melengkapi data identitas (email, nama, asal sekolah, kelas, foto profil).
2. **Katalog Paket Tryout**: Peserta memilih paket tryout aktif.
3. **CBT Exam Room**:
   - Menampilkan countdown timer subtes aktif.
   - Pilihan jawaban tersimpan secara instan (*auto-save*) via AJAX fetch tanpa reload halaman.
   - Navigasi tombol nomor soal dengan indikator status warna:
     - Hijau: Sudah dijawab
     - Kuning: Ragu-ragu
     - Abu-abu: Belum dijawab
     - Biru/Border: Soal aktif
   - Transisi otomatis ke subtes berikutnya saat waktu subtes habis.
4. **Submit & Kalkulasi Nilai**:
   - Setelah selesai, peserta diarahkan ke halaman tunggu / konfirmasi.
   - Admin mengeksekusi kalkulasi IRT batch untuk mengalibrasi tingkat kesulitan soal dari data respons seluruh peserta.
5. **Review Pembahasan & Leaderboard**:
   - Peserta dapat melihat skor per subtes, peringkat nasional, serta pembahasan mendalam per butir soal (kunci jawaban, analisis, dan tips penyelesaian).
