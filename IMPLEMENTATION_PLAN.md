# Dokumentasi & Rencana Implementasi: Website CBT Tryout (Flask + IRT Scoring)

Dokumen ini berisi spesifikasi arsitektur, struktur database, logika Item Response Theory (IRT), hierarki 3-Tier soal, hak akses peran (Role Management), dan alur pengerjaan CBT. File ini berfungsi sebagai referensi pengembangan utama (Single Source of Truth) bagi pengembang dan AI.

---

## 1. Arsitektur & Hierarki Soal 3-Tier (T1 - T3)

Struktur soal diorganisir dalam 3 tingkatan (Tier) fleksibel dengan sistem **Timer Mandiri per Subtes**:

| Tier | Nama Resmi | Contoh Standar UTBK/SNBT | Keterangan & Aturan Timer |
| :--- | :--- | :--- | :--- |
| **Tier 1 (T1)** | **Kelompok Ujian / Kategori Utama** (*Main Test Category*) | - Tes Potensi Skolastik (TPS)<br>- Tes Literasi & Penalaran<br>- Tes Kemampuan Akademik (TKA) | Mengelompokkan subtes ke dalam kategori besar/sesi. |
| **Tier 2 (T2)** | **Subtes / Bidang Ujian** (*Subtest / Subject Domain*) [Wajib] | 1. Kemampuan Penalaran Umum (30 mnt)<br>2. Pengetahuan & Pemahaman Umum (15 mnt)<br>3. Pemahaman Bacaan & Menulis (25 mnt)<br>4. Pengetahuan Kuantitatif (20 mnt)<br>5. Literasi Bahasa Indonesia (30 mnt)<br>6. Literasi Bahasa Inggris (30 mnt)<br>7. Penalaran Matematika (30 mnt) | **Wajib diisi & Memiliki Timer Independen**.<br>Saat timer habis, sistem auto-save, mengunci subtes aktif, dan peserta kembali ke menu pilih subtes. |
| **Tier 3 (T3)** | **Topik / Kompetensi / Materi Pokok** (*Topic / Competency*) [Opsional] | *Di bawah Penalaran:*<br>- Penalaran Induktif<br>- Penalaran Deduktif<br>- Penalaran Kuantitatif<br>*Di bawah Penalaran Matematika:*<br>- Aljabar & Fungsi<br>- Geometri & Pengukuran | **Opsional (Tergantung SPV)**.<br>Digunakan untuk memetakan analitik kelemahan/kelebihan peserta pada topik tertentu.<br>Topik baru bisa ditambah langsung dari form soal (opsi *+ Tambah topik baru*) atau di halaman *Kelola Subtes & Topik*; nama yang sama dalam satu subtes dipakai ulang, bukan dibuat dobel. |

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
| Ajukan Lupa Password (dari halaman login) | ✅ | ✅ | ✅ |
| Pilih & Kerjakan Paket Tryout (CBT Room + Timer) | ✅ | ❌ | ❌ |
| Lihat Hasil Skor IRT & Pembahasan Lengkap | ✅ (Paket Sendiri) | ✅ (Semua) | ✅ (Semua) |
| Manajemen Soal & Jawaban (T1-T3, Gambar, Pembahasan) | ❌ | ✅ | ✅ |
| Analisis Statistik, Distribusi Nilai & Leaderboard | ❌ | ✅ | ✅ |
| Live Monitor Ujian Peserta (Proctoring) | ❌ | ✅ | ✅ |
| Visual History & Timeline Pengerjaan Peserta | ❌ | ✅ | ✅ |
| Manajemen Pengguna (Tambah/Edit/Hapus Akun SPV/Peserta) | ❌ | ❌ | ✅ |
| Proses Permintaan Lupa Password (Reset / Tolak) | ❌ | ❌ | ✅ |
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
   - $a_j$: Daya pembeda soal (*item discrimination*), dihitung dari korelasi point-biserial antara skor butir dan skor peserta pada subtes yang sama.
   - $c_j$: Tingkat tebakan (*pseudo-guessing parameter*), $c \approx 0.2$ untuk PG 5 opsi, $0$ untuk Isian/Checklist.

2. **Data Subtes yang Tidak Dikerjakan**:
   - Subtes yang **tidak pernah dibuka** peserta dianggap data kosong: tidak ikut kalibrasi butir, tidak diestimasi, dan tidak mendapat skor.
   - Soal yang **dikosongkan** di subtes yang dibuka tetap dihitung salah.

