"""Deepfire client (OGC API - Features on api.deepfire.co).

Auth: POST /v1/token with client_id / client_secret -> access_token (bearer).
Credentials come ONLY from the environment or the git-ignored repo-root `.env` file
(DEEPFIRE_CLIENT_ID / DEEPFIRE_CLIENT_SECRET). They are never logged, returned or put in errors.
"""

import math
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx

BASE_URL = "https://api.deepfire.co"
TOKEN_URL = f"{BASE_URL}/v1/token"
HOTSPOTS_URL = f"{BASE_URL}/ogc/features/v1/collections/deepfire:hotspots/items"
TIMEOUT_SECONDS = 20.0
QUERY_LIMIT = 200  # max hotspots requested per query (the API returns them in a bbox)

_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"  # repo root, git-ignored
_token_cache: dict = {"token": None, "expires_at": 0.0}


class DeepfireUnavailable(Exception):
    """Deepfire could not be queried. The message never contains credentials or tokens."""


@dataclass(frozen=True)
class Hotspot:
    id: str
    lat: float
    lon: float
    observed_at: datetime  # timezone-aware UTC
    confidence: str
    source: str


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p = math.pi / 180
    a = math.sin((lat2 - lat1) * p / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2
    return 12742.0 * math.asin(math.sqrt(a))


def _credentials() -> tuple[str, str]:
    values = {k: os.environ.get(k) for k in ("DEEPFIRE_CLIENT_ID", "DEEPFIRE_CLIENT_SECRET")}
    if not all(values.values()) and _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            key, sep, val = line.partition("=")
            if sep and key.strip() in values and not values[key.strip()]:
                values[key.strip()] = val.strip()
    if not all(values.values()):
        raise DeepfireUnavailable("credentials not configured")
    return values["DEEPFIRE_CLIENT_ID"], values["DEEPFIRE_CLIENT_SECRET"]  # type: ignore[return-value]


def _access_token() -> str:
    if _token_cache["token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["token"]
    client_id, client_secret = _credentials()
    try:
        resp = httpx.post(
            TOKEN_URL, json={"client_id": client_id, "client_secret": client_secret}, timeout=TIMEOUT_SECONDS
        )
        resp.raise_for_status()
        body = resp.json()
        token = body["access_token"]
        expires_in = int(body.get("expires_in", 300))
    except httpx.HTTPStatusError as exc:
        raise DeepfireUnavailable(f"authentication failed (HTTP {exc.response.status_code})") from None
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise DeepfireUnavailable(f"authentication error ({type(exc).__name__})") from None
    _token_cache.update(token=token, expires_at=time.time() + max(expires_in - 60, 0))
    return token


def fetch_active_hotspots(lat: float, lon: float, radius_km: float) -> tuple[list[Hotspot], bool]:
    """Active hotspots in the bbox around (lat, lon). Returns (hotspots, truncated).

    `truncated` is True when the API returned QUERY_LIMIT features (there may be more).
    """
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.01))
    bbox = f"{lon - dlon:.4f},{lat - dlat:.4f},{lon + dlon:.4f},{lat + dlat:.4f}"
    token = _access_token()
    try:
        resp = httpx.get(
            HOTSPOTS_URL,
            params={
                "f": "application/json", "bbox": bbox, "limit": QUERY_LIMIT,
                "filter": "active = true", "filter-lang": "cql-text",
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        features = resp.json()["features"]
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403):
            _token_cache.update(token=None, expires_at=0.0)
        raise DeepfireUnavailable(f"hotspots query failed (HTTP {exc.response.status_code})") from None
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise DeepfireUnavailable(f"hotspots query error ({type(exc).__name__})") from None

    hotspots: list[Hotspot] = []
    for f in features:
        try:
            props, (h_lon, h_lat) = f["properties"], f["geometry"]["coordinates"][:2]
            observed = datetime.fromisoformat(props["observed_at"].replace("Z", "+00:00"))
            hotspots.append(
                Hotspot(
                    id=str(props.get("id") or f.get("id")), lat=float(h_lat), lon=float(h_lon),
                    observed_at=observed, confidence=str(props.get("confidence", "UNKNOWN")),
                    source=str(props.get("source", "UNKNOWN")),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue  # skip a malformed feature rather than guessing its meaning
    return hotspots, len(features) >= QUERY_LIMIT
