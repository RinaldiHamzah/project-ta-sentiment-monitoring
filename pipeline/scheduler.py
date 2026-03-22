# pipeline/scheduler.py
import schedule
import time
import logging
import multiprocessing
from pipeline.pipeline import run_pipeline

logger = logging.getLogger("scheduler")
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")

# Event untuk menghentikan scheduler
STOP_EVENT = multiprocessing.Event()

def _run_scheduled_pipeline(hotel_id=None):
    try:
        results = run_pipeline(hotel_id=hotel_id)
        logger.info("Scheduled pipeline result: %s", results)
    except Exception as e:
        logger.exception("Scheduled pipeline error: %s", e)

def scheduler_loop(interval_minutes: int = 2, hotel_id=None):
    """
    Loop utama scheduler dengan kemampuan berhenti menggunakan STOP_EVENT.
    - hotel_id=None: jalankan untuk semua hotel aktif
    - hotel_id=int : jalankan hanya untuk hotel tersebut
    """
    schedule.clear()
    schedule.every(interval_minutes).minutes.do(_run_scheduled_pipeline, hotel_id=hotel_id)
    scope = f"hotel_id={hotel_id}" if hotel_id is not None else "all active hotels"
    logger.info("Scheduler aktif setiap %s menit (%s).", interval_minutes, scope)

    while not STOP_EVENT.is_set():
        schedule.run_pending()
        time.sleep(1)

    logger.info("Scheduler dihentikan dengan aman.")

def start_scheduler(interval_minutes: int = 2, hotel_id=None):
    """Start scheduler di proses terpisah."""
    STOP_EVENT.clear()
    scheduler_process = multiprocessing.Process(
        target=scheduler_loop,
        args=(interval_minutes, hotel_id),
    )
    scheduler_process.start()
    logger.info("Scheduler dijalankan (PID=%s)", scheduler_process.pid)
    return scheduler_process

def stop_scheduler():
    """Stop scheduler yang sedang berjalan."""
    STOP_EVENT.set()
    logger.info("STOP_EVENT dikirim ke scheduler.")

