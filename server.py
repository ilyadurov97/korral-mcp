import os
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from key_manager import get_key_for_store

load_dotenv()

STORELINK_API_URL = os.environ["STORELINK_API_URL"]

mcp = FastMCP("korral-storelink")

POS_LOOKBACK_HOURS = 24
ALL_FIELDS = ("on_hand", "hours_left")


def _client(store_id: str) -> httpx.Client:
    key = get_key_for_store(store_id)
    if key is None:
        raise ValueError(f"no StoreLink key configured for store_id={store_id!r}")
    return httpx.Client(base_url=STORELINK_API_URL, headers={"X-Korral-Store-Key": key})


@mcp.tool()
def check_stock_status(store_id: str, sku: str, fields: list[str] | None = None) -> dict:
    """Check on-hand stock and/or projected hours of stock left for a SKU at a store.

    fields: subset of ["on_hand", "hours_left"]. Defaults to both.
    """
    requested = set(fields) if fields else set(ALL_FIELDS)
    result: dict = {"store_id": store_id, "sku": sku}

    with _client(store_id) as client:
        on_hand = None
        if requested & {"on_hand", "hours_left"}:
            resp = client.get(f"/stores/{store_id}/inventory", params={"sku": sku})
            resp.raise_for_status()
            on_hand = resp.json()["on_hand"]
            if "on_hand" in requested:
                result["on_hand"] = on_hand

        if "hours_left" in requested:
            since = (datetime.now(timezone.utc) - timedelta(hours=POS_LOOKBACK_HOURS)).isoformat()
            resp = client.get(f"/stores/{store_id}/pos", params={"sku": sku, "since": since})
            resp.raise_for_status()
            transactions = resp.json()["transactions"]
            units_sold = sum(t["quantity"] for t in transactions)
            hourly_rate = units_sold / POS_LOOKBACK_HOURS
            result["hourly_sales_rate"] = hourly_rate
            result["hours_of_stock_left"] = (on_hand / hourly_rate) if hourly_rate > 0 else None

    return result


@mcp.tool()
def raise_replenishment(store_id: str, sku: str, quantity: int) -> dict:
    """Raise a replenishment order for a SKU at a store."""
    with _client(store_id) as client:
        resp = client.post(f"/stores/{store_id}/replenishment", json={"sku": sku, "quantity": quantity})
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
def get_replenishment_status(store_id: str, order_id: str) -> dict:
    """Get the status of a previously raised replenishment order."""
    with _client(store_id) as client:
        resp = client.get(f"/stores/{store_id}/replenishment/{order_id}")
        resp.raise_for_status()
        return resp.json()


if __name__ == "__main__":
    mcp.run()
