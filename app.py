# app.py
import time
import hashlib
import json
import requests
import os
import config
import csv
import io
import pandas as pd  
from flask import Response
from datetime import datetime, date, timedelta, timezone
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, has_request_context, flash
from apscheduler.schedulers.background import BackgroundScheduler
from schedule import logger
from werkzeug.security import generate_password_hash, check_password_hash
from multiprocessing import Process
# lokal modules
from pipeline import bot_id, mysql_connector as db
from pipeline.scraper import scrape_latest_review, parse_review_time
from pipeline.model_predict import ModelPredict
from pipeline.place_id import extract_place_id

app = Flask(__name__)
app.secret_key = config.SECRET_KEY or os.urandom(32)
scheduler = BackgroundScheduler(daemon=True)
scheduler.start()
JOB_ID_PREFIX = "scrape_job_hotel_"
MODEL = ModelPredict()  # inisialisasi model
# gunakan file-based timestamp agar shared antar-process (fallback jika tidak ada external store)
TIMESTAMP_FILE = os.path.join(config.DATA_DIR if hasattr(config, "DATA_DIR") else ".", ".last_scrape_ts")
MIN_SCRAPE_INTERVAL = getattr(config, "MIN_SCRAPE_INTERVAL_SEC", 30)
# Bot process container
bot_process = None

# Helpers 
def md5(s: str):
    return hashlib.md5(s.encode()).hexdigest()

def read_last_ts():
    try:
        with open(TIMESTAMP_FILE, "r") as f:
            return float(f.read().strip() or "0")
    except Exception:
        return 0.0

def write_last_ts(ts: float):
    # write atomically
    tmp = TIMESTAMP_FILE + ".tmp"
    with open(tmp, "w") as f:
        f.write(str(ts))
    os.replace(tmp, TIMESTAMP_FILE)

def get_active_hotel_id(require=True):
    if not has_request_context():
        if require:
            raise RuntimeError("No request context for hotel resolution.")
        return None

    role = (session.get("role") or "user").lower()
    default_hotel_id = session.get("hotel_id")
    raw_hotel_id = session.get("active_hotel_id") if role == "admin" else default_hotel_id
    if raw_hotel_id is None:
        raw_hotel_id = default_hotel_id

    if raw_hotel_id is None:
        if require:
            raise RuntimeError("Hotel is not set in user session.")
        return None

    try:
        return int(raw_hotel_id)
    except Exception:
        if require:
            raise RuntimeError("Invalid hotel_id value in session.")
        return None

@app.context_processor
def inject_hotel_context():
    active_hotel_id = get_active_hotel_id(require=False)
    role = (session.get("role") or "user").lower() if has_request_context() else "user"
    hotel = None
    hotels_for_selector = []

    if active_hotel_id is not None:
        hotel = db.get_hotel(active_hotel_id)
        if role == "admin":
            hotels_for_selector = db.list_hotels_for_ui(active_only=False)
        else:
            hotels_for_selector = db.list_hotels_for_ui(active_only=False, hotel_id=active_hotel_id)

    return {
        "hotel": hotel,
        "active_hotel_id": active_hotel_id,
        "hotels_for_selector": hotels_for_selector
    }

# Auth decorator (API vs Page aware) 
from functools import wraps

def _is_api_request():
    return (
        request.path.startswith("/api/")
        or request.path.startswith("/bot/")
        or request.is_json
        or request.headers.get("Accept", "").startswith("application/json")
    )

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "uid" not in session:
            if _is_api_request():
                return jsonify({"ok": False, "msg": "Unauthorized"}), 401
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "uid" not in session:
            if _is_api_request():
                return jsonify({"ok": False, "msg": "Unauthorized"}), 401
            return redirect(url_for("login"))

        role = (session.get("role") or "user").lower()
        if role != "admin":
            if _is_api_request():
                return jsonify({"ok": False, "msg": "Forbidden: admin only"}), 403
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return wrapper

def user_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "uid" not in session:
            if _is_api_request():
                return jsonify({"ok": False, "msg": "Unauthorized"}), 401
            return redirect(url_for("login"))

        role = (session.get("role") or "user").lower()
        if role == "admin":
            if _is_api_request():
                return jsonify({"ok": False, "msg": "Forbidden: user area"}), 403
            return redirect(url_for("admin_dashboard"))
        return f(*args, **kwargs)
    return wrapper

