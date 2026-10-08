import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone, date
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://in.bookmyshow.com"
ADAPTER_VERSION = "0.4.0"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36",
    "Accept-Language": "en-IN,en;q=0.9",
}

class BMSAdapterError(RuntimeError):
    pass

@dataclass
class SourceState:
    ok: bool = False
    last_success: float | None = None
    last_error: str | None = None
    adapter_version: str = ADAPTER_VERSION

state = SourceState()
_cache = {}

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

def _get(url: str, ttl: int = 15) -> str:
    now = time.time()
    hit = _cache.get(url)
    if hit and now - hit[0] < ttl:
        return hit[1]

    try:
        r = requests.get(url, headers=HEADERS, timeout=18)
        r.raise_for_status()
        body = r.text
        low = body.lower()
        if ("captcha" in low or "access denied" in low) and len(body) < 250000:
            raise BMSAdapterError("BMS challenge/access page detected")
        _cache[url] = (now, body)
        state.ok = True
        state.last_success = now
        state.last_error = None
        return body
    except Exception as e:
        state.ok = False
        state.last_error = str(e)
        raise BMSAdapterError(str(e))

def _parse_time(s: str) -> bool:
    return bool(re.fullmatch(r"(?:0?[1-9]|1[0-2]):[0-5]\d\s*(?:AM|PM)", s.strip(), re.I))

def movies(city: str = "chennai"):
    url = f"{BASE}/explore/movies-{city}?cat=MT"
    soup = BeautifulSoup(_get(url, ttl=30), "html.parser")
    out, seen = [], set()

    for a in soup.select('a[href*="/movies/"]'):
        href = urljoin(BASE, a.get("href", ""))
        txt = _clean(a.get_text(" ", strip=True))
        if not txt or len(txt) < 2:
            continue
        if txt.lower() in {"movies", "movie tickets", "see all"}:
            continue
        # BMS movie anchors can contain title + certification/language.
        # Prefer a readable title, falling back to visible anchor text.
        key = txt.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"id": _slug(txt), "title": txt, "url": href})
    return out

def _extract_booking_urls(html: str, city: str) -> list[str]:
    # Public BMS pages embed booking links in HTML/JSON even when the rendered
    # text view does not expose them as ordinary anchors.
    patterns = [
        rf'https://in\.bookmyshow\.com/cinemas/{re.escape(city)}/[^"\'<>\\ ]+/buytickets/[A-Za-z0-9]+/\d{{8}}',
        rf'/cinemas/{re.escape(city)}/[^"\'<>\\ ]+/buytickets/[A-Za-z0-9]+/\d{{8}}',
    ]
    found = []
    for pat in patterns:
        found.extend(re.findall(pat, html, re.I))
    out = []
    for u in found:
        u = urljoin(BASE, u)
        if u not in out:
            out.append(u)
    return out

def _name_from_booking_slug(slug: str) -> str:
    return _clean(re.sub(r'[-_]+', ' ', slug)).title()

def cinemas(city: str = "chennai"):
    url = f"{BASE}/{city}/cinemas"
    html = _get(url, ttl=60)
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()

    # First prefer visible cinema names. Then recover their direct booking URL
    # from embedded HTML when the listing page doesn't render it as an anchor.
    visible_names = []
    for a in soup.select('a[href*="/cinemas/"]'):
        txt = _clean(a.get_text(" ", strip=True))
        if txt and len(txt) >= 3 and txt.lower() not in {"cinemas", "see all"}:
            visible_names.append(txt)

    booking_urls = _extract_booking_urls(html, city)
    used_urls = set()
    for name in visible_names:
        key = name.lower()
        if key in seen:
            continue
        match = next((u for u in booking_urls if _slug(name) in u.lower()), None)
        seen.add(key)
        if match:
            used_urls.add(match)
        out.append({"id": _slug(name), "name": name, "url": match, "showtimes_url": match})

    # Add booking URLs not matched to visible names. This keeps monitoring
    # functional even when BMS changes the listing DOM.
    for u in booking_urls:
        if u in used_urls:
            continue
        m = re.search(rf'/cinemas/{re.escape(city)}/([^/]+)/buytickets/[^/]+/\d{{8}}', u, re.I)
        if not m:
            continue
        name = _name_from_booking_slug(m.group(1))
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"id": _slug(name), "name": name, "url": u, "showtimes_url": u})

    return out

def _resolve_showtimes_url(cinema: dict, city: str) -> str | None:
    if cinema.get("showtimes_url"):
        return cinema["showtimes_url"]

    page = cinema.get("url")
    if not page:
        return None

    soup = BeautifulSoup(_get(page, ttl=60), "html.parser")
    candidates = []
    for a in soup.select('a[href*="/buytickets/"]'):
        href = urljoin(BASE, a.get("href", ""))
        if "/cinemas/" in href and "/buytickets/" in href:
            candidates.append(href)
    if not candidates:
        # Some BMS pages expose the booking URL in scripts/JSON.
        html = str(soup)
        m = re.search(r'https://in\.bookmyshow\.com/cinemas/[^"\']+/buytickets/[^"\']+', html)
        if m:
            candidates.append(m.group(0))
    return candidates[0] if candidates else None