3. **Estimasi Kemampuan ($\theta$) per Subtes**:
   - Diestimasi dengan MAP (prior $N(0,1)$, batas $[-4, 4]$) berbasis vektor respons peserta pada butir-butir subtes tersebut.

4. **Skor Subtes & Skor Total (200 - 1000)**:
   $$\text{Skor Subtes} = 500 + 100 \times \theta_{\text{subtes}}$$
   $$\text{Skor Total} = \text{rata-rata Skor Subtes yang dikerjakan}$$
   (Dibatasi pada rentang 200 s/d 1000).

5. **Peringkat Nasional**: hanya untuk akun **peserta** yang mengerjakan **seluruh** subtes paket. Peserta yang tidak lengkap tetap mendapat skor subtes dan skor rata-rata, tetapi tanpa peringkat.
   - Sesi akun **admin/supervisor** (uji coba) tetap dinilai, tetapi tidak masuk peringkat, tidak ikut kalibrasi butir ($a$, $b$ hanya dari jawaban peserta), dan tidak ikut rata-rata subtes di Analitik.
   - Peringkat disusun ulang otomatis bila role akun diubah atau akun dihapus, sehingga nomor peringkat tetap berurutan.

6. **Penutupan Sesi Otomatis saat Hitung IRT**: sesi yang belum menekan *Selesai Tryout* dan sedang tidak mengerjakan subtes (diam di menu / ditinggal) ditutup otomatis lalu ikut dinilai. Sesi yang sedang mengerjakan subtes belum diikutkan.

---

## 5. Skema Relasi Database (Entity Relationship)

- **`users`**: `id`, `username`, `email`, `phone`, `password_hash`, `full_name`, `school`, `grade`, `photo_filename`, `role` ('admin', 'supervisor', 'peserta'), `must_change_password` (True setelah password direset admin), `created_at`.
- **`password_reset_requests`**: `id`, `user_id`, `contact_phone` (nomor dari form, bisa beda dari profil), `note`, `status` ('pending', 'resolved', 'rejected'), `ip_address`, `created_at`, `resolved_at`, `resolved_by_id`. Maksimal satu permintaan `pending` per user.
- **`test_groups` (Tier 1)**: `id`, `name`, `description`.
- **`subtests` (Tier 2)**: `id`, `test_group_id`, `name`, `default_duration_minutes`, `order_num`.
- **`topics` (Tier 3 - Opsional)**: `id`, `subtest_id`, `name`, `description`.
- **`questions`**: `id`, `subtest_id`, `topic_id` (nullable), `question_type` ('pg', 'pg_kompleks', 'isian'), `question_text`, `question_image`, `options_json`, `correct_answer_json`, `explanation_text`, `explanation_image`, `difficulty_level`, `irt_a`, `irt_b`, `irt_c`, `created_by`.
- **`tryout_packages`**: `id`, `title`, `description`, `banner_image`, `start_time`, `end_time` (disimpan UTC; form admin memakai WIB), `is_published`, `is_irt_calculated`, `free_subtest_order` (True: urutan bebas, False: berurutan/simulasi UTBK), `created_by`.
- **`tryout_subtests`**: `id`, `tryout_package_id`, `subtest_id`, `duration_minutes`, `order_num`.
- **`tryout_questions`**: `id`, `tryout_package_id`, `question_id`, `order_num`.
- **`exam_sessions`**: `id`, `user_id`, `tryout_package_id`, `current_subtest_index` & `current_subtest_start` (legacy, tidak dipakai lagi), `start_time`, `submitted_at`, `status` ('in_progress', 'completed', 'expired'), `total_raw_score`, `total_irt_score` (nullable), `national_rank` (null = tidak berperingkat), `irt_scored_at` (waktu sesi ikut kalkulasi IRT; null = peserta selesai setelah kalkulasi terakhir, skor tampil "Menunggu IRT" dan admin diminta menghitung ulang).
- **`exam_subtest_attempts`**: `id`, `exam_session_id`, `subtest_id`, `status` ('in_progress', 'finished'), `started_at`, `finished_at`. Satu baris per subtes yang pernah dibuka; subtes yang belum dibuka tidak punya baris. Unik per (`exam_session_id`, `subtest_id`).
- **`exam_answers`**: `id`, `exam_session_id`, `question_id`, `user_answer_json`, `is_correct`, `is_marked_doubtful`, `updated_at`.
- **`subtest_scores`**: `id`, `exam_session_id`, `subtest_id`, `raw_correct`, `raw_total`, `irt_score`.
- **`activity_logs`**: `id`, `user_id`, `action`, `details`, `ip_address`, `created_at`.