# Sentiment classification (benar) 
def classify_text_or_rating(text, rating):
    """
    Return (nb_label, svm_label, db_label)
    db_label normalized to ('Positive','Negative')
    - If text exists, use models
    - Else infer from rating: rating >=4 => Positive else Negative
    """
    def norm(lbl):
        if not lbl:
            return None
        s = (lbl or "").strip().lower()
        # menangani label bahasa indonesia / english
        if "positif" in s or "positive" in s or s == "pos" or s == "p":
            return "POSITIF"
        if "negatif" in s or "negative" in s or s == "neg" or s == "n":
            return "NEGATIF"
        return None
    if text and text.strip():
        try:
            nb = MODEL.predict_nb(text)
        except Exception:
            nb = None
        try:
            svm = MODEL.predict_svm(text)
        except Exception:
            svm = None

        db_label = norm(nb) or norm(svm) or "NEGATIF"
        # normalize returned labels to readable form
        nb = nb or "Unknown"
        svm = svm or "Unknown"
        return nb, svm, db_label
    else:
        rule = "POSITIF" if (int(rating or 0) >= 3) else "NEGATIF"
        # return nb, svm, db_label (both models absent so we duplicate rule)
        return rule, rule, rule

# Broadcast Telegram 
def broadcast_to_subscribers(saved_review, hotel_id):
    subs = db.get_subscribers(hotel_id)
    if not subs or not getattr(config, "TELEGRAM_BOT_TOKEN", None):
        return {"sent": 0, "failed": 0}
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    sent = failed = 0
    message = (
        "📢 <b>Review Baru</b>\n"
        f"👤 <b>User:</b> {saved_review.get('user_name')}\n"
        f"⭐ <b>Rating:</b> {saved_review.get('rating')}\n\n"
        f"📝 <b>Review:</b> {(saved_review.get('review_text') or '(None)')[:400]}\n\n"
        f"🤖 <b>Naive Bayes:</b> {saved_review.get('sentiment_nb')}\n"
        f"⚡ <b>SVM:</b> {saved_review.get('sentiment_svm')}\n\n"
        f"🕒 <b>Waktu:</b> {saved_review.get('review_time').strftime('%d/%m/%Y %H:%M:%S')}"
    )
    # safety: cap to telegram limit
    if len(message) > 3800:
        message = message[:3790] + "\n\n...(truncated)"

    for s in subs:
        payload = {"chat_id": s["chat_id"], "text": message, "parse_mode": "HTML"}
        try:
            r = requests.post(url, data=payload, timeout=12)
            ok = (r.status_code == 200 and r.json().get("ok", False))
        except Exception:
            ok = False
        status = "sent" if ok else "failed"
        try:
            db.log_notification(saved_review["review_id"], s["chat_id"], hotel_id, status)
        except Exception:
            pass
        if ok:
            sent += 1
        else:
            failed += 1
    return {"sent": sent, "failed": failed}

# Orchestration: one scrape run
def run_scrape_once(hotel_id):
    """
    1) call pipeline.scraper.scrape_latest_review, Ambil review terbaru dari Google Maps
    2) if you found the same review as last time, skip
    3) if found, save to hotel_reviews (raw) & sentiment_reviews
    4) broadcast to telegram & log notifications
    Returns dict with summary
    """
    hotel = db.get_hotel(hotel_id) or {}
    google_data_id = hotel.get("google_place_id") or hotel.get("place_id")
    if not google_data_id:
        return {"ok": False, "msg": f"Google place id not configured for hotel_id={hotel_id}"}

    try:
        reviews = scrape_latest_review(google_data_id, config.SERPAPI_KEY)
    except Exception as e:
        return {"ok": False, "msg": f"Scraper error: {e}"}

    if not reviews:
        return {"ok": True, "new": False, "msg": "No reviews"}

    r = reviews[0]

    # Normalisasi Teks
    text = r.get("text") or r.get("snippet")
    if text is not None:
        text = text.strip() or None  #Kosong jadi None
    
    # Rating
    try:
        rating = int(r.get("rating") or 0)
    except Exception:
        rating = 0
    # User
    user = r.get("user")
    user_name = (user.get("name") if isinstance(user, dict) else (user or "Unknown"))
    # Sumber dan Waktu
    source = r.get("source", "Google Maps")
    
    # Waktu review asli
    review_time = parse_review_time(r.get("time")) or datetime.now()

    # cek duplikat
    try:
        if db.review_exists(hotel_id, user_name, text, rating, source):
            return {"ok": True, "new": False, "msg": "Review already exists, skipped"}
    except Exception as e:
        # jika fungsi db error, log dan lanjutkan (atau return error)
        return {"ok": False, "msg": f"DB error on review_exists: {e}"}

    # save raw review/ simpan ulasan mentah
    try:
        review_id = db.save_hotel_review(hotel_id, user_name, text, rating, review_time, source)
    except Exception as e:
        return {"ok": False, "msg": f"DB error on save_hotel_review: {e}"}

    # classify
    nb, svm, db_label = classify_text_or_rating(text, rating)

    # save sentiment result
    try:
        sid = db.save_sentiment_review(
            review_id, hotel_id, user_name, text, rating,
            review_time, nb, svm, source
        )
    except Exception as e:
        return {"ok": False, "msg": f"DB error on save_sentiment_review: {e}"}

    saved = {
        "review_id": review_id,
        "sentiment_id": sid,
        "user_name": user_name,
        "review_text": text,
        "rating": rating,
        "sentiment_nb": nb,
        "sentiment_svm": svm,
        "review_time": review_time, # waktu asli dari Google Maps
        "source": source
    }

    # broadcast
    stats = broadcast_to_subscribers(saved, hotel_id) if getattr(config, "TELEGRAM_BOT_TOKEN", None) else {"sent": 0, "failed": 0}
    return {"ok": True, "new": True, "saved": saved, "notify": stats}

