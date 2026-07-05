import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from observability import log_decision, log_tool_call
from storelink_client import StoreLinkClient

load_dotenv()

STORELINK_API_URL = os.environ["STORELINK_API_URL"]

mcp = FastMCP("korral-storelink")

POS_LOOKBACK_HOURS = 24
ALL_FIELDS = ("on_hand", "hours_left")


def _client(store_id: str) -> StoreLinkClient:
    return StoreLinkClient(store_id, STORELINK_API_URL)


@mcp.tool()
@log_tool_call
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
            on_hand = resp.json()["on_hand"]
            if "on_hand" in requested:
                result["on_hand"] = on_hand

        if "hours_left" in requested:
            since = (datetime.now(timezone.utc) - timedelta(hours=POS_LOOKBACK_HOURS)).isoformat()
            resp = client.get(f"/stores/{store_id}/pos", params={"sku": sku, "since": since})
            transactions = resp.json()["transactions"]
            units_sold = sum(t["quantity"] for t in transactions)
            hourly_rate = units_sold / POS_LOOKBACK_HOURS
            result["hourly_sales_rate"] = hourly_rate
            result["hours_of_stock_left"] = (on_hand / hourly_rate) if hourly_rate > 0 else None

    if "hours_of_stock_left" in result:
        if result["hours_of_stock_left"] is None:
            log_decision(
                f"Checked SKU {sku} at store {store_id}: {on_hand} units on hand, "
                f"no sales in the last {POS_LOOKBACK_HOURS}h so depletion time can't be estimated."
            )
        else:
            log_decision(
                f"Checked SKU {sku} at store {store_id}: {on_hand} units on hand, "
                f"selling ~{result['hourly_sales_rate']:.1f} units/hr over the last {POS_LOOKBACK_HOURS}h "
                f"=> about {result['hours_of_stock_left']:.1f} hours of stock left."
            )
    else:
        log_decision(f"Checked on-hand stock for SKU {sku} at store {store_id}: {on_hand} units.")

    return result


@mcp.tool()
@log_tool_call
def raise_replenishment(store_id: str, sku: str, quantity: int) -> dict:
    """Raise a replenishment order for a SKU at a store."""
    with _client(store_id) as client:
        resp = client.post(f"/stores/{store_id}/replenishment", json={"sku": sku, "quantity": quantity})
        order = resp.json()

    log_decision(
        f"Raised replenishment for {quantity} units of SKU {sku} at store {store_id} "
        f"(order {order.get('order_id', '?')})."
    )
    return order


@mcp.tool()
@log_tool_call
def get_replenishment_status(store_id: str, order_id: str) -> dict:
    """Get the status of a previously raised replenishment order."""
    with _client(store_id) as client:
        resp = client.get(f"/stores/{store_id}/replenishment/{order_id}")
        status = resp.json()

    log_decision(
        f"Checked replenishment order {order_id} at store {store_id}: status is "
        f"{status.get('status', 'unknown')}."
    )
    return status


if __name__ == "__main__":
    mcp.run()
