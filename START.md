# Hotel Review Dashboard (Multi-Hotel)

## Ringkasan
Aplikasi ini berbasis **multi-hotel** dengan aturan **1 user = 1 hotel**.  
Setiap user hanya melihat data hotel miliknya (session-scoped).

## Fitur Utama
- Registrasi user + hotel dalam satu langkah
- Scraping review Google Maps per hotel
- Analitik sentimen & rating
- Subscriber Telegram + notifikasi
- Scheduler scraping per hotel

## Prasyarat
- Python 3.10+
- MariaDB/MySQL aktif
- Database `monitoring_review` sudah dibuat

## Instalasi Dependensi
Gunakan file standar:
```bash
pip install -r requirements.txt
```

Alternatif lama (masih tersedia):
```bash
pip install -r library.txt
```

## Konfigurasi Environment
Buat file `.env` dari template:
```bash
cp .env.example .env
```

Lalu isi nilainya di `.env`:
```env
SECRET_KEY=replace_with_strong_random_key
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
- Jangan commit `.env`.
- `SERPAPI_KEY` wajib untuk scraping.
- `TELEGRAM_BOT_TOKEN` opsional jika tidak pakai broadcast bot.

## Setup Database dari `schema.sql`
Setelah MySQL/MariaDB aktif:
```bash
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS monitoring_review;"
mysql -u root -p monitoring_review < schema.sql
```

Jika di hosting, jalankan import schema yang sama di database server hosting.

## Push ke GitHub + Deploy
Yang dipush ke GitHub:
- Kode aplikasi
- `requirements.txt`
- `.env.example`
- `schema.sql`

Yang jangan dipush:
- `.env` (sudah di-ignore)
- Password/token asli
- Dump database produksi yang berisi data sensitif

Langkah ringkas:
```bash
git add .
git commit -m "Prepare app for deployment"
git push origin main
```

## Menjalankan Aplikasi
```bash
python app.py
```

Akses:
- `http://127.0.0.1:5000/login`
- `http://127.0.0.1:5000/register`

## Alur Penggunaan Cepat
1. Buka `/register`.
2. Isi form termasuk `place_id` **atau** link Google Maps hotel.
3. Login di `/login`.
4. Masuk ke `/dashboard` untuk hotel milik user tersebut.

## Endpoint Utama

### Page Routes
- `GET /login`
- `POST /login`
- `GET /register`
- `POST /register`
- `GET /dashboard`
- `GET /reviews`
- `GET /analytics`
- `GET /subscribers`
- `GET /notifications`
- `GET /logout`

### Scrape & Scheduler (Per Hotel Session)
- `POST /api/scrape`
- `POST /api/scheduler/start`
- `POST /api/scheduler/stop`
- `GET /api/scheduler/status`

### API Data
- `GET /api/notifications`
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

## Arsitektur Multi-Hotel
- Tidak ada fallback `config.HOTEL_ID` untuk operasi utama.
- `place_id` diambil dari tabel `hotels` berdasarkan `hotel_id` session.
- Scheduler job dibuat per hotel user (`job_id` per `hotel_id`).
- Subscriber Telegram (`telegram_users`) terikat ke `hotel_id`.
- Notifikasi (`notifications`) terikat ke `hotel_id`.

## Struktur Data Inti
- `users` -> punya `hotel_id`
- `hotels` -> simpan `place_id`, interval scrape, status aktif
- `hotel_reviews` -> review mentah per hotel
- `sentiment_reviews` -> hasil klasifikasi per hotel
- `telegram_users` -> subscriber per hotel
- `notifications` -> log kirim notifikasi per hotel

## File Penting
- `app.py` - web app + routes + scheduler API
- `config.py` - konfigurasi env
- `pipeline/mysql_connector.py` - akses DB
- `pipeline/pipeline.py` - orchestration scrape -> sentiment -> notif
- `pipeline/scraper.py` - ambil review Google Maps
- `pipeline/place_id.py` - parser place_id dari id/link

## Troubleshooting Singkat

### Register gagal karena Place ID
- Pastikan input berupa `0x...:0x...` atau URL Google Maps valid.
- Jika pakai short link, backend mencoba resolve redirect otomatis.

### Dashboard kosong
- Pastikan user sudah terhubung ke `hotel_id` valid di tabel `users`.
- Pastikan hotel punya `place_id`.
- Cek apakah tabel review untuk hotel tersebut memang sudah ada data.

### Scrape gagal
- Pastikan `SERPAPI_KEY` valid di `.env`.
- Cek response endpoint `POST /api/scrape`.

### Scheduler tidak jalan
- Start dulu via `POST /api/scheduler/start` setelah login.
- Cek status via `GET /api/scheduler/status`.

---
Last Updated: 2026-03-17  
Architecture: Multi-Hotel, Session-Scoped