# Scheduler and Scheduler control 
def _job_id_for_hotel(hotel_id: int) -> str:
    return f"{JOB_ID_PREFIX}{int(hotel_id)}"

def scheduled_scrape_job(hotel_id):
    try:
        hid = int(hotel_id)
        result = run_scrape_once(hid)
        logger.info(f"Scheduled scrape executed for hotel_id={hid}: {result}")
    except Exception as e:
        logger.error(f"Scheduled scrape failed for hotel_id={hotel_id}: {e}", exc_info=True)


def _parse_admin_datetime(value):
    raw = (value or "").strip()
    if not raw:
        return datetime.now()
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return datetime.now()


def _is_ajax_request():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _serialize_admin_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _serialize_admin_row(row):
    if not row:
        return None
    return {key: _serialize_admin_value(value) for key, value in row.items()}


def _admin_action_response(ok, message, table, status_code=200, payload=None):
    if _is_ajax_request():
        return jsonify({"ok": ok, "msg": message, "table": table, "payload": payload or {}}), status_code
    flash(message)
    return redirect(url_for("admin_data_management", table=table))

# Routes & endpoints
@app.get("/login")
def login():
    if "uid" in session:
        return redirect(url_for("dashboard"))
    return render_template("login.html")

@app.post("/login")
def login_post():
    username = request.form.get("username","").strip()
    password = request.form.get("password","")
    user = db.get_user_by_username(username)
    if not user or not check_password_hash(user["password"], password):
        return render_template("login.html", error="Username atau password salah")
    if not user.get("hotel_id"):
        return render_template("login.html", error="Akun tidak terhubung ke hotel.")
    role = user.get("role") if isinstance(user, dict) else getattr(user, "role", "user")
    hotel = db.get_hotel(int(user["hotel_id"])) if user.get("hotel_id") else None
    if (role or "user").lower() != "admin" and hotel and not hotel.get("is_active", True):
        return render_template("login.html", error="Hotel untuk akun ini sedang nonaktif. Hubungi admin.")
    session["uid"] = user["user_id"]
    session["uname"] = user["username"]
    session["hotel_id"] = int(user["hotel_id"])
    session["active_hotel_id"] = session["hotel_id"]
    # guard: if user is not dict-like with .get
    session["role"] = role or "user"
    if (session.get("role") or "").lower() == "admin":
        return redirect(url_for("admin_dashboard"))
    return redirect(url_for("dashboard"))

@app.get("/register")
def register():
    return render_template("register.html")

@app.post("/register")
def register_post():
    username = request.form.get("username","").strip()
    password = request.form.get("password","")
    hotel_name = request.form.get("hotel_name", "").strip()
    address = request.form.get("address", "").strip()
    place_id_input = request.form.get("place_id", "").strip()
    if not username or not password or not hotel_name or not place_id_input:
        return render_template("register.html", error="Semua field wajib diisi kecuali alamat.")
    place_id = extract_place_id(place_id_input, resolve_redirect=True)
    if not place_id:
        return render_template(
            "register.html",
            error="Place ID tidak valid. Isi dengan Place ID atau link Google Maps hotel yang lengkap."
        )
    if db.get_user_by_username(username):
        return render_template("register.html", error="Username sudah dipakai.")
    pw_hash = generate_password_hash(password)
    try:
        db.create_hotel_and_user(
            username=username,
            password_hash=pw_hash,
            hotel_name=hotel_name,
            address=address or None,
            place_id=place_id,
            role="user"
        )
    except Exception as e:
        return render_template("register.html", error=f"Gagal register: {e}")
    return redirect(url_for("login"))

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# Lupa Password & Ganti Password 
@app.get("/forgot-password")
def forgot_password():
    return render_template("forgot_password.html")

@app.post("/forgot-password")
def forgot_password_post():
    username = request.form.get("username", "").strip()
    user = db.get_user_by_username(username)
    if not user:
        return render_template("forgot_password.html", message="Username tidak ditemukan")

    # Nanti di sini bisa kirim email reset link, tapi untuk demo langsung redirect
    return redirect(url_for("reset_password", username=username))

@app.get("/reset-password/<username>")
def reset_password(username):
    user = db.get_user_by_username(username)
    if not user:
        return redirect(url_for("forgot_password"))
    return render_template("reset_password.html", username=username)

