# pipeline/notif_telegram.py
import os
import requests
import config
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from pipeline.mysql_connector import (
    get_connection,
    get_hotel,
    get_subscribers,
    save_telegram_user,)
def _get_bot_token():
    # Single source of truth: root config.py (which loads .env).
    return (getattr(config, "TELEGRAM_BOT_TOKEN", None) or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()

def send_message(chat_id, message):
    bot_token = _get_bot_token()
    if not bot_token:
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    try:
        response = requests.post(url, data=payload, timeout=12)
        return response.status_code == 200
    except Exception:
        return False


def _get_review_time_by_review_id(review_id):
    if not review_id:
        return "-"

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT review_date FROM hotel_reviews WHERE review_id=%s", (review_id,))
        row = cur.fetchone()
        if row and row.get("review_date"):
            return row["review_date"].strftime("%d/%m/%Y %H:%M:%S")
        return "-"
    finally:
        cur.close()
        conn.close()


def send_telegram_to_user(chat_id, review_id, review_text, sentiment_nb, sentiment_svm, rating=None, user="System"):
    review_time = _get_review_time_by_review_id(review_id)

    msg = (
        "?? <b>Review Baru</b>\n"
        f"?? <b>User:</b> {user}\n"
        f"? <b>Rating:</b> {rating}\n"
        f"?? <b>Review:</b> {(review_text or '-')[:400]}\n"
        f"?? <b>Naive Bayes:</b> {sentiment_nb}\n"
        f"? <b>Support Vector Machine:</b> {sentiment_svm}\n"
        f"?? <b>Waktu:</b> {review_time}"
    )
    return send_message(chat_id, msg)


def broadcast_telegram(hotel_id, review_id, review_text, sentiment_nb, sentiment_svm, rating=None, user="System"):
    subs = get_subscribers(hotel_id)
    sent = failed = 0

    for s in subs:
        ok = send_telegram_to_user(
            chat_id=s["chat_id"],
            review_id=review_id,
            review_text=review_text,
            sentiment_nb=sentiment_nb,
            sentiment_svm=sentiment_svm,
            rating=rating,
            user=user,
        )
        if ok:
            sent += 1
        else:
            failed += 1

    return {"sent": sent, "failed": failed}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id if update.effective_chat else None
    if not chat_id:
        return

    # Format: /start <hotel_id>
    hotel_id = None
    if context.args:
        try:
            hotel_id = int(context.args[0])
        except Exception:
            hotel_id = None

    if not hotel_id:
        await update.message.reply_text(
            "Kirim /start <hotel_id> untuk subscribe. Contoh: /start 1"
        )
        return

    hotel = get_hotel(hotel_id)
    if not hotel:
        await update.message.reply_text("Hotel tidak ditemukan. Cek kembali hotel_id.")
        return

    ok = save_telegram_user(chat_id, hotel_id)
    if ok:
        await update.message.reply_text(
            f"Berhasil subscribe notifikasi untuk hotel: {hotel.get('hotel_name', hotel_id)}"
        )
    else:
        await update.message.reply_text("Gagal menyimpan subscriber. Coba lagi.")

def run_bot():
    bot_token = _get_bot_token()
    if not bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN tidak tersedia di config/env")

    app = ApplicationBuilder().token(bot_token).build()
    app.add_handler(CommandHandler("start", start))
    print("[INFO] Bot Telegram berjalan...")
    app.run_polling()

if __name__ == "__main__":
    run_bot()
