"""Store-scoped HTTP client for the StoreLink API.

Centralizes two failure modes Korral's IT will judge us on:

1. No key configured for a store at all: fail with a readable error before
   ever touching the network.
2. A key rotates while a request is in flight: StoreLink returns 401, we
   force a fresh read of the key (bypassing the TTL cache) and retry once
   before giving up.
"""

from __future__ import annotations

import httpx

from key_manager import get_key_for_store


class StoreLinkAuthError(Exception):
    """No usable StoreLink credentials for a store — missing key, or rejected after retry."""


def _headers_for_store(store_id: str, force_reload: bool = False) -> dict:
    key = get_key_for_store(store_id, force_reload=force_reload)
    if key is None:
        raise StoreLinkAuthError(
            f"No StoreLink API key configured for store_id={store_id!r}. "
            "This server has no credentials for that store — check keys.json, "
            "or confirm the store_id with Korral IT."
        )
    return {"X-Korral-Store-Key": key}


class StoreLinkClient:
    """Store-scoped HTTP client that re-reads credentials on every request and
    retries once, with a freshly-loaded key, if StoreLink returns 401."""

    def __init__(self, store_id: str, base_url: str):
        self.store_id = store_id
        self._http = httpx.Client(base_url=base_url)

    def __enter__(self) -> "StoreLinkClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self._http.close()

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        # Fails before any network call if we have no key at all for this store.
        resp = self._http.request(method, url, headers=_headers_for_store(self.store_id), **kwargs)

        if resp.status_code == 401:
            # Key may have rotated since we read it above. Force a fresh read
            # (force_reload bypasses the key cache's TTL, otherwise the retry
            # would just reuse the same stale key) and retry once.
            resp = self._http.request(
                method, url, headers=_headers_for_store(self.store_id, force_reload=True), **kwargs
            )
            if resp.status_code == 401:
                raise StoreLinkAuthError(
                    f"StoreLink rejected our key for store_id={self.store_id!r} "
                    "even after reloading credentials and retrying once. The key "
                    "may have rotated again or been revoked — escalate to Korral IT "
                    "rather than retrying further."
                )

        resp.raise_for_status()
        return resp

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self.request("POST", url, **kwargs)