@app.post("/reset-password/<username>")
def reset_password_post(username):
    new_password = request.form.get("new_password", "")
    if not new_password:
        return render_template("reset_password.html", error="Password tidak boleh kosong", username=username)

    pw_hash = generate_password_hash(new_password)
    db.update_user_password(username, pw_hash)
    return redirect(url_for("login"))
# End Lupa Password & Ganti Password 

@app.get("/")
@login_required
def index():
    if (session.get("role") or "").lower() == "admin":
        return redirect(url_for("admin_dashboard"))
    return redirect(url_for("dashboard"))

@app.post("/set-hotel")
@login_required
def set_active_hotel():
    next_url = request.form.get("next") or request.referrer or url_for("dashboard")
    try:
        hotel_id = int(request.form.get("hotel_id", "0"))
    except Exception:
        return redirect(next_url)

    role = (session.get("role") or "user").lower()
    if role == "admin":
        available_ids = {int(h["hotel_id"]) for h in db.list_hotels_for_ui(active_only=False)}
        if hotel_id in available_ids:
            session["active_hotel_id"] = hotel_id
    elif hotel_id == int(session.get("hotel_id", 0)):
        session["active_hotel_id"] = hotel_id
    return redirect(next_url)

# dashboard
@app.get("/admin/dashboard")
@admin_required
def admin_dashboard():
    data = db.get_admin_overview()
    return render_template("admin_dashboard.html", data=data)


@app.get("/admin/data")
@admin_required
def admin_data_management():
    catalog = db.list_admin_table_catalog()
    table_keys = [item["key"] for item in catalog]
    selected_table = request.args.get("table", table_keys[0] if table_keys else "hotels")
    if selected_table not in table_keys and table_keys:
        selected_table = table_keys[0]

    preview_page = request.args.get("page", default=1, type=int)
    preview_limit = request.args.get("limit", default=8, type=int)
    preview_search = request.args.get("search", default="", type=str)
    preview = db.get_admin_table_preview(selected_table, limit=preview_limit, page=preview_page, search=preview_search)
    selected_meta = next((item for item in catalog if item["key"] == selected_table), None) or {}
    hotels = db.list_hotels_for_ui(active_only=False)
    review_choices = db.list_recent_hotel_reviews_for_admin(limit=50)
    edit_hotel_review = None
    edit_sentiment_review = None

    if selected_table == "hotel_reviews":
        edit_id = request.args.get("edit_review_id", type=int)
        if edit_id:
            edit_hotel_review = db.get_hotel_review_by_id(edit_id)
    elif selected_table == "sentiment_reviews":
        edit_id = request.args.get("edit_sentiment_id", type=int)
        if edit_id:
            edit_sentiment_review = db.get_sentiment_review_by_id(edit_id)

    return render_template(
        "admin_data_management.html",
        catalog=catalog,
        selected_table=selected_table,
        selected_label=selected_meta.get("label", selected_table),
        preview=preview,
        preview_search=preview_search,
        hotels=hotels,
        review_choices=review_choices,
        edit_hotel_review=edit_hotel_review,
        edit_sentiment_review=edit_sentiment_review,
    )


@app.post("/admin/data/hotel-reviews/create")
@admin_required
def admin_create_hotel_review():
    try:
        hotel_id = int(request.form.get("hotel_id", "0"))
        user_name = request.form.get("user_name", "").strip()
        review_text = request.form.get("review_text", "").strip() or None
        rating = int(request.form.get("rating", "0"))
        source = request.form.get("source", "").strip() or "Manual Admin"
        review_date = _parse_admin_datetime(request.form.get("review_date"))

        if not hotel_id or not user_name or rating < 1 or rating > 5:
            raise ValueError("Data review belum lengkap atau rating tidak valid.")

        review_id = db.save_hotel_review(hotel_id, user_name, review_text, rating, review_date, source)
        row = db.get_hotel_review_by_id(review_id)
        return _admin_action_response(True, "Review hotel berhasil ditambahkan.", "hotel_reviews", payload={"row": _serialize_admin_row(row)})
    except Exception as e:
        return _admin_action_response(False, f"Gagal menambah review hotel: {e}", "hotel_reviews", 400)


@app.post("/admin/data/hotel-reviews/<int:review_id>/update")
@admin_required
def admin_update_hotel_review(review_id):
    try:
        hotel_id = int(request.form.get("hotel_id", "0"))
        user_name = request.form.get("user_name", "").strip()
        review_text = request.form.get("review_text", "").strip() or None
        rating = int(request.form.get("rating", "0"))
        source = request.form.get("source", "").strip() or "Manual Admin"
        review_date = _parse_admin_datetime(request.form.get("review_date"))

        if not hotel_id or not user_name or rating < 1 or rating > 5:
            raise ValueError("Data review belum lengkap atau rating tidak valid.")

        db.update_hotel_review_admin(review_id, hotel_id, user_name, review_text, rating, review_date, source)
        row = db.get_hotel_review_by_id(review_id)
        return _admin_action_response(True, "Review hotel berhasil diperbarui.", "hotel_reviews", payload={"row": _serialize_admin_row(row)})
    except Exception as e:
        return _admin_action_response(False, f"Gagal memperbarui review hotel: {e}", "hotel_reviews", 400)


