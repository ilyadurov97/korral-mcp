"""Tests for the two credential-failure modes StoreLinkClient must handle:

1. No key configured for a store -> readable error, no network call.
2. Key rotates mid-flight (401) -> reload key, retry once, then either
   succeed or fail with a readable error.

Uses only the standard library plus httpx's built-in MockTransport, so it
runs with no extra dependencies beyond what's already in requirements.txt.
"""

import json
import tempfile
import unittest
from unittest.mock import patch

import httpx

import key_manager
from storelink_client import StoreLinkAuthError, StoreLinkClient


class NoCredentialsTest(unittest.TestCase):
    def test_missing_key_fails_before_touching_network(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("network was hit despite having no key for this store")

        transport = httpx.MockTransport(handler)

        with patch("storelink_client.get_key_for_store", return_value=None) as mock_get_key:
            client = StoreLinkClient("unknown_store", "https://storelink.test")
            client._http = httpx.Client(base_url="https://storelink.test", transport=transport)

            with self.assertRaises(StoreLinkAuthError) as ctx:
                client.get("/stores/unknown_store/inventory", params={"sku": "sku_milk_1l"})

        self.assertIn("unknown_store", str(ctx.exception))
        mock_get_key.assert_called_with("unknown_store", force_reload=False)


class KeyRotationTest(unittest.TestCase):
    def test_401_triggers_reload_and_retry_then_succeeds(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if request.headers["X-Korral-Store-Key"] != "new_key":
                return httpx.Response(401, json={"detail": "invalid or mismatched key"})
            return httpx.Response(200, json={"on_hand": 42})

        transport = httpx.MockTransport(handler)

        with patch("storelink_client.get_key_for_store", side_effect=["stale_key", "new_key"]):
            client = StoreLinkClient("store_001", "https://storelink.test")
            client._http = httpx.Client(base_url="https://storelink.test", transport=transport)

            resp = client.get("/stores/store_001/inventory", params={"sku": "sku_milk_1l"})

        self.assertEqual(resp.json(), {"on_hand": 42})
        self.assertEqual(calls["n"], 2)

    def test_401_persists_after_retry_raises_readable_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"detail": "invalid or mismatched key"})

        transport = httpx.MockTransport(handler)

        with patch("storelink_client.get_key_for_store", side_effect=["stale_key", "still_stale"]):
            client = StoreLinkClient("store_001", "https://storelink.test")
            client._http = httpx.Client(base_url="https://storelink.test", transport=transport)

            with self.assertRaises(StoreLinkAuthError) as ctx:
                client.get("/stores/store_001/inventory", params={"sku": "sku_milk_1l"})

        self.assertIn("store_001", str(ctx.exception))
        self.assertIn("escalate", str(ctx.exception).lower())


class KeyCacheBustTest(unittest.TestCase):
    """Regression: a 401 retry must bypass the key cache's TTL. Otherwise a key
    that rotated seconds ago is still masked by the cache and the retry just
    reuses the stale key — defeating the whole point of the retry.

    This test drives the real key_manager cache (not a patched get_key_for_store)
    so it would catch that regression.
    """

    def setUp(self):
        self._orig_cache = key_manager._cache
        self._orig_loaded_at = key_manager._cache_loaded_at
        self._orig_file = key_manager.KEYS_FILE
        self._orig_secret = key_manager.KEYS_SECRET_NAME
        key_manager.KEYS_SECRET_NAME = None  # force the file path, not Secret Manager

    def tearDown(self):
        key_manager._cache = self._orig_cache
        key_manager._cache_loaded_at = self._orig_loaded_at
        key_manager.KEYS_FILE = self._orig_file
        key_manager.KEYS_SECRET_NAME = self._orig_secret

    def test_force_reload_bypasses_fresh_ttl_cache(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"store_001": "stale_key"}, f)
            f.flush()
            key_manager.KEYS_FILE = f.name

            # Prime a *fresh* cache (well inside the TTL) with the stale key.
            key_manager._cache = None
            key_manager._cache_loaded_at = 0.0
            self.assertEqual(key_manager.get_key_for_store("store_001"), "stale_key")

            # Rotate the key at the source.
            with open(f.name, "w") as f2:
                json.dump({"store_001": "new_key"}, f2)

            # A normal read is still served from the fresh cache...
            self.assertEqual(key_manager.get_key_for_store("store_001"), "stale_key")
            # ...but a forced reload (the 401 retry path) sees the rotated key.
            self.assertEqual(
                key_manager.get_key_for_store("store_001", force_reload=True), "new_key"
            )


if __name__ == "__main__":
    unittest.main()
