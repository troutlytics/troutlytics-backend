# web_scraper/scraper.py
# Python 3.10+

import os
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, date
from time import time
from typing import Optional, List, Dict, Tuple
from urllib.parse import quote_plus
import re

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter, Retry
from dotenv import load_dotenv

# project imports
from data.database import DataBase
from data.models import WaterLocation  # used for preloading the cache

# ---------------- Logging ----------------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(message)s",
)

# ---------------- Model ------------------
@dataclass
class RowRecord:
    original_html_name: Optional[str] = None
    water_name_cleaned: Optional[str] = None
    county: Optional[str] = None
    region: Optional[str] = None
    date: Optional[date] = None
    species: Optional[str] = None
    stocked_fish: Optional[int] = None
    # DB column is "weight"; WDFW column is "Fish per pound"
    weight: Optional[float] = None          # mapped from fish_per_lb
    fish_per_lb: Optional[float] = None
    approx_weight_lb: Optional[float] = None
    hatchery: Optional[str] = None
    notes: Optional[str] = None

    latitude: Optional[float] = None
    longitude: Optional[float] = None
    directions: Optional[str] = None
    derby_participant: bool = False

# ---------- Legacy cleaning (matches your original) ----------
ABBREVIATIONS = {
    "LK": "Lake", "PD": "Pond", "CR": "Creek", "PRK": "Park", "CO": "County",
    "ADLT": "Adult", "JV": "Juvenile"
}

_ABBR_REGEX = re.compile(
    r"\(.*?\)|[^\w\s\d]|(?<!\w)(\d+)(?!\w)|\b(" + "|".join(ABBREVIATIONS.keys()) + r")\b"
)

def legacy_clean_water_name(cell_text: str) -> str:
    raw = (cell_text or "").strip() + " County"

    def _repl(m: re.Match) -> str:
        if m.group(1):  # standalone numbers
            return ""
        if m.group(2):  # ABBR key
            return ABBREVIATIONS.get(m.group(2), "")
        return ""  # parens/punct -> drop

    s = _ABBR_REGEX.sub(_repl, raw)
    s = s.strip().replace("\n", "").replace(" Region ", "").replace("  ", " ")
    s = s.title()
    return s

# ---------- Normalization for matching ----------
_whitespace = re.compile(r"\s+")
_nonword = re.compile(r"[^\w]+")