@app.post("/admin/data/hotel-reviews/<int:review_id>/delete")
@admin_required
def admin_delete_hotel_review(review_id):
    try:
        db.delete_hotel_review_admin(review_id)
        return _admin_action_response(True, "Review hotel berhasil dihapus.", "hotel_reviews", payload={"review_id": review_id})
    except Exception as e:
        return _admin_action_response(False, f"Gagal menghapus review hotel: {e}", "hotel_reviews", 400)


@app.post("/admin/data/sentiment-reviews/create")
@admin_required
def admin_create_sentiment_review():
    try:
        review_id = int(request.form.get("review_id", "0"))
        sentiment_nb = (request.form.get("sentiment_nb") or "").strip().upper()
        sentiment_svm = (request.form.get("sentiment_svm") or "").strip().upper()
        source = request.form.get("source", "").strip() or "Manual Admin"

        if not review_id or sentiment_nb not in ("POSITIF", "NEGATIF") or sentiment_svm not in ("POSITIF", "NEGATIF"):
            raise ValueError("Data sentimen tidak valid.")

        sentiment_id = db.create_sentiment_review_admin(review_id, sentiment_nb, sentiment_svm, source)
        row = db.get_sentiment_review_by_id(sentiment_id)
        return _admin_action_response(True, "Sentiment review berhasil ditambahkan.", "sentiment_reviews", payload={"row": _serialize_admin_row(row)})
    except Exception as e:
        return _admin_action_response(False, f"Gagal menambah sentiment review: {e}", "sentiment_reviews", 400)


@app.post("/admin/data/sentiment-reviews/<int:sentiment_id>/update")
@admin_required
def admin_update_sentiment_review(sentiment_id):
    try:
        sentiment_nb = (request.form.get("sentiment_nb") or "").strip().upper()
        sentiment_svm = (request.form.get("sentiment_svm") or "").strip().upper()
        source = request.form.get("source", "").strip() or "Manual Admin"

        if sentiment_nb not in ("POSITIF", "NEGATIF") or sentiment_svm not in ("POSITIF", "NEGATIF"):
            raise ValueError("Label sentimen harus POSITIF atau NEGATIF.")

        db.update_sentiment_review_admin(sentiment_id, sentiment_nb, sentiment_svm, source)
        row = db.get_sentiment_review_by_id(sentiment_id)
        return _admin_action_response(True, "Sentiment review berhasil diperbarui.", "sentiment_reviews", payload={"row": _serialize_admin_row(row)})
    except Exception as e:
        return _admin_action_response(False, f"Gagal memperbarui sentiment review: {e}", "sentiment_reviews", 400)


@app.post("/admin/data/sentiment-reviews/<int:sentiment_id>/delete")
@admin_required
def admin_delete_sentiment_review(sentiment_id):
    try:
        db.delete_sentiment_review_admin(sentiment_id)
        return _admin_action_response(True, "Sentiment review berhasil dihapus.", "sentiment_reviews", payload={"sentiment_id": sentiment_id})
    except Exception as e:
        return _admin_action_response(False, f"Gagal menghapus sentiment review: {e}", "sentiment_reviews", 400)


@app.post("/admin/data/hotels/<int:hotel_id>/toggle-active")
@admin_required
def admin_toggle_hotel_active(hotel_id):
    try:
        hotel = db.get_hotel(hotel_id)
        if not hotel:
            raise ValueError("Hotel tidak ditemukan.")
        next_status = not bool(hotel.get("is_active"))
        db.set_hotel_active_status(hotel_id, next_status)
        return _admin_action_response(
            True,
            f"Hotel {'diaktifkan kembali' if next_status else 'dinonaktifkan'} dengan aman.",
            "hotels",
            payload={"hotel_id": hotel_id, "is_active": next_status},
        )
    except Exception as e:
        return _admin_action_response(False, f"Gagal mengubah status hotel: {e}", "hotels", 400)


@app.post("/admin/data/hotels/<int:hotel_id>/delete")
@admin_required
def admin_delete_hotel_permanently(hotel_id):
    try:
        db.delete_hotel_permanently(hotel_id)
        return _admin_action_response(True, "Hotel berhasil dihapus permanen.", "hotels", payload={"hotel_id": hotel_id})
    except Exception as e:
        return _admin_action_response(False, f"Gagal menghapus hotel permanen: {e}", "hotels", 400)

