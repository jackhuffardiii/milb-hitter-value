"""Shared helpers: paths, cached/retrying HTTP, bounded thread pool. Used by every step."""
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
STATSAPI_CACHE = RAW / "statsapi"
MANUAL = DATA / "manual"
API = "https://statsapi.mlb.com/api/v1"
MAX_WORKERS = 8  # contract: at most 8 concurrent requests

_session = requests.Session()


def _get(url, params=None, retries=6):
    for i in range(retries):
        try:
            r = _session.get(url, params=params, timeout=120)
            if r.status_code == 200:
                return r
            if r.status_code not in (429, 500, 502, 503, 504):
                r.raise_for_status()
        except (requests.ConnectionError, requests.Timeout):
            pass
        time.sleep(2 ** i)
    raise RuntimeError(f"giving up on {url} {params}")


def api_get(path, **params):
    """GET {API}/{path} as JSON, cached on disk by (path, params)."""
    key = hashlib.sha1(json.dumps([path, sorted(params.items())], default=str).encode()).hexdigest()
    f = STATSAPI_CACHE / f"{key}.json"
    if f.exists():
        return json.loads(f.read_text())
    out = _get(f"{API}/{path}", params).json()
    STATSAPI_CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out))
    return out


def download(url, dest):
    """Download url to dest unless it already exists (cache)."""
    dest = Path(dest)
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(_get(url).content)
        tmp.rename(dest)
    return dest


def pmap(fn, items):
    """Ordered parallel map with at most MAX_WORKERS threads."""
    with ThreadPoolExecutor(MAX_WORKERS) as ex:
        return list(ex.map(fn, items))


COUNTS = ["G", "PA", "AB", "H", "2B", "3B", "HR", "BB", "IBB", "HBP", "SO", "SF", "SH",
          "SB", "CS", "GO", "AO", "pitches_faced", "swings", "whiffs"]


def add_rates(df):
    """Q4: recompute rate stats from counting stats. Zero denominators give NaN, never inf."""
    d = lambda s: s.where(s != 0)  # noqa: E731
    h = df["H"]
    tb = h + df["2B"] + 2 * df["3B"] + 3 * df["HR"]
    df["AVG"] = h / d(df["AB"])
    df["OBP"] = (h + df["BB"] + df["HBP"]) / d(df["AB"] + df["BB"] + df["HBP"] + df["SF"])
    df["SLG"] = tb / d(df["AB"])
    df["ISO"] = df["SLG"] - df["AVG"]
    df["BABIP"] = (h - df["HR"]) / d(df["AB"] - df["SO"] - df["HR"] + df["SF"])
    df["K_pct"] = df["SO"] / d(df["PA"])
    df["BB_pct"] = df["BB"] / d(df["PA"])
    return df
