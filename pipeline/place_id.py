# pipeline/place_id.py
import re
from urllib.parse import unquote
import requests

PLACE_ID_PATTERN = re.compile(r"(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)")

def _extract_from_text(text: str):
    if not text:
        return None

    decoded = unquote(text.strip())

    # Direct "<hex>:<hex>" format anywhere in text or URL.
    m = PLACE_ID_PATTERN.search(decoded)
    if m:
        return m.group(1)

    # Google Maps URL segment format: ...!1s<id>!...
    m = re.search(r"!1s([^!&?#]+)", decoded)
    if m:
        candidate = m.group(1).strip()
        if PLACE_ID_PATTERN.fullmatch(candidate):
            return candidate

    return None

def extract_place_id(raw_value: str, resolve_redirect: bool = False, timeout_sec: int = 8):
    """
    Extract Google Maps data/place id from:
    - raw id: 0x...:0x...
    - full URL
    - short URL (when resolve_redirect=True)
    """
    place_id = _extract_from_text(raw_value)
    if place_id:
        return place_id

    if not resolve_redirect:
        return None

    val = (raw_value or "").strip()
    if not val.lower().startswith(("http://", "https://")):
        return None
    try:
        response = requests.get(val, allow_redirects=True, timeout=timeout_sec)
        return _extract_from_text(response.url)
    except Exception:
        return None