@app.get("/dashboard")
@user_required
def dashboard():
    hotel_id = get_active_hotel_id()
    # Ambil data utama dari database
    hotel = db.get_hotel(hotel_id)
    latest = db.get_latest_reviews(hotel_id, limit=1)  # Review terbaru
    counts = db.count_sentiments(hotel_id)
    trend = db.trend_reviews(hotel_id, days=7)
    total_reviews = db.get_review_stats(hotel_id)
    diff_reviews = counts.get("POSITIF", 0) - counts.get("NEGATIF", 0)
    weekly = db.get_weekly_comparison(hotel_id)
    
    # Tambahan: data rating
    avg_rating = db.get_average_rating(hotel_id)
    count_by_star = db.get_rating_distribution(hotel_id)  # misal return dict {5:10,4:4,3:2,...}

    # Perhitungan distribusi rating agar total = 100% 
    rating_dist = {}
    total_count = sum(count_by_star.values()) or 1  # hindari div by zero
    # Hitung persentase mentah
    raw_percentages = {
        star: (count_by_star.get(star, 0) / total_count) * 100
        for star in range(1, 6)
    }

    # Bulatkan & hitung total
    rating_dist = {star: round(raw_percentages[star]) for star in raw_percentages}
    total_rounded = sum(rating_dist.values())

    # Koreksi selisih (agar total tepat 100%)
    diff = 100 - total_rounded
    if diff != 0:
        # Tambahkan/kurangi ke bintang 5 (atau rating tertinggi yang punya nilai)
        for star in range(5, 0, -1):
            if rating_dist.get(star, 0) + diff >= 0:
                rating_dist[star] += diff
                break

    # 🔹 Keyword analytics
    keywords = db.get_top_keywords(hotel_id, limit=5)

    # Kirim semua data ke template
    return render_template(
        "dashboard.html",
        hotel=hotel,
        avg_rating=avg_rating,
        rating_dist=rating_dist,
        latest=latest,
        trend=trend,
        counts=counts,
        total_reviews=total_reviews,
        diff_reviews=diff_reviews,
        keywords=keywords,
        weekly=weekly
    )

# Halaman review
@app.get("/reviews")
@user_required
def reviews_page():
    rows = db.list_sentiments(get_active_hotel_id(), limit=100)
    return render_template("reviews.html", rows=rows)


@app.get("/api/reviews")
@user_required
def api_reviews():
    hotel_id = get_active_hotel_id()
    limit = request.args.get("limit", default=100, type=int)
    search = request.args.get("search", default="", type=str)
    rows = db.list_sentiments(hotel_id, limit=(None if limit == 0 else limit), search=search)
    return jsonify(rows)

