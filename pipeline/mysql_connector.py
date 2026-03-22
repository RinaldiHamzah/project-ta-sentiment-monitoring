import re
import os
import csv
import math
import mysql.connector
from collections import Counter
from datetime import datetime

def _env_int(name, default):
    raw = os.getenv(name, str(default))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default

# KONFIGURASI DATABASE
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": _env_int("DB_PORT", 3306),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "monitoring_review"),
}

def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

# Users
def get_user_by_username(username):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM users WHERE username=%s", (username,))
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


def create_hotel_and_user(
    username,
    password_hash,
    hotel_name,
    address,
    place_id,
    role="user",
    scrape_interval_minutes=30,
):
    conn = get_connection()
    cur = conn.cursor()
    lock_name = "monitoring_review_create_hotel"
    lock_acquired = False
    try:
        # Serialize hotel creation to avoid manajemen_hotel_id race under concurrent registrations.
        cur.execute("SELECT GET_LOCK(%s, %s)", (lock_name, 10))
        lock_row = cur.fetchone()
        lock_acquired = bool(lock_row and int(lock_row[0]) == 1)
        if not lock_acquired:
            raise ValueError("Sistem sedang sibuk. Coba register beberapa detik lagi.")

        conn.start_transaction()

        cur.execute("SELECT COALESCE(MAX(manajemen_hotel_id), 0) + 1 FROM hotels")
        next_mgmt_id = int(cur.fetchone()[0])

        inserted = False
        for _ in range(25):
            try:
                cur.execute(
                    """
                    INSERT INTO hotels
                        (manajemen_hotel_id, hotel_name, address, place_id, scrape_interval_minutes, is_active)
                    VALUES (%s, %s, %s, %s, %s, TRUE)
                    """,
                    (next_mgmt_id, hotel_name, address, place_id, scrape_interval_minutes),
                )
                inserted = True
                break
            except mysql.connector.IntegrityError as e:
                msg = str(e).lower()
                if "place_id" in msg:
                    raise ValueError("Place ID sudah terdaftar. Gunakan Place ID hotel lain.")
                if "manajemen_hotel_id" in msg:
                    next_mgmt_id += 1
                    continue
                raise ValueError(f"Data hotel tidak valid atau sudah terdaftar. ({e})")

        if not inserted:
            raise ValueError("Gagal membuat manajemen_hotel_id unik setelah beberapa percobaan.")

        hotel_id = cur.lastrowid
        cur.execute(
            "INSERT INTO users (username, password, role, hotel_id) VALUES (%s, %s, %s, %s)",
            (username, password_hash, role, hotel_id),
        )
        conn.commit()
        return hotel_id
    except Exception:
        conn.rollback()
        raise
    finally:
        if lock_acquired:
            try:
                cur.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
                cur.fetchone()
            except Exception:
                pass
        cur.close()
        conn.close()


def update_user_password(username, new_hash):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE users SET password=%s WHERE username=%s", (new_hash, username))
        conn.commit()
    finally:
        cur.close()
        conn.close()


# Hotels

def get_hotel(hotel_id):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM hotels WHERE hotel_id=%s", (hotel_id,))
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


