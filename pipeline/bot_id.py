# pipeline/bot_id.py
import os
import json
import logging
import asyncio
import platform
import multiprocessing
from telegram.request import HTTPXRequest
from telegram.error import TimedOut, NetworkError
from typing import Optional
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
STOP_EVENT = multiprocessing.Event()


# Prefer token dari config, lalu env var
try:
    import config
    BOT_TOKEN = getattr(config, "TELEGRAM_BOT_TOKEN", None)
except Exception:
    BOT_TOKEN = None

if not BOT_TOKEN:
    BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

logger = logging.getLogger("telegram_bot")
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")

# Try import save_telegram_user from your mysql connector.
# Jika tidak tersedia (mis. saat pengujian), fallback menulis ke subscribers.json.
try:
    from pipeline.mysql_connector import save_telegram_user, get_hotel  # type: ignore
    _HAS_DB_SAVE = True
    logger.info("Using pipeline.mysql_connector.save_telegram_user")
except Exception:
    _HAS_DB_SAVE = False
    SUBS_FILE = os.path.join(os.path.dirname(__file__), "subscribers.json")
    logger.warning("pipeline.mysql_connector.save_telegram_user not found — using local JSON fallback (%s)", SUBS_FILE)

    def save_telegram_user(chat_id: int, hotel_id: int) -> bool:
        """
        Simple fallback: simpan pasangan chat_id + hotel_id ke subscribers.json
        Return True on success.
        """
        try:
            data = []
            if os.path.exists(SUBS_FILE):
                with open(SUBS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f) or []
            row = {"chat_id": int(chat_id), "hotel_id": int(hotel_id)}
            if row not in data:
                data.append(row)
                with open(SUBS_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            return True
        except Exception as e:
            logger.exception("Failed to save chat_id to fallback file: %s", e)
            return False

    def get_hotel(hotel_id: int):
        return {"hotel_id": hotel_id, "hotel_name": f"Hotel {hotel_id}"}

# Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler untuk /start:
    - ambil chat_id
    - simpan ke DB (dijalankan via asyncio.to_thread agar tidak block)
    - balas pesan ke user
    """
    chat = update.effective_chat
    if chat is None:
        logger.warning("Start called but effective_chat is None")
        return

    chat_id = chat.id
    logger.info("Received /start from chat_id=%s", chat_id)

    hotel_id = None
    if context.args:
        try:
            hotel_id = int(context.args[0])
        except Exception:
            hotel_id = None

    if not hotel_id:
        await update.effective_message.reply_text(
            "Gunakan format: /start <hotel_id>. Contoh: /start 1"
        )
        return

    hotel = None
    try:
        hotel = await asyncio.to_thread(get_hotel, hotel_id)
    except Exception:
        hotel = None
    if not hotel:
        await update.effective_message.reply_text("hotel_id tidak valid / tidak ditemukan.")
        return

    saved = False
    try:
        # run DB save in thread to avoid blocking the async event loop
        saved = await asyncio.to_thread(save_telegram_user, chat_id, hotel_id)
    except Exception:
        logger.exception("Exception when saving chat_id via save_telegram_user")

    if saved:
        hname = hotel.get("hotel_name") if isinstance(hotel, dict) else getattr(hotel, "hotel_name", str(hotel_id))
        reply = f"Berhasil subscribe notifikasi untuk hotel: {hname} (ID: {hotel_id})."
    else:
        reply = "Gagal menyimpan subscriber. Coba lagi."
    try:
        # Prefer effective_message which is safe for callbacks from different update types
        await update.effective_message.reply_text(reply)
    except Exception:
        logger.exception("Failed sending reply to /start")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Simple echo handler for non-command text messages.
    """
    text = update.effective_message.text if update.effective_message else ""
    logger.debug("Echoing message from %s: %s", update.effective_chat.id if update.effective_chat else "?", text)
    try:
        await update.effective_message.reply_text(f"Kamu menulis: {text}")
    except Exception:
        logger.exception("Failed sending echo reply")

# Runner
def run_bot(token: Optional[str] = None):
    """
    Jalankan bot Telegram dalam proses terpisah.
    Dapat dihentikan dengan aman menggunakan STOP_EVENT dari Flask controller.
    Aman untuk multiprocessing Flask.
    """
    
    # Kompatibilitas Windows event loop
    if os.name == "nt" or platform.system().lower().startswith("win"):
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except Exception:
            logger.warning("Gagal set WindowsSelectorEventLoopPolicy")

    token = token or BOT_TOKEN or os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Telegram bot token tidak ditemukan")

    # Tambahkan konfigurasi timeout dan retry agar bot tidak freeze
    request = HTTPXRequest(
        connect_timeout=10.0,
        read_timeout=20.0,
        write_timeout=10.0,
        pool_timeout=5.0,
    )

    app = ApplicationBuilder().token(token).request(request).build()
    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), echo))

    async def _main():
        """Loop utama bot yang berhenti jika STOP_EVENT diset."""
        while True:
            try:
                async with app:
                    await app.start()
                    await app.updater.start_polling(drop_pending_updates=True)
                    logger.info("Bot aktif ")

                    # Loop sampai ada STOP_EVENT
                    while not STOP_EVENT.is_set():
                        await asyncio.sleep(1)

                    logger.info("STOP_EVENT diterima")
                    await app.updater.stop()
                    await app.stop()
                    break  # keluar dari while True setelah stop event
            except (TimedOut, NetworkError) as e:
                logger.warning(f"Jaringan terputus ({e}), ulang dalam 10 detik...")
                await asyncio.sleep(10)
            except Exception as e:
                logger.exception(f"Kesalahan tak terduga di loop utama: {e}")
                await asyncio.sleep(10)

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        logger.info("Bot dihentikan secara manual.")
    except Exception as e:
        logger.exception(f"Bot error: {e}")
    finally:
        logger.info("Bot telah berhenti ")

# Allow running the bot directly for local testing
if __name__ == "__main__":
    run_bot()