def _date_url(url: str, date_str: str | None) -> str:
    if not date_str:
        return url
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y%m%d")
        return re.sub(r'/\d{8}(?:$|\?)', f'/{d}', url)
    except ValueError:
        return url

def showtimes_for_cinema(cinema: dict, city: str = "chennai", date_str: str | None = None):
    url = _resolve_showtimes_url(cinema, city)
    if not url:
        raise BMSAdapterError(f"Could not resolve a BMS showtime page for {cinema.get('name')}")
    url = _date_url(url, date_str)
    soup = BeautifulSoup(_get(url, ttl=8), "html.parser")
    text = _clean(soup.get_text(" ", strip=True))
    tokens = [_clean(x) for x in soup.stripped_strings if _clean(x)]

    time_re = re.compile(r"^(?:0?[1-9]|1[0-2]):[0-5]\d\s*(?:AM|PM)$", re.I)
    status_words = {"AVAILABLE", "FAST FILLING", "ALMOST FULL", "FILLING FAST", "SOLD OUT", "HOUSEFULL"}
    movie_re = re.compile(r"\((?:U|UA|A)\d{0,2}\+?\)$", re.I)
    format_re = re.compile(r"^(?:2D|3D|IMAX|4DX|MX4D|4K/ATMOS|RGB ATMOS|4K RGB|2K/DOLBY 7\.1)$", re.I)
    lang_format_re = re.compile(r"^([A-Za-z][A-Za-z ,+.-]*),\s*(2D|3D|IMAX|4DX|MX4D)$", re.I)

    shows = []
    current_movie = None
    current_language = None
    current_format = None
    current_status = "UNKNOWN"
    page_status = "AVAILABLE" if "AVAILABLE" in text.upper() else "UNKNOWN"

    for token in tokens:
        upper = token.upper()
        if upper in status_words:
            current_status = upper
            continue
        if time_re.fullmatch(token):
            shows.append({
                "movie": current_movie,
                "language": current_language,
                "format": current_format,
                "time": token.upper(),
                "status": current_status if current_status != "UNKNOWN" else page_status,
                "booking_url": url,
            })
            current_status = page_status
            continue
        if movie_re.search(token) and len(token) <= 120:
            current_movie = token
            current_language = None
            current_format = None
            current_status = page_status
            continue
        m = lang_format_re.fullmatch(token)
        if m:
            current_language = m.group(1).strip()
            current_format = m.group(2).upper()
            continue
        if format_re.fullmatch(token):
            current_format = token.upper()

    if not shows:
        # Flattened-page fallback: retain observable times rather than returning
        # an empty result when BMS changes its DOM hierarchy.
        for t in dict.fromkeys(re.findall(r"\b(?:0?[1-9]|1[0-2]):[0-5]\d\s*(?:AM|PM)\b", text, re.I)):
            shows.append({"movie": None, "language": None, "format": None, "time": t.upper(), "status": page_status, "booking_url": url})

    return {"cinema": cinema.get("name"), "source_url": url, "shows": shows}

def check_alert(movie: str, cinema_names: list[str], city: str = "chennai", date_str: str | None = None, available_only: bool = False):
    all_cinemas = cinemas(city)
    lookup = {c["name"].lower(): c for c in all_cinemas}
    results = []

    for requested in cinema_names[:3]:
        c = lookup.get(requested.lower())
        if not c:
            # fuzzy fallback
            c = next((x for x in all_cinemas if requested.lower() in x["name"].lower()), None)
        if not c:
            results.append({"cinema": requested, "error": "Cinema not found on BMS"})
            continue

        try:
            data = showtimes_for_cinema(c, city, date_str)
            wanted = movie.strip().lower()
            matches = []
            for s in data["shows"]:
                observed = (s.get("movie") or "").lower()
                # Never alert on a show whose movie could not be identified.
                # A flattened BMS page can expose times without preserving the
                # movie/time relationship; treating those as a match creates
                # false positives.
                if not observed:
                    continue
                if wanted and wanted not in observed and observed not in wanted:
                    continue
                if available_only and s.get("status") not in {"AVAILABLE", "FAST FILLING", "ALMOST FULL", "FILLING FAST"}:
                    continue
                matches.append(s)
            results.append({"cinema": c["name"], "source_url": data["source_url"], "matches": matches})
        except Exception as e:
            results.append({"cinema": c["name"], "error": str(e)})

    return results