def list_hotels_for_ui(active_only=True, hotel_id=None):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        query = "SELECT hotel_id, hotel_name, is_active FROM hotels"
        conditions = []
        params = []

        if active_only:
            conditions.append("is_active = TRUE")
        if hotel_id is not None:
            conditions.append("hotel_id = %s")
            params.append(hotel_id)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY hotel_name ASC"
        cur.execute(query, tuple(params))
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def get_active_hotels():
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT hotel_id, place_id
            FROM hotels
            WHERE is_active = TRUE
            ORDER BY hotel_id
            """
        )
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def get_admin_overview():
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT
                COUNT(*) AS total_hotels,
                SUM(CASE WHEN is_active = TRUE THEN 1 ELSE 0 END) AS active_hotels
            FROM hotels
            """
        )
        hotels = cur.fetchone() or {}

        cur.execute(
            """
            SELECT
                COUNT(*) AS total_users,
                SUM(CASE WHEN role = 'admin' THEN 1 ELSE 0 END) AS total_admins,
                SUM(CASE WHEN role = 'user' THEN 1 ELSE 0 END) AS total_regular_users
            FROM users
            """
        )
        users = cur.fetchone() or {}

        cur.execute("SELECT COUNT(*) AS total_reviews FROM hotel_reviews")
        reviews = cur.fetchone() or {}

        cur.execute("SELECT COUNT(*) AS total_sentiments FROM sentiment_reviews")
        sentiments = cur.fetchone() or {}

        cur.execute("SELECT COUNT(*) AS total_subscribers FROM telegram_users WHERE subscribed = TRUE")
        subscribers = cur.fetchone() or {}

        cur.execute("SELECT COUNT(*) AS total_notifications FROM notifications")
        notifications = cur.fetchone() or {}

        cur.execute(
            """
            SELECT
                h.hotel_id,
                h.hotel_name,
                COUNT(hr.review_id) AS review_count
            FROM hotels h
            LEFT JOIN hotel_reviews hr ON hr.hotel_id = h.hotel_id
            GROUP BY h.hotel_id, h.hotel_name
            ORDER BY review_count DESC, h.hotel_name ASC
            LIMIT 8
            """
        )
        top_hotels = cur.fetchall() or []

        cur.execute(
            """
            SELECT username, role, created_at
            FROM users
            ORDER BY created_at DESC
            LIMIT 8
            """
        )
        recent_users = cur.fetchall() or []

        return {
            "total_hotels": int(hotels.get("total_hotels") or 0),
            "active_hotels": int(hotels.get("active_hotels") or 0),
            "total_users": int(users.get("total_users") or 0),
            "total_admins": int(users.get("total_admins") or 0),
            "total_regular_users": int(users.get("total_regular_users") or 0),
            "total_reviews": int(reviews.get("total_reviews") or 0),
            "total_sentiments": int(sentiments.get("total_sentiments") or 0),
            "total_subscribers": int(subscribers.get("total_subscribers") or 0),
            "total_notifications": int(notifications.get("total_notifications") or 0),
            "top_hotels": top_hotels,
            "recent_users": recent_users,
        }
    finally:
        cur.close()
        conn.close()