def norm_key_exact(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    return s.strip()

def norm_key_relaxed(s: Optional[str]) -> Optional[str]:
    """Collapse whitespace & casefold; keep letters/digits/spaces."""
    if not s:
        return None
    s2 = _whitespace.sub(" ", s).strip().casefold()
    return s2

def norm_key_alnum(s: Optional[str]) -> Optional[str]:
    """Only letters/digits for last-resort match."""
    if not s:
        return None
    s2 = _nonword.sub("", s).casefold()
    return s2

def parse_int(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    try:
        return int(text.replace(",", "").strip())
    except Exception:
        logging.debug("parse_int failed for %r", text)
        return None

def parse_float(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    try:
        return float(text.replace(",", "").strip())
    except Exception:
        logging.debug("parse_float failed for %r", text)
        return None

def parse_date_str(text: Optional[str]) -> Optional[date]:
    if not text:
        return None
    s = text.strip()
    for fmt in ("%b %d, %Y", "%b %e, %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    logging.warning("Unrecognized date: %r", text)
    return None

def build_maps_url(cleaned: Optional[str]) -> Optional[str]:
    if not cleaned:
        return None
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(cleaned + ' Washington State')}"

# --------------- Scraper -----------------
class Scraper:
    DEFAULT_URL = (
        "https://wdfw.wa.gov/fishing/reports/stocking/trout-plants/all"
        "?lake_stocked=&county=&species=&hatchery=&region=&items_per_page=250"
    )

    def __init__(self, db: Optional[DataBase] = None):
        self.db = db
        self.session = self._session()
        # behavior flags
        self.allow_create_wl = os.getenv("SCRAPER_ALLOW_CREATE_WATER_LOCATION", "false").lower() in ("1", "true", "yes")
        self.do_geocode = os.getenv("SCRAPER_GEOCODE", "false").lower() in ("1", "true", "yes")

        # preload existing WaterLocation rows into multiple lookup maps
        self._existing_maps_built = False
        self.by_original_exact: Dict[str, WaterLocation] = {}
        self.by_original_relaxed: Dict[str, WaterLocation] = {}
        self.by_original_alnum: Dict[str, WaterLocation] = {}
        self.by_clean_relaxed: Dict[str, WaterLocation] = {}
        self.by_clean_alnum: Dict[str, WaterLocation] = {}

    @staticmethod
    def _session() -> requests.Session:
        s = requests.Session()
        s.headers["User-Agent"] = "TroutlyticsScraper/1.0 (+contact: troutlytics)"
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        s.mount("https://", HTTPAdapter(max_retries=retries))
        s.mount("http://", HTTPAdapter(max_retries=retries))
        return s

    def _build_existing_maps(self):
        if self._existing_maps_built or not self.db:
            return
        logging.info("Preloading existing WaterLocation index...")
        q = self.db.session.query(WaterLocation).all()
        for wl in q:
            o = wl.original_html_name or ""
            c = wl.water_name_cleaned or ""

            k1 = norm_key_exact(o)
            k2 = norm_key_relaxed(o)
            k3 = norm_key_alnum(o)
            k4 = norm_key_relaxed(c)
            k5 = norm_key_alnum(c)

            if k1: self.by_original_exact.setdefault(k1, wl)
            if k2: self.by_original_relaxed.setdefault(k2, wl)
            if k3: self.by_original_alnum.setdefault(k3, wl)
            if k4: self.by_clean_relaxed.setdefault(k4, wl)
            if k5: self.by_clean_alnum.setdefault(k5, wl)

        self._existing_maps_built = True
        logging.info("Indexed %d WaterLocation rows", len(q))

    def _find_existing_wl(self, original_html_name: Optional[str], cleaned: Optional[str]) -> Optional[WaterLocation]:
        """Try multiple keys to hit existing WaterLocation and avoid duplicates."""
        if not self._existing_maps_built:
            self._build_existing_maps()

        for key, mapping in (
            (norm_key_exact(original_html_name), self.by_original_exact),
            (norm_key_relaxed(original_html_name), self.by_original_relaxed),
            (norm_key_alnum(original_html_name), self.by_original_alnum),
            (norm_key_relaxed(cleaned), self.by_clean_relaxed),
            (norm_key_alnum(cleaned), self.by_clean_alnum),
        ):
            if key and key in mapping:
                return mapping[key]
        return None

    def fetch(self, url: str) -> BeautifulSoup:
        logging.info("Fetching %s", url)
        r = self.session.get(url, timeout=20)
        r.raise_for_status()
        return BeautifulSoup(r.content, "html.parser")

    def _parse_row(self, tr: Tag) -> Optional[RowRecord]:
        def txt(sel: str) -> Optional[str]:
            el = tr.select_one(sel)
            return (el.get_text(strip=True) if el else None) or None

        lake_td = tr.select_one(".views-field-lake-stocked")
        if not lake_td:
            return None

        first_a = lake_td.find("a")
        original = first_a.get_text(strip=True) if first_a else lake_td.get_text(strip=True)

        anchors = lake_td.find_all("a")
        county = anchors[1].get_text(strip=True) if len(anchors) >= 2 else None
        region = None
        if len(anchors) >= 3:
            reg_text = anchors[2].get_text(strip=True)  # "Region 4"
            m = re.search(r"(\d+)$", reg_text)
            region = m.group(1) if m else reg_text

        lake_cell_text_raw = lake_td.get_text()  # raw (with newlines) for legacy behavior
        cleaned = legacy_clean_water_name(lake_cell_text_raw)

        date_str   = txt(".views-field-stock-date")
        # inside your row parse
        species_raw  = txt(".views-field-species")
        species      = species_raw.title().strip() if species_raw else None
        num_str    = txt(".views-field-num-fish")
        fpl_str    = txt(".views-field-fish-per-lb")
        hatchery_raw = txt(".views-field-hatchery")
        hatchery = hatchery_raw.title() if hatchery_raw else None
        notes      = txt(".views-field-other-notes")

        stocked = parse_int(num_str)
        fpl     = parse_float(fpl_str)
        approx  = (1.0 / fpl) if (fpl and fpl > 0) else None

        return RowRecord(
            original_html_name = original,
            water_name_cleaned = cleaned,
            county = county,
            region = region,
            date = parse_date_str(date_str),
            species = species,
            stocked_fish = stocked,
            weight = fpl,                 # DB "weight" = fish-per-lb
            fish_per_lb = fpl,
            approx_weight_lb = approx,
            hatchery = hatchery,
            notes = notes,
            directions = build_maps_url(cleaned),
        )

    def _geocode_one(self, query: str) -> Tuple[Optional[float], Optional[float]]:
        from geopy import GoogleV3
        api_key = os.getenv("GV3_API_KEY")
        if not api_key:
            return (None, None)
        locator = GoogleV3(api_key=api_key)
        try:
            place = locator.geocode(query, timeout=10)
            if place and place.point:
                return (float(place.point[0]), float(place.point[1]))
        except Exception as e:
            logging.warning("Geocode error for %s: %s", query, e)
        return (None, None)

    def scrape(self, url: Optional[str] = None) -> List[RowRecord]:
        soup = self.fetch(url or self.DEFAULT_URL)
        trs = soup.select("table.cols-7 tbody tr")
        out: List[RowRecord] = []
        for tr in trs:
            rec = self._parse_row(tr)
            if rec:
                out.append(rec)
        logging.info("Parsed %d rows", len(out))
        return out

# ------------- Main ----------------
def main():
    load_dotenv()
    run_started_at = datetime.now().astimezone()
    start = time()
    db = DataBase()
    scraper = Scraper(db=db)

    rows = scraper.scrape()

    # Attach existing WaterLocation when possible; control creation via env
    payload: List[Dict] = []
    created_blocked = 0
    matched_existing = 0
    created_new = 0

    for r in rows:
        existing = scraper._find_existing_wl(r.original_html_name, r.water_name_cleaned)

        if existing:
            matched_existing += 1
            r.latitude = float(existing.latitude) if existing.latitude is not None else None
            r.longitude = float(existing.longitude) if existing.longitude is not None else None
            r.directions = existing.directions or r.directions
        else:
            if scraper.allow_create_wl:
                if scraper.do_geocode:
                    q = r.directions.split("query=", 1)[-1] if r.directions else quote_plus((r.water_name_cleaned or "") + " Washington State")
                    lat, lon = scraper._geocode_one(q)
                    r.latitude, r.longitude = lat, lon
                created_new += 1
            else:
                created_blocked += 1
                continue  # skip to avoid creating phantom WLs

        d = asdict(r)
        payload.append({
            "original_html_name": d["original_html_name"],
            "water_name_cleaned": d["water_name_cleaned"],
            "stocked_fish": d["stocked_fish"],
            "date": d["date"],
            "species": d["species"],
            "weight": d["weight"],            # fish-per-lb
            "hatchery": d["hatchery"],
            "latitude": d["latitude"],
            "longitude": d["longitude"],
            "directions": d["directions"],
            "derby_participant": d["derby_participant"],
        })

    logging.info("Matched existing WL: %d | New WL allowed: %d | New WL blocked: %d",
                 matched_existing, created_new, created_blocked)

    scraper_version = (
        os.getenv("SCRAPER_VERSION")
        or os.getenv("GITHUB_SHA")
        or os.getenv("IMAGE_TAG")
        or os.getenv("GIT_SHA")
    )
    db.write_data(
        payload,
        utility_meta={
            "run_started_at": run_started_at,
            "rows_scraped": len(rows),
            "rows_payload": len(payload),
            "water_locations_matched": matched_existing,
            "water_locations_created": created_new,
            "water_locations_blocked": created_blocked,
            "source_url": scraper.DEFAULT_URL,
            "scraper_version": scraper_version,
            "status": "success",
        },
    )
    logging.info("Done in %.2fs", time() - start)

if __name__ == "__main__":
    main()