---

## 6. Alur Pengerjaan Peserta (CBT Flow)

1. **Registrasi / Login & Profil**: Peserta melengkapi data identitas (email, nama, asal sekolah, kelas, foto profil).
2. **Katalog Paket Tryout**: Peserta memilih paket tryout aktif (dalam jadwal buka-tutup paket).
3. **Menu Pilih Subtes**:
   - Menampilkan semua subtes paket dengan status: Belum Dikerjakan / Sedang Berjalan / Selesai (terkunci).
   - Mode **urutan bebas**: peserta memilih subtes mana pun yang belum dikerjakan. Mode **berurutan**: hanya subtes berikutnya sesuai urutan paket yang bisa dimulai.
   - Hanya **satu subtes** yang boleh berjalan dalam satu waktu. Timer tetap berjalan walaupun peserta kembali ke menu (tidak bisa dijeda).
   - Tombol **Selesai Tryout** ada di menu ini; tryout boleh diselesaikan tanpa mengerjakan semua subtes. Bila semua subtes sudah selesai, lembar ujian otomatis dikumpulkan.
   - Setelah jadwal paket ditutup, sesi yang tidak sedang mengerjakan subtes otomatis diselesaikan; subtes yang sedang berjalan boleh dituntaskan sampai timernya habis.
4. **CBT Exam Room (satu subtes)**:
   - Menampilkan countdown timer subtes aktif.
   - Pilihan jawaban tersimpan secara instan (*auto-save*) via AJAX fetch tanpa reload halaman. Server hanya menerima jawaban untuk soal di subtes yang sedang berjalan (toleransi 10 detik setelah timer habis untuk keterlambatan jaringan).
   - Navigasi tombol nomor soal dengan indikator status warna:
     - Hijau: Sudah dijawab
     - Kuning: Ragu-ragu
     - Abu-abu: Belum dijawab
     - Biru/Border: Soal aktif
   - Tombol **Selesai Subtes & Kembali ke Menu** mengunci subtes. Saat waktu habis, subtes otomatis dikunci dan peserta kembali ke menu.
5. **Submit & Kalkulasi Nilai**:
   - Setelah selesai, peserta diarahkan ke halaman hasil (menunggu IRT).
   - Admin mengeksekusi kalkulasi IRT batch untuk mengalibrasi tingkat kesulitan soal dari data respons seluruh peserta.
6. **Review Pembahasan & Leaderboard**:
   - Peserta dapat melihat skor per subtes, peringkat nasional, serta pembahasan mendalam per butir soal (kunci jawaban, analisis, dan tips penyelesaian).

---

## 7. Alur Lupa Password (Diproses Admin)

Aplikasi berjalan di server lokal tanpa layanan email, sehingga reset password dilakukan melalui admin:

1. **User mengajukan permintaan** di halaman *Lupa Password* (tautan di halaman login): username/email, nomor HP/WA yang bisa dihubungi (opsional), dan catatan. Pesan konfirmasi selalu sama, baik akun ditemukan atau tidak, agar username terdaftar tidak bisa ditebak. Permintaan ulang tidak membuat duplikat.
2. **Admin melihat permintaan** di *Panel Admin → Reset Password* (jumlah permintaan tampil sebagai badge di navigasi). Admin memverifikasi identitas melalui **nomor yang terdaftar di profil**; sistem memberi tanda bila nomor di form berbeda dari profil.
3. **Admin klik Reset**: sistem membuat password sementara 8 karakter (tanpa karakter ambigu 0/O/1/l/I), menyimpan hash-nya, dan menampilkannya **sekali** kepada admin, lengkap dengan tombol salin dan tautan WhatsApp ke nomor terdaftar. Admin juga bisa **Tolak** permintaan yang mencurigakan.
4. **User login dengan password sementara** dan langsung diarahkan ke halaman *Buat Password Baru*. Semua halaman lain diblokir sampai password baru (minimal 6 karakter, tidak sama dengan password sementara) disimpan.
5. Seluruh langkah tercatat di Activity Log: `FORGOT_PASSWORD_REQUEST`, `PASSWORD_RESET`, `PASSWORD_RESET_REJECTED`, `PASSWORD_CHANGED`.