def set_hotel_active_status(hotel_id, is_active):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE hotels SET is_active = %s WHERE hotel_id = %s",
            (bool(is_active), hotel_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def get_hotel_dependency_summary(hotel_id):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        summary = {}
        queries = {
            "users": "SELECT COUNT(*) AS total FROM users WHERE hotel_id = %s",
            "hotel_reviews": "SELECT COUNT(*) AS total FROM hotel_reviews WHERE hotel_id = %s",
            "sentiment_reviews": "SELECT COUNT(*) AS total FROM sentiment_reviews WHERE hotel_id = %s",
            "telegram_users": "SELECT COUNT(*) AS total FROM telegram_users WHERE hotel_id = %s",
            "notifications": "SELECT COUNT(*) AS total FROM notifications WHERE hotel_id = %s",
        }
        for key, query in queries.items():
            cur.execute(query, (hotel_id,))
            row = cur.fetchone() or {}
            summary[key] = int(row.get("total") or 0)
        return summary
    finally:
        cur.close()
        conn.close()


def delete_hotel_permanently(hotel_id):
    summary = get_hotel_dependency_summary(hotel_id)
    blockers = {k: v for k, v in summary.items() if v > 0}
    if blockers:
        detail = ", ".join(f"{k}={v}" for k, v in blockers.items())
        raise ValueError(f"Hotel masih memiliki data terkait: {detail} Nonaktifkan saja atau hapus data terkait terlebih dahulu")

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM hotels WHERE hotel_id = %s", (hotel_id,))
        conn.commit()
    finally:
        cur.close()
        conn.close()


def list_admin_table_catalog():
    table_specs = [
        {
            "key": "hotels",
            "label": "Hotels",
            "description": "Master data hotel ke sistem monitoring",
            "icon": "bi-building",
            "variant": "primary",
            "manage_scope": "full",
        },
        {
            "key": "users",
            "label": "Users",
            "description": "Akun login aplikasi dan hak akses hotel",
            "icon": "bi-people",
            "variant": "info",
            "manage_scope": "limited",
        },
        {
            "key": "hotel_reviews",
            "label": "Hotel Reviews",
            "description": "Review mentah hasil scraping Google Maps",
            "icon": "bi-chat-left-text",
            "variant": "success",
            "manage_scope": "read_only",
        },
        {
            "key": "sentiment_reviews",
            "label": "Sentiment Reviews",
            "description": "Hasil klasifikasi sentimen dari review hotel",
            "icon": "bi-emoji-smile",
            "variant": "warning",
            "manage_scope": "read_only",
        },
        {
            "key": "notifications",
            "label": "Notifications",
            "description": "Riwayat notifikasi ke subscriber Telegram",
            "icon": "bi-bell",
            "variant": "danger",
            "manage_scope": "read_only",
        },
        {
            "key": "telegram_users",
            "label": "Telegram Users",
            "description": "Subscriber aktif Telegram Bot untuk hotel",
            "icon": "bi-telegram",
            "variant": "secondary",
            "manage_scope": "limited",
        },
    ]

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        rows = []
        for spec in table_specs:
            table_name = spec["key"]
            cur.execute(f"SELECT COUNT(*) AS total_rows FROM {table_name}")
            count_row = cur.fetchone() or {}

            cur.execute(
                """
                SELECT
                    ROUND((data_length + index_length) / 1024, 1) AS size_kb
                FROM information_schema.TABLES
                WHERE table_schema = DATABASE() AND table_name = %s
                """,
                (table_name,),
            )
            size_row = cur.fetchone() or {}

            cur.execute(
                """
                SELECT COLUMN_NAME
                FROM information_schema.COLUMNS
                WHERE table_schema = DATABASE() AND table_name = %s
                ORDER BY ORDINAL_POSITION
                LIMIT 6
                """,
                (table_name,),
            )
            preview_cols = [r["COLUMN_NAME"] for r in (cur.fetchall() or [])]

            rows.append(
                {
                    **spec,
                    "total_rows": int(count_row.get("total_rows") or 0),
                    "size_kb": float(size_row.get("size_kb") or 0),
                    "preview_columns": preview_cols,
                }
            )
        return rows
    finally:
        cur.close()
        conn.close()


def get_admin_table_preview(table_name, limit=8, page=1, search=""):
    allowed = {
        "hotels": {
            "order_candidates": ["hotel_id", "manajemen_hotel_id", "created_at"],
            "preferred_columns": [
                "hotel_id",
                "manajemen_hotel_id",
                "hotel_name",
                "address",
                "place_id",
                "google_place_id",
                "scrape_interval_minutes",
                "is_active",
            ],
        },
        "users": {
            "order_candidates": ["user_id", "created_at"],
            "preferred_columns": [
                "user_id",
                "username",
                "role",
                "hotel_id",
                "created_at",
            ],
        },
        "hotel_reviews": {
            "order_candidates": ["review_id", "review_date", "created_at"],
            "preferred_columns": [
                "review_id",
                "hotel_id",
                "user_name",
                "rating",
                "review_text",
                "source",
                "review_date",
            ],
        },
        "sentiment_reviews": {
            "order_candidates": ["sentiment_id", "review_date", "created_at"],
            "preferred_columns": [
                "sentiment_id",
                "review_id",
                "hotel_id",
                "user_name",
                "sentiment_nb",
                "sentiment_svm",
                "review_date",
            ],
        },
        "notifications": {
            "order_candidates": ["notification_id", "created_at", "review_id"],
            "preferred_columns": [
                "notification_id",
                "review_id",
                "chat_id",
                "hotel_id",
                "status",
                "created_at",
            ],
        },
        "telegram_users": {
            "order_candidates": ["id", "created_at", "chat_id"],
            "preferred_columns": [
                "id",
                "chat_id",
                "hotel_id",
                "subscribed",
                "created_at",
            ],
        },
    }

    spec = allowed.get(table_name)
    if not spec:
        raise ValueError("Unsupported admin table.")

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT COLUMN_NAME
            FROM information_schema.COLUMNS
            WHERE table_schema = DATABASE() AND table_name = %s
            ORDER BY ORDINAL_POSITION
            """,
            (table_name,),
        )
        actual_columns = [r["COLUMN_NAME"] for r in (cur.fetchall() or [])]
        if not actual_columns:
            return {"table_name": table_name, "columns": [], "rows": [], "total_rows": 0, "page": 1, "limit": 0, "total_pages": 1, "search": ""}

        selected_columns = [c for c in spec["preferred_columns"] if c in actual_columns]
        if not selected_columns:
            selected_columns = actual_columns[:6]

        order_by_column = next((c for c in spec["order_candidates"] if c in actual_columns), actual_columns[0])
        safe_limit = max(1, min(int(limit or 8), 50))
        safe_page = max(1, int(page or 1))
        search_term = (search or "").strip()
        offset = (safe_page - 1) * safe_limit
        where_clauses = []
        params = []

        if search_term and table_name == "hotel_reviews":
            where_clauses.append("(CAST(review_id AS CHAR) LIKE %s OR CAST(hotel_id AS CHAR) LIKE %s OR user_name LIKE %s OR review_text LIKE %s OR source LIKE %s)")
            like = f"%{search_term}%"
            params.extend([like, like, like, like, like])
        elif search_term and table_name == "sentiment_reviews":
            where_clauses.append("(CAST(sentiment_id AS CHAR) LIKE %s OR CAST(review_id AS CHAR) LIKE %s OR CAST(hotel_id AS CHAR) LIKE %s OR user_name LIKE %s OR sentiment_nb LIKE %s OR sentiment_svm LIKE %s)")
            like = f"%{search_term}%"
            params.extend([like, like, like, like, like, like])

        where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        count_query = f"SELECT COUNT(*) AS total_rows FROM {table_name}{where_sql}"
        cur.execute(count_query, tuple(params))
        count_row = cur.fetchone() or {}
        total_rows = int(count_row.get("total_rows") or 0)
        total_pages = max(1, (total_rows + safe_limit - 1) // safe_limit)
        if safe_page > total_pages:
            safe_page = total_pages
            offset = (safe_page - 1) * safe_limit

        column_sql = ", ".join(selected_columns)
        query = f"SELECT {column_sql} FROM {table_name}{where_sql} ORDER BY {order_by_column} DESC LIMIT %s OFFSET %s"
        cur.execute(query, tuple(params + [safe_limit, offset]))
        rows = cur.fetchall() or []
        return {
            "table_name": table_name,
            "columns": selected_columns,
            "rows": rows,
            "total_rows": total_rows,
            "page": safe_page,
            "limit": safe_limit,
            "total_pages": total_pages,
            "search": search_term,
        }
    finally:
        cur.close()
        conn.close()


def get_hotel_review_by_id(review_id):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM hotel_reviews WHERE review_id = %s", (review_id,))
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


def get_sentiment_review_by_id(sentiment_id):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM sentiment_reviews WHERE sentiment_id = %s", (sentiment_id,))
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


def list_recent_hotel_reviews_for_admin(limit=50):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT review_id, hotel_id, user_name, rating, review_date
            FROM hotel_reviews
            ORDER BY review_date DESC, review_id DESC
            LIMIT %s
            """,
            (limit,),
        )
        return cur.fetchall() or []
    finally:
        cur.close()
        conn.close()


