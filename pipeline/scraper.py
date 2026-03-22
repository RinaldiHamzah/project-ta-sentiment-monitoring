# pipeline/scraper.py
import os
import re
import pytz
from datetime import datetime, timedelta
from deep_translator import GoogleTranslator
from serpapi import GoogleSearch

WIB = pytz.timezone("Asia/Jakarta")
TRANSLATOR = GoogleTranslator(source="auto", target="id")

def translate_to_indonesian(text: str) -> str:
    if not text:
        return None
    try:
        return TRANSLATOR.translate(text)
    except Exception as e:
        print(f"Translasi gagal: {e}")
        return text


def parse_review_time(raw_time: str):
    """Konversi waktu review Google Maps ke datetime WIB."""
    if not raw_time:
        return datetime.now(WIB)

    s = str(raw_time).strip().lower()
    now_wib = datetime.now(WIB)

    # Case: waktu relatif (misal: '12 hours ago', '2 hari lalu')
    rel_match = re.match(r"(\d+|a)\s+(\w+)", s)
    if rel_match:
        value = 1 if rel_match.group(1) == "a" else int(rel_match.group(1))
        unit = rel_match.group(2)

        if "menit" in unit or "minute" in unit:
            dt_wib = now_wib - timedelta(minutes=value)
        elif "jam" in unit or "hour" in unit:
            dt_wib = now_wib - timedelta(hours=value)
        elif "hari" in unit or "day" in unit:
            dt_wib = now_wib - timedelta(days=value)
        elif "minggu" in unit or "week" in unit:
            dt_wib = now_wib - timedelta(weeks=value)
        elif "bulan" in unit or "month" in unit:
            dt_wib = now_wib - timedelta(days=value * 30)
        elif "tahun" in unit or "year" in unit:
            dt_wib = now_wib - timedelta(days=value * 365)
        else:
            dt_wib = now_wib

        return dt_wib

    # Case: format tanggal absolut (misal: 'Sep 2, 2025', '20 Agustus 2025')
    try:
        bulan_id = {
            "januari": "January",
            "februari": "February",
            "maret": "March",
            "april": "April",
            "mei": "May",
            "juni": "June",
            "juli": "July",
            "agustus": "August",
            "september": "September",
            "oktober": "October",
            "november": "November",
            "desember": "December",
        }
        for indo, eng in bulan_id.items():
            s = s.replace(indo, eng)

        try:
            dt = datetime.strptime(s, "%b %d, %Y")
        except Exception:
            dt = datetime.strptime(s, "%d %B %Y")

        return WIB.localize(dt)
    except Exception:
        return datetime.now(WIB)


def scrape_latest_review(data_id, serpapi_key):
    params = {
        "engine": "google_maps_reviews",
        "api_key": serpapi_key,
        "data_id": data_id,
        "hl": "id",
        "gl": "id",
        "sort_by": "newestFirst",
        "no_cache": True,
        "limit": 1,
    }

    results = GoogleSearch(params).get_dict()
    if "error" in results:
        raise Exception(results["error"])

    reviews = results.get("reviews", [])
    if not reviews:
        return []

    r = reviews[0]
    raw_text = r.get("text") or r.get("snippet") or r.get("content")
    text = raw_text.strip() if isinstance(raw_text, str) else None

    return [
        {
            "text": translate_to_indonesian(text) if text else None,
            "raw_text": raw_text,
            "time": r.get("timestamp") or r.get("date") or r.get("time_ago"),
            "rating": r.get("rating", 0),
            "source": "Google Maps",
            "user": (
                r["user"]["name"]
                if isinstance(r.get("user"), dict) and "name" in r["user"]
                else str(r.get("user", "Unknown"))
            ),
        }
    ]

if __name__ == "__main__":
    # Debug manual tanpa hardcode ke kode produksi.
    serpapi_key = os.getenv("SERPAPI_KEY")
    data_id = os.getenv("GOOGLE_DATA_ID")
    if not serpapi_key or not data_id:
        print("Set env SERPAPI_KEY dan GOOGLE_DATA_ID dulu.")
    else:
        try:
            reviews = scrape_latest_review(data_id, serpapi_key)
            print(reviews[0] if reviews else "Tidak ada review ditemukan.")
        except Exception as e:
            print(f"[ERROR Scraper]: {e}")
