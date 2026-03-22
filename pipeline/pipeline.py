# pipeline/pipeline.py
import json
from datetime import datetime
import config
from pipeline.model_predict import ModelPredict
from pipeline.notif_telegram import send_telegram_to_user
from pipeline.scraper import scrape_latest_review, parse_review_time as normalize_review_time
from pipeline.mysql_connector import (
    save_hotel_review,
    save_sentiment_review,
    log_notification,
    get_active_hotels,
    get_hotel,
    get_subscribers,
    review_exists,
)

MODEL = ModelPredict()


def normalize_sentiment(label, rating=None):
    t = str(label or "").strip().lower()
    if "positif" in t or "positive" in t or t in ("pos", "p"):
        return "POSITIF"
    if "negatif" in t or "negative" in t or t in ("neg", "n"):
        return "NEGATIF"

    if rating is not None:
        try:
            return "POSITIF" if int(rating) >= 4 else "NEGATIF"
        except Exception:
            return "NEGATIF"

    return "NEGATIF"


def _extract_user_name(user_val):
    if isinstance(user_val, dict):
        return str(user_val.get("name") or "Anonim")
    return str(user_val or "Anonim")


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def run_pipeline_for_hotel(hotel_id):
    serpapi_key = getattr(config, "SERPAPI_KEY", None)
    if not serpapi_key:
        return {"ok": False, "hotel_id": hotel_id, "msg": "SERPAPI_KEY tidak tersedia."}

    hotel = get_hotel(hotel_id) or {}
    data_id = hotel.get("google_place_id") or hotel.get("place_id")
    if not data_id:
        return {"ok": False, "hotel_id": hotel_id, "msg": "place_id hotel belum diatur."}

    try:
        reviews = scrape_latest_review(data_id, serpapi_key)
        if not reviews:
            return {"ok": True, "hotel_id": hotel_id, "new": False, "msg": "Tidak ada review terbaru."}

        latest_review = reviews[0]
        raw_text = latest_review.get("text") or latest_review.get("snippet")
        review_text = (raw_text or "").strip() or None
        rating = _safe_int(latest_review.get("rating"), 0)
        user_name = _extract_user_name(latest_review.get("user"))
        source = latest_review.get("source", "Google Maps")
        review_time = normalize_review_time(latest_review.get("time")) or datetime.now()

        # Deduplikasi per hotel + user + text + rating + source
        if review_exists(hotel_id, user_name, review_text, rating, source):
            return {"ok": True, "hotel_id": hotel_id, "new": False, "msg": "Review sudah ada, skip."}

        # Prediksi sentimen
        if review_text:
            sentiment_nb = normalize_sentiment(MODEL.predict_nb(review_text), rating)
            sentiment_svm = normalize_sentiment(MODEL.predict_svm(review_text), rating)
        else:
            sentiment_nb = sentiment_svm = ("POSITIF" if rating >= 4 else "NEGATIF")
            review_text = f"(Tidak ada teks, hanya rating {rating})"

        # Simpan ke DB
        review_id = save_hotel_review(
            hotel_id=hotel_id,
            user_name=user_name,
            review_text=review_text,
            rating=rating,
            review_date=review_time,
            source=source,
        )

        sentiment_id = save_sentiment_review(
            review_id=review_id,
            hotel_id=hotel_id,
            user_name=user_name,
            review_text=review_text,
            rating=rating,
            review_date=review_time,
            nb=sentiment_nb,
            svm=sentiment_svm,
            source=source,
        )

        # Notifikasi subscriber hotel tersebut
        subs = get_subscribers(hotel_id)
        sent = failed = 0
        for s in subs:
            chat_id = s.get("chat_id")
            try:
                send_telegram_to_user(
                    chat_id=chat_id,
                    review_id=review_id,
                    review_text=review_text,
                    sentiment_nb=sentiment_nb,
                    sentiment_svm=sentiment_svm,
                    rating=rating,
                    user=user_name,
                )
                log_notification(review_id, chat_id, hotel_id, status="sent")
                sent += 1
            except Exception:
                log_notification(review_id, chat_id, hotel_id, status="failed")
                failed += 1

        # Simpan cache per hotel
        latest_review["sentiment_nb"] = sentiment_nb
        latest_review["sentiment_svm"] = sentiment_svm
        latest_review["hotel_id"] = hotel_id
        with open(f"latest_review_{hotel_id}.json", "w", encoding="utf-8") as f:
            json.dump(latest_review, f, ensure_ascii=False, indent=2)

        return {
            "ok": True,
            "hotel_id": hotel_id,
            "new": True,
            "review_id": review_id,
            "sentiment_id": sentiment_id,
            "sent": sent,
            "failed": failed,
        }

    except Exception as e:
        # error notification ke subscriber hotel yang sama
        try:
            for s in get_subscribers(hotel_id):
                chat_id = s.get("chat_id")
                try:
                    send_telegram_to_user(
                        chat_id=chat_id,
                        review_id=0,
                        review_text="Terjadi kesalahan dalam pipeline.",
                        sentiment_nb="ERROR",
                        sentiment_svm="ERROR",
                        rating=None,
                        user="System",
                    )
                    log_notification(None, chat_id, hotel_id, status="error")
                except Exception:
                    pass
        except Exception:
            pass

        return {"ok": False, "hotel_id": hotel_id, "msg": str(e)}


def run_pipeline(hotel_id=None):
    if hotel_id is not None:
        return [run_pipeline_for_hotel(int(hotel_id))]

    hotels = get_active_hotels() or []
    results = []
    for h in hotels:
        hid = int(h["hotel_id"])
        results.append(run_pipeline_for_hotel(hid))
    return results


if __name__ == "__main__":
    for r in run_pipeline():
        print(r)