#  Route untuk Export Reviews
@app.get("/reviews/export/<fmt>")
@user_required
def export_reviews(fmt):
    hotel_id = get_active_hotel_id()
    limit = request.args.get("limit", type=int)
    sentiment = request.args.get("filter", "all")
    rating = request.args.get("rating", "all")
    model = request.args.get("model", "all")
    date_filter = request.args.get("date", "all")
    start = request.args.get("start")
    end = request.args.get("end")
    query = """
        SELECT review_date, user_name, rating, review_text, sentiment_nb, sentiment_svm
        FROM sentiment_reviews
        WHERE hotel_id = %s
    """
    params = [hotel_id]
    # Filter sentiment umum (Naive Bayes default)
    if sentiment in ("positif", "negatif"):
        query += " AND sentiment_nb = %s"
        params.append(sentiment.upper())
    # Filter rating
    if rating.isdigit():
        query += " AND rating = %s"
        params.append(int(rating))
    # Filter model
    if model == "nb_pos":
        query += " AND sentiment_nb = 'POSITIF'"
    elif model == "nb_neg":
        query += " AND sentiment_nb = 'NEGATIF'"
    elif model == "svm_pos":
        query += " AND sentiment_svm = 'POSITIF'"
    elif model == "svm_neg":
        query += " AND sentiment_svm = 'NEGATIF'"
    # Filter tanggal (pakai MySQL DATE_FORMAT / BETWEEN)
    if date_filter == "month":
        now = datetime.now().strftime("%Y-%m")
        query += " AND DATE_FORMAT(review_date, '%%Y-%%m') = %s"
        params.append(now)
    elif date_filter == "range" and start and end:
        query += " AND DATE(review_date) BETWEEN %s AND %s"
        params.extend([start, end])
    query += " ORDER BY review_date DESC"
    if limit:
        query += f" LIMIT {limit}"

    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute(query, tuple(params))
    rows = cur.fetchall()
    cur.close(); conn.close()

    # Export CSV
    if fmt == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Tanggal", "User", "Rating", "Text", "Naive Bayes", "SVM"])
        for r in rows:
            writer.writerow(r)
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment;filename=reviews.csv"}
        )

    # Export XLS 
    elif fmt in ("xls", "xlsx"):
        df = pd.DataFrame(rows, columns=["Tanggal", "User", "Rating", "Text", "Naive Bayes", "SVM"])
        output = io.BytesIO()
        df.to_excel(output, index=False)
        output.seek(0)
        return Response(
            output.read(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment;filename=reviews.xlsx"}
        )
    return jsonify({"ok": False, "msg": "Format not supported"})

#Halaman subcriber
@app.get("/subscribers")
@user_required
def subscribers_page():
    subs = db.get_subscribers(get_active_hotel_id())
    return render_template("subscribers.html", subs=subs)

@app.post("/subscribers")
@user_required
def subscribers_add():
    chat_id = request.form.get("chat_id")
    if chat_id:
        try:
            db.add_subscriber(int(chat_id), get_active_hotel_id())
        except Exception:
            pass
    return redirect(url_for("subscribers_page"))

#Halaman notifications
@app.get("/notifications")
@user_required
def notifications_page():
    rows = db.get_notifications(get_active_hotel_id(), limit=100)
    return render_template("notifications.html", rows=rows)
# coba scearch 
@app.route('/api/notifications')
@user_required
def get_notifications():
    hotel_id = get_active_hotel_id()
    limit = request.args.get('limit', default=150, type=int)
    search = request.args.get('search', default="", type=str)
    if limit == 0:
        rows = db.get_notifications(hotel_id, limit=None, search=search)
    else:
        rows = db.get_notifications(hotel_id, limit=limit, search=search)
    return jsonify(rows)

# Halaman analytic
@app.get("/analytics")
@user_required
def analytics_page():
    hotel_id = get_active_hotel_id()
    counts = db.count_sentiments(hotel_id)
    trend = db.trend_reviews(hotel_id, days=30)
    return render_template("analytics.html", counts=counts, trend=trend)

# API endpoints
@app.post("/api/scrape")
@user_required
def api_scrape():
    hotel_id = get_active_hotel_id()
    # throttle across processes using file timestamp
    now = time.time()
    last = read_last_ts()
    if now - last < MIN_SCRAPE_INTERVAL:
        return jsonify({"ok": False, "msg": "Terlalu cepat, tunggu beberapa saat"}), 429
    # update timestamp immediately to avoid race
    write_last_ts(now)
    res = run_scrape_once(hotel_id)
    # if failed, optionally reset timestamp to allow retry sooner
    if not res.get("ok"):
        # small backoff: subtract MIN_SCRAPE_INTERVAL to allow next immediate attempt
        write_last_ts(last)
    return jsonify(res)

# Scheduler control
@app.post("/api/scheduler/start")
@user_required
def api_sched_start():
    hotel_id = get_active_hotel_id()
    job_id = _job_id_for_hotel(hotel_id)
    data = request.get_json(force=True)
    minutes = int(data.get("minutes", 15))
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    scheduler.add_job(
        scheduled_scrape_job,
        "interval",
        minutes=minutes,
        args=[hotel_id],
        id=job_id,
        replace_existing=True
    )
    return jsonify({"ok": True, "minutes": minutes})

@app.post("/api/scheduler/stop")
@user_required
def api_sched_stop():
    hotel_id = get_active_hotel_id()
    job_id = _job_id_for_hotel(hotel_id)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    return jsonify({"ok": True})

#scheduler status
@app.get("/api/scheduler/status")
@user_required
def api_sched_status():
    hotel_id = get_active_hotel_id()
    job_id = _job_id_for_hotel(hotel_id)
    job = scheduler.get_job(job_id)
    if job:
        next_run = job.next_run_time
        remaining = None
        if next_run:
            # pastikan semua datetime UTC
            now = datetime.now(timezone.utc)
            next_run = next_run.astimezone(timezone.utc)
            remaining = int((next_run - now).total_seconds())
            if remaining < 0:
                remaining = 0
        return jsonify({
            "ok": True,
            "running": True,
            "interval": job.trigger.interval.total_seconds() // 60,  # menit
            "next_run": next_run.isoformat() if next_run else None,
            "remaining": remaining
        })
    else:
        return jsonify({"ok": True, "running": False})
    
#Halaman subcriber
@app.get("/api/subscribers")
@user_required
def api_get_subs():
    return jsonify(db.get_subscribers(get_active_hotel_id()))

@app.post("/api/subscribers")
@user_required
def api_add_sub():
    data = request.get_json(force=True)
    chat_id = data.get("chat_id")
    if not chat_id:
        return jsonify({"ok": False, "msg": "chat_id kosong"}), 400
    db.add_subscriber(int(chat_id), get_active_hotel_id())
    return jsonify({"ok": True})

@app.route("/api/subscribers/<int:chat_id>", methods=["DELETE"])
@user_required
def api_del_sub(chat_id):
    try:
        db.remove_subscriber(chat_id, get_active_hotel_id())
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500

# Analytics APIs
@app.get("/api/analytics/sentiment")
@user_required
def api_analytics_sentiment():
    d = db.count_sentiments(get_active_hotel_id())
    mapping = [{"label": k, "value": v} for k, v in d.items()]
    return jsonify(mapping)

@app.get("/api/analytics/rating")
@user_required
def api_analytics_rating():
    avg = db.get_average_rating(get_active_hotel_id())
    try:
        avg = float(avg or 0)
    except Exception:
        avg = 0.0
    return jsonify({"avg": avg})

# Protected trend API analytic
@app.get("/api/analytics/trend")
@user_required
def api_analytics_trend():
    hotel_id = get_active_hotel_id()
    days = int(request.args.get("days", 30))  # bisa 7 / 30 hari
    rows = db.get_trend_sentiment(hotel_id, days=days)  # ganti ke query baru
    today = date.today()
    lastN = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days-1, -1, -1)]
    data_map = {r["d"].strftime("%Y-%m-%d"): r for r in rows}

    filled = []
    for d in lastN:
        r = data_map.get(d, {"pos": 0, "neg": 0})
        filled.append({
            "date": d,
            "pos": r.get("pos", 0),
            "neg": r.get("neg", 0),
            "total": r.get("pos", 0) + r.get("neg", 0)
        })
    return jsonify(filled)