# Backward-compatible aliases while the rest of the app is being cleaned up.
def get_admin_table_catalog():
    return list_admin_table_catalog()


def get_recent_hotel_reviews_for_admin(limit=50):
    return list_recent_hotel_reviews_for_admin(limit=limit)


def update_hotel_review_admin(review_id, hotel_id, user_name, review_text, rating, review_date, source):
    conn = get_connection()
    cur = conn.cursor()
    try:
        normalized_date = _normalize_review_date(review_date)
        cur.execute(
            """
            UPDATE hotel_reviews
            SET hotel_id = %s,
                user_name = %s,
                review_text = %s,
                rating = %s,
                review_date = %s,
                source = %s
            WHERE review_id = %s
            """,
            (hotel_id, user_name, review_text, rating, normalized_date, source, review_id),
        )
        cur.execute(
            """
            UPDATE sentiment_reviews
            SET hotel_id = %s,
                user_name = %s,
                review_text = %s,
                rating = %s,
                review_date = %s,
                source = %s
            WHERE review_id = %s
            """,
            (hotel_id, user_name, review_text, rating, normalized_date, source, review_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def delete_hotel_review_admin(review_id):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM sentiment_reviews WHERE review_id = %s", (review_id,))
        related_count = int(cur.fetchone()[0] or 0)
        if related_count > 0:
            raise ValueError("Review ini masih terhubung dengan data sentiment_reviews. Hapus data sentimen terkait terlebih dahulu.")

        cur.execute("DELETE FROM hotel_reviews WHERE review_id = %s", (review_id,))
        conn.commit()
    finally:
        cur.close()
        conn.close()


def create_sentiment_review_admin(review_id, sentiment_nb, sentiment_svm, source="Google Maps"):
    base_review = get_hotel_review_by_id(review_id)
    if not base_review:
        raise ValueError("Review dasar tidak ditemukan.")

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM sentiment_reviews WHERE review_id = %s", (review_id,))
        existing_count = int(cur.fetchone()[0] or 0)
        if existing_count > 0:
            raise ValueError("Sentiment review untuk review_id ini sudah ada.")

        cur.execute(
            """
            INSERT INTO sentiment_reviews
                (review_id, hotel_id, user_name, review_text, rating, review_date, sentiment_nb, sentiment_svm, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                base_review["review_id"],
                base_review["hotel_id"],
                base_review["user_name"],
                base_review.get("review_text"),
                base_review["rating"],
                _normalize_review_date(base_review.get("review_date")),
                sentiment_nb,
                sentiment_svm,
                source,
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        cur.close()
        conn.close()


def update_sentiment_review_admin(sentiment_id, sentiment_nb, sentiment_svm, source):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE sentiment_reviews
            SET sentiment_nb = %s,
                sentiment_svm = %s,
                source = %s
            WHERE sentiment_id = %s
            """,
            (sentiment_nb, sentiment_svm, source, sentiment_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def delete_sentiment_review_admin(sentiment_id):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM sentiment_reviews WHERE sentiment_id = %s", (sentiment_id,))
        conn.commit()
    finally:
        cur.close()
        conn.close()


# Reviews + Sentiment

def _normalize_review_date(review_date):
    if isinstance(review_date, datetime):
        return review_date
    if isinstance(review_date, str):
        try:
            return datetime.fromisoformat(review_date)
        except Exception:
            return datetime.now()
    if isinstance(review_date, (int, float)):
        try:
            return datetime.fromtimestamp(review_date)
        except Exception:
            return datetime.now()
    return datetime.now()


def save_hotel_review(hotel_id, user_name, review_text, rating, review_date=None, source="Google Maps"):
    conn = get_connection()
    cur = conn.cursor()
    try:
        normalized_date = _normalize_review_date(review_date)
        cur.execute(
            """
            INSERT INTO hotel_reviews (hotel_id, user_name, review_text, rating, review_date, source)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (hotel_id, user_name, review_text, rating, normalized_date, source),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        cur.close()
        conn.close()


def save_sentiment_review(review_id, hotel_id, user_name, review_text, rating, review_date, nb, svm, source="Google Maps"):
    conn = get_connection()
    cur = conn.cursor()
    try:
        normalized_date = _normalize_review_date(review_date)
        cur.execute(
            """
            INSERT INTO sentiment_reviews
                (review_id, hotel_id, user_name, review_text, rating, review_date, sentiment_nb, sentiment_svm, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (review_id, hotel_id, user_name, review_text, rating, normalized_date, nb, svm, source),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        cur.close()
        conn.close()


def review_exists(hotel_id, user_name, text, rating, source):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if text is None:
            query = """
                SELECT review_id
                FROM hotel_reviews
                WHERE hotel_id = %s AND user_name = %s
                  AND review_text IS NULL AND rating = %s AND source = %s
                LIMIT 1
            """
            params = (hotel_id, user_name, rating, source)
        else:
            query = """
                SELECT review_id
                FROM hotel_reviews
                WHERE hotel_id = %s AND user_name = %s
                  AND review_text = %s AND rating = %s AND source = %s
                LIMIT 1
            """
            params = (hotel_id, user_name, text, rating, source)

        cur.execute(query, params)
        return cur.fetchone() is not None
    finally:
        cur.close()
        conn.close()


def get_reviews_by_hotel(hotel_id):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM hotel_reviews WHERE hotel_id = %s", (hotel_id,))
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def get_latest_reviews(hotel_id, limit=1):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT user_name, review_text, rating, source, review_date, sentiment_nb, sentiment_svm
            FROM sentiment_reviews
            WHERE hotel_id = %s
            ORDER BY review_date DESC
            LIMIT %s
            """,
            (hotel_id, limit),
        )
        return cur.fetchall() or []
    finally:
        cur.close()
        conn.close()


def list_sentiments(hotel_id, limit=200, search=None):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        query = """
            SELECT s.*, h.review_text AS raw_text
            FROM sentiment_reviews s
            LEFT JOIN hotel_reviews h ON h.review_id = s.review_id
            WHERE s.hotel_id = %s
        """
        params = [hotel_id]

        if search and str(search).strip():
            like = f"%{str(search).strip()}%"
            query += """
                AND (
                    CAST(s.review_id AS CHAR) LIKE %s
                    OR CAST(s.hotel_id AS CHAR) LIKE %s
                    OR s.user_name LIKE %s
                    OR s.review_text LIKE %s
                    OR s.sentiment_nb LIKE %s
                    OR s.sentiment_svm LIKE %s
                    OR s.source LIKE %s
                )
            """
            params.extend([like, like, like, like, like, like, like])

        query += " ORDER BY s.review_date DESC"
        if limit is not None and int(limit) > 0:
            query += " LIMIT %s"
            params.append(int(limit))

        cur.execute(query, tuple(params))
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


# Analytics

def count_sentiments(hotel_id):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT sentiment_nb, COUNT(*)
            FROM sentiment_reviews
            WHERE hotel_id = %s
            GROUP BY sentiment_nb
            """,
            (hotel_id,),
        )
        rows = cur.fetchall()
        return {r[0]: r[1] for r in rows}
    finally:
        cur.close()
        conn.close()


def trend_reviews(hotel_id, days=30):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT DATE(review_date) AS d, COUNT(*) AS cnt
            FROM sentiment_reviews
            WHERE hotel_id = %s AND review_date >= (NOW() - INTERVAL %s DAY)
            GROUP BY DATE(review_date)
            ORDER BY d
            """,
            (hotel_id, days),
        )
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def get_trend_sentiment(hotel_id, days=30):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT DATE(COALESCE(review_date, created_at)) AS d,
                   SUM(CASE WHEN LOWER(sentiment_nb) LIKE 'posit%' THEN 1 ELSE 0 END) AS pos,
                   SUM(CASE WHEN LOWER(sentiment_nb) LIKE 'negat%' THEN 1 ELSE 0 END) AS neg
            FROM sentiment_reviews
            WHERE hotel_id = %s
              AND COALESCE(review_date, created_at) >= CURDATE() - INTERVAL %s DAY
            GROUP BY d
            ORDER BY d
            """,
            (hotel_id, days),
        )
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def get_review_stats(hotel_id):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT COUNT(*) AS total FROM sentiment_reviews WHERE hotel_id=%s", (hotel_id,))
        total = cur.fetchone()["total"]

        cur.execute(
            """
            SELECT COUNT(*) AS c
            FROM sentiment_reviews
            WHERE hotel_id=%s AND review_date >= CURDATE() - INTERVAL 7 DAY
            """,
            (hotel_id,),
        )
        this_week = cur.fetchone()["c"]

        cur.execute(
            """
            SELECT COUNT(*) AS c
            FROM sentiment_reviews
            WHERE hotel_id=%s
              AND review_date >= CURDATE() - INTERVAL 14 DAY
              AND review_date < CURDATE() - INTERVAL 7 DAY
            """,
            (hotel_id,),
        )
        last_week = cur.fetchone()["c"]

        return total, this_week - last_week
    finally:
        cur.close()
        conn.close()


def get_weekly_comparison(hotel_id):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT
              SUM(CASE WHEN YEARWEEK(review_date, 1) = YEARWEEK(CURDATE(), 1) THEN 1 ELSE 0 END) AS this_week,
              SUM(CASE WHEN YEARWEEK(review_date, 1) = YEARWEEK(CURDATE(), 1) - 1 THEN 1 ELSE 0 END) AS last_week
            FROM hotel_reviews
            WHERE hotel_id = %s
            """,
            (hotel_id,),
        )
        row = cur.fetchone() or {}
        return {
            "this_week": row.get("this_week") or 0,
            "last_week": row.get("last_week") or 0,
        }
    finally:
        cur.close()
        conn.close()


def get_rating_distribution(hotel_id):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT rating, COUNT(*) AS count
            FROM hotel_reviews
            WHERE hotel_id = %s
            GROUP BY rating
            """,
            (hotel_id,),
        )
        rows = cur.fetchall()

        dist = {i: 0 for i in range(1, 6)}
        for row in rows:
            dist[row["rating"]] = row["count"]
        return dist
    finally:
        cur.close()
        conn.close()


def get_average_rating(hotel_id):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT AVG(rating) FROM hotel_reviews WHERE hotel_id = %s", (hotel_id,))
        avg = cur.fetchone()[0]
        return round(avg, 2) if avg else 0.0
    finally:
        cur.close()
        conn.close()

_STOPWORDS_CSV_CACHE = None

def _load_stopwords_csv():
    global _STOPWORDS_CSV_CACHE
    if _STOPWORDS_CSV_CACHE is not None:
        return _STOPWORDS_CSV_CACHE

    words = set()
    csv_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "analisis", "data", "raw", "stopword_aveta.csv")
    )
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            # skip header
            next(reader, None)
            for row in reader:
                if not row:
                    continue
                w = row[0].strip().lower()
                if w:
                    words.add(w)
    except Exception:
        words = set()

    _STOPWORDS_CSV_CACHE = words
    return words


def _compute_tfidf_scores(docs):
    # docs: list[list[str]]
    if not docs:
        return Counter()

    df = Counter()
    for doc in docs:
        if doc:
            df.update(set(doc))

    total_docs = len(docs)
    scores = Counter()
    for doc in docs:
        if not doc:
            continue
        tf = Counter(doc)
        doc_len = len(doc)
        for term, cnt in tf.items():
            tf_norm = cnt / doc_len
            idf = math.log((total_docs + 1) / (df[term] + 1)) + 1.0
            scores[term] += tf_norm * idf
    return scores


def get_top_keywords(hotel_id, limit=10, lang="id"):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT review_text, sentiment_nb FROM sentiment_reviews WHERE hotel_id=%s", (hotel_id,))
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    stopwords_id = {
        "dan", "yang", "di", "ke", "dari", "itu", "ini", "ada", "okekkk", "sangat",
        "saya", "juga", "untuk", "ya", "kalo", "klo", "ga", "ok", "oke", "udah",
        "sudah", "aja", "tapi", "dengan", "karena", "jadi", "kalau", "kami", "kamu",
        "mereka", "dia", "aku", "nya", "yg", "dr", "jg", "tdk", "krn", "bgt", "lain",
    }
    stopwords_en = {
        "the", "and", "to", "of", "in", "is", "it", "for", "on", "with", "this", "that",
        "a", "an", "or", "but", "if", "as", "at", "by", "from", "be", "are", "was", "were",
        "i", "you", "we", "they", "he", "she", "my", "your", "our", "their", "not", "very",
    }
    stopwords_csv = _load_stopwords_csv()
    base_stopwords = stopwords_id if lang == "id" else stopwords_en
    stopwords = base_stopwords.union(stopwords_csv)

    pos_docs = []
    neg_docs = []
    pos_counts = Counter()
    neg_counts = Counter()

    for row in rows:
        text = row.get("review_text")
        if not text:
            continue
        words = re.findall(r"\b\w+\b", text.lower())
        words = [w for w in words if w not in stopwords and len(w) > 2]

        if row.get("sentiment_nb") == "POSITIF":
            pos_docs.append(words)
            pos_counts.update(words)
        elif row.get("sentiment_nb") == "NEGATIF":
            neg_docs.append(words)
            neg_counts.update(words)

    pos_scores = _compute_tfidf_scores(pos_docs)
    neg_scores = _compute_tfidf_scores(neg_docs)

    # limit <= 0 or None means return all words sorted by score.
    def _top_items(scores, counts):
        items = [(w, s, int(counts.get(w, 0))) for w, s in scores.items()]
        items.sort(key=lambda x: x[1], reverse=True)
        if limit is None or int(limit) <= 0:
            return items
        return items[: int(limit)]

    return {
        "positive": _top_items(pos_scores, pos_counts),
        "negative": _top_items(neg_scores, neg_counts),
    }


# Subscribers + Notifications

def save_telegram_user(chat_id, hotel_id=None):
    if hotel_id is None:
        return False

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO telegram_users (chat_id, hotel_id, subscribed)
            VALUES (%s, %s, TRUE)
            ON DUPLICATE KEY UPDATE subscribed=TRUE
            """,
            (chat_id, hotel_id),
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        cur.close()
        conn.close()


def get_subscribers(hotel_id):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT * FROM telegram_users WHERE hotel_id=%s AND subscribed=TRUE ORDER BY created_at DESC",
            (hotel_id,),
        )
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def add_subscriber(chat_id, hotel_id):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO telegram_users (chat_id, hotel_id, subscribed)
            VALUES (%s, %s, TRUE)
            ON DUPLICATE KEY UPDATE subscribed=TRUE
            """,
            (chat_id, hotel_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def remove_subscriber(chat_id, hotel_id):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE telegram_users SET subscribed=FALSE WHERE chat_id=%s AND hotel_id=%s",
            (chat_id, hotel_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def log_notification(review_id, chat_id, hotel_id, status, message_text=None):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO notifications (review_id, chat_id, hotel_id, status, created_at)
            VALUES (%s, %s, %s, %s, NOW())
            """,
            (review_id, chat_id, hotel_id, status),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def get_notifications(hotel_id, limit=None, search=None):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        base_query = """
            SELECT n.*, s.review_text, s.sentiment_nb, s.sentiment_svm
            FROM notifications n
            LEFT JOIN sentiment_reviews s ON s.review_id = n.review_id
            WHERE n.hotel_id = %s
        """
        params = [hotel_id]

        if search and str(search).strip():
            like = f"%{str(search).strip()}%"
            base_query += """
                AND (
                    CAST(n.review_id AS CHAR) LIKE %s
                    OR CAST(n.chat_id AS CHAR) LIKE %s
                    OR n.status LIKE %s
                    OR CAST(n.created_at AS CHAR) LIKE %s
                    OR s.review_text LIKE %s
                    OR s.sentiment_nb LIKE %s
                    OR s.sentiment_svm LIKE %s
                )
            """
            params.extend([like, like, like, like, like, like, like])

        base_query += " ORDER BY n.created_at DESC"
        if limit is not None and int(limit) > 0:
            base_query += " LIMIT %s"
            params.append(int(limit))

        cur.execute(base_query, tuple(params))
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()
