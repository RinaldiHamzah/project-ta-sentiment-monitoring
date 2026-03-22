# Hotel Review Sentiment Monitoring

Aplikasi web tugas akhir untuk monitoring ulasan hotel dan analisis sentimen berbasis machine learning.  
Sistem dirancang **multi-hotel** dengan aturan **1 user = 1 hotel**, dilengkapi scraping Google Maps, dashboard analitik, manajemen data admin, dan notifikasi Telegram.

## Fitur Utama

- Autentikasi user (login, register, reset password)
- Registrasi hotel bersamaan dengan pembuatan akun user
- Scraping review Google Maps berbasis `place_id`
- Prediksi sentimen review (Naive Bayes + SVM)
- Dashboard statistik review, rating, tren, dan keyword
- Manajemen subscriber Telegram + log notifikasi
- Scheduler scraping otomatis per hotel
- Panel admin untuk monitoring dan manajemen data utama
- Ekspor data review (CSV/Excel)

## Teknologi

- Backend: Flask
- Database: MySQL / MariaDB
- Scheduler: APScheduler
- ML Inference: scikit-learn + joblib (model `.pkl`)
- Frontend: HTML, CSS, JavaScript (Jinja templates)
- Integrasi eksternal:
  - SerpAPI (scraping Google Maps)
  - Telegram Bot API (broadcast notifikasi)

## Arsitektur Singkat

- `app.py` mengelola route halaman + API + scheduler + bot control.
- `pipeline/` berisi modul scraping, prediksi sentimen, pipeline data, koneksi DB, dan utilitas.
- `schema.sql` berisi skema database utama.
- Data model ML ada di folder model (`analisis/model_machine` atau lokasi model lain yang sesuai kode).

## Prasyarat

- Python 3.10+
- MySQL atau MariaDB aktif
- Git (opsional, untuk kolaborasi/push GitHub)

## Instalasi

1. Clone repository:

```bash
git clone <URL_REPOSITORY_ANDA>
cd APP\ TA
```

2. Buat virtual environment dan aktifkan:

```bash
python -m venv env
env\Scripts\activate
```

3. Install dependency:

```bash
pip install -r requirements.txt
```

## Konfigurasi Environment

Buat file `.env` di root project, lalu isi minimal:

```env
SECRET_KEY=replace-with-strong-random-secret
APP_HOST=0.0.0.0
APP_PORT=5000

DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=
DB_NAME=monitoring_review

SERPAPI_KEY=your_serpapi_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token

MIN_SCRAPE_INTERVAL_SEC=30
DATA_DIR=.
```

Catatan:
- Jangan commit file `.env`.
- `SERPAPI_KEY` wajib untuk fitur scraping.
- `TELEGRAM_BOT_TOKEN` opsional jika tidak memakai bot notifikasi.

## Setup Database

### Opsi 1: Dari MariaDB/MySQL shell

```sql
CREATE DATABASE IF NOT EXISTS monitoring_review
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
USE monitoring_review;
SOURCE schema.sql;
```

### Opsi 2: Dari terminal (Windows CMD)

```cmd
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS monitoring_review;"
mysql -u root -p monitoring_review < schema.sql
```

## Menjalankan Aplikasi

```bash
python app.py
```

Akses aplikasi:
- `http://127.0.0.1:5000/login`
- `http://127.0.0.1:5000/register`

## Endpoint Utama

### Halaman

- `GET /login`
- `GET /register`
- `GET /dashboard`
- `GET /reviews`
- `GET /analytics`
- `GET /subscribers`
- `GET /notifications`
- `GET /admin/dashboard`
- `GET /admin/data`

### API

- `GET /api/reviews`
- `GET /api/notifications`
- `POST /api/scrape`
- `POST /api/scheduler/start`
- `POST /api/scheduler/stop`
- `GET /api/scheduler/status`
- `GET /api/subscribers`
- `POST /api/subscribers`
- `DELETE /api/subscribers/<chat_id>`
- `GET /api/analytics/sentiment`
- `GET /api/analytics/rating`
- `GET /api/analytics/trend`
- `GET /api/analytics/keywords`

### Bot Control

- `POST /bot/start`
- `POST /bot/stop`
- `GET /bot/status`

## Struktur Project

```text
APP TA/
├─ app.py
├─ config.py
├─ schema.sql
├─ requirements.txt
├─ pipeline/
├─ templates/
├─ static/
├─ model_ml/
├─ analisis/


## Troubleshooting

### 1) `mysql` tidak dikenali di PowerShell

Gunakan path penuh, contoh:

```powershell
& "C:\xampp\mysql\bin\mysql.exe" -u root -p
```

### 2) Error model tidak ditemukan

Pastikan file model berikut ada di direktori model yang dipakai kode:
- `naive_bayes_model.pkl`
- `SVM_model.pkl`
- `vectorizer.pkl`

### 3) Scraping tidak jalan

- Cek `SERPAPI_KEY` pada `.env`
- Cek koneksi internet
- Cek response endpoint `/api/scrape`

### 4) Bot Telegram gagal start

- Cek `TELEGRAM_BOT_TOKEN` pada `.env`
- Restart aplikasi setelah update token

## Kontribusi

1. Buat branch fitur: `git checkout -b feature/nama-fitur`
2. Commit perubahan: `git commit -m "Deskripsi perubahan"`
3. Push branch: `git push origin feature/nama-fitur`
4. Buat Pull Request