# api/analytics/keywords
@app.get("/api/analytics/keywords")
@user_required
def api_keywords():
    lang = request.args.get("lang", "id")  # default: stopwords bahasa Indonesia
    limit = request.args.get("limit", default=10, type=int)
    if limit is not None and limit <= 0:
        limit = None
    data = db.get_top_keywords(get_active_hotel_id(), limit=limit, lang=lang)

    def _serialize(items):
        rows = []
        for item in items:
            if len(item) == 3:
                w, score, count = item
            else:
                w, score = item
                count = 0
            try:
                score_val = float(score)
            except Exception:
                score_val = 0.0
            rows.append({"word": w, "count": int(count), "score": score_val})
        return rows

    return jsonify({
        "ok": True,
        "positive": _serialize(data["positive"]),
        "negative": _serialize(data["negative"])
    })

# BOT CONTROL
@app.post("/bot/start")
@login_required
def start_bot():
    global bot_process
    token = (getattr(config, "TELEGRAM_BOT_TOKEN", "") or "").strip()
    if not token:
        return jsonify({
            "ok": False,
            "msg": "TELEGRAM_BOT_TOKEN belum di-set. Isi di file .env lalu restart app."
        }), 400

    if bot_process is None or not bot_process.is_alive():
        # spawn process, run bot
        bot_process = Process(target=bot_id.run_bot, args=(token,), daemon=True)
        bot_process.start()
        # Wait briefly to detect immediate crash (e.g. invalid token/config)
        time.sleep(0.4)
        if not bot_process.is_alive():
            exitcode = bot_process.exitcode
            bot_process = None
            return jsonify({
                "ok": False,
                "msg": f"Bot gagal dijalankan (exitcode={exitcode}). Cek TELEGRAM_BOT_TOKEN dan log server."
            }), 500
        return jsonify({"ok": True, "msg": "Bot started"})
    return jsonify({"ok": False, "msg": "Bot already running"})

@app.post("/bot/stop")
@login_required
def stop_bot():
    global bot_process
    if bot_process and bot_process.is_alive():
        try:
            from pipeline.bot_id import STOP_EVENT
            STOP_EVENT.set()  # beri sinyal ke bot untuk berhenti
            time.sleep(2)     # beri waktu bot menutup loop
        except Exception as e:
            app.logger.warning(f"Gagal kirim stop signal: {e}")

        bot_process.terminate()  # fallback kill jika masih hidup
        bot_process.join(timeout=3)
        if bot_process.is_alive():
            bot_process.kill()
        bot_process = None
        return jsonify({"ok": True, "msg": "Bot stopped"})
    return jsonify({"ok": False, "msg": "Bot not running"})

@app.get("/bot/status")
@login_required
def bot_status():
    global bot_process
    running = bot_process is not None and bot_process.is_alive()
    return jsonify({"running": running})

# Global error handler (API vs Page aware)
@app.errorhandler(Exception)
def handle_exception(e):
    app.logger.error(f"Unhandled error: {e}", exc_info=True)
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "msg": "Internal server error"}), 500
    return render_template("error.html", msg=str(e)), 500

# Error.html untuk penanganan kesalahan
@app.errorhandler(404)
def not_found_error(e):
    return render_template("error.html", error_code=404, error_message="Page Not Found"), 404

@app.errorhandler(500)
def internal_error(e):
    return render_template("error.html", error_code=500, error_message="Internal Server Error"), 500

if __name__ == "__main__":
    # jangan gunakan debug=True jika ingin start multiprocessing di devlopment
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=True)
