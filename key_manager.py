from __future__ import annotations

import json
import os
import time

from dotenv import load_dotenv

load_dotenv()

KEYS_FILE = os.environ.get("STORELINK_KEYS_FILE", "keys.json")

# Set in production only. Resource name of a Secret Manager secret version,
# e.g. "projects/123456789/secrets/storelink-keys/versions/latest". The
# secret payload is the same {store_id: key} JSON shape as keys.json.
KEYS_SECRET_NAME = os.environ.get("STORELINK_KEYS_SECRET_NAME")

# Keys rotate weekly; re-fetch periodically instead of caching for the life
# of the process so a rotation doesn't require a redeploy to pick up.
CACHE_TTL_SECONDS = int(os.environ.get("STORELINK_KEYS_CACHE_TTL", "300"))

_cache: dict[str, str] | None = None
_cache_loaded_at: float = 0.0


def _load_from_secret_manager() -> dict[str, str]:
    from google.cloud import secretmanager

    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(name=KEYS_SECRET_NAME)
    return json.loads(response.payload.data.decode("utf-8"))


def load_keys(force: bool = False) -> dict[str, str]:
    """Return the {store_id: key} map, served from a short-lived cache.

    Pass force=True to bypass the TTL and re-read the source immediately. The
    retry-on-401 path uses this: without it, a key that rotated seconds ago is
    still masked by the cache, so the retry would reuse the same stale key and
    fail again.
    """
    global _cache, _cache_loaded_at
    now = time.monotonic()
    if not force and _cache is not None and (now - _cache_loaded_at) < CACHE_TTL_SECONDS:
        return _cache

    if KEYS_SECRET_NAME:
        _cache = _load_from_secret_manager()
    else:
        with open(KEYS_FILE) as f:
            _cache = json.load(f)
    _cache_loaded_at = now
    return _cache


def get_key_for_store(store_id: str, force_reload: bool = False) -> str | None:
    return load_keys(force=force_reload).get(store_id)


def get_store_for_key(key: str) -> str | None:
    for store_id, store_key in load_keys().items():
        if store_key == key:
            return store_id
    return None
