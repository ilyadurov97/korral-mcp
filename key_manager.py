import json
import os

from dotenv import load_dotenv

load_dotenv()

KEYS_FILE = os.environ.get("STORELINK_KEYS_FILE", "keys.json")


def load_keys() -> dict[str, str]:
    with open(KEYS_FILE) as f:
        return json.load(f)


def get_key_for_store(store_id: str) -> str | None:
    return load_keys().get(store_id)


def get_store_for_key(key: str) -> str | None:
    for store_id, store_key in load_keys().items():
        if store_key == key:
            return store_id
    return None
