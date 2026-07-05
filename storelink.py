import uuid
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from key_manager import get_store_for_key

app = FastAPI(title="StoreLink API (mock)")

NOW = datetime.now(timezone.utc)

STORES = {"store_001", "store_002", "47", "102"}

SKUS = {
    "sku_milk_1l": {"name": "Whole Milk 1L", "category": "dairy", "supplier_id": "sup_dairy"},
    "sku_beans_400g": {"name": "Canned Beans 400g", "category": "grocery", "supplier_id": "sup_canned"},
    "8847291": {"name": "Madeta Butter 250g", "category": "dairy", "supplier_id": "sup_dairy"},
}

SUPPLIERS = {
    "sup_dairy": {"name": "Nordic Dairy Co-op", "lead_time_hours": 24},
    "sup_canned": {"name": "Continental Canned Goods", "lead_time_hours": 72},
}

INVENTORY = {
    ("store_001", "sku_milk_1l"): 20,
    ("store_001", "sku_beans_400g"): 150,
    ("store_002", "sku_milk_1l"): 8,
    ("store_002", "sku_beans_400g"): 200,
    # gap (24h sold - on_hand) = 18 - 15 = 3, under the 6-unit reorder threshold
    ("47", "8847291"): 15,
    # gap (24h sold - on_hand) = 20 - 2 = 18, over the 6-unit reorder threshold
    ("102", "8847291"): 2,
}

# Fast-moving milk: steady sales over the last 24h. Slow-moving beans: nothing recent.
POS_TRANSACTIONS = {
    ("store_001", "sku_milk_1l"): [
        {"timestamp": NOW - timedelta(hours=h), "quantity": 2}
        for h in range(0, 24, 1)
    ],
    ("store_001", "sku_beans_400g"): [],
    ("store_002", "sku_milk_1l"): [
        {"timestamp": NOW - timedelta(hours=h), "quantity": 1}
        for h in range(0, 24, 2)
    ],
    ("store_002", "sku_beans_400g"): [],
    ("47", "8847291"): [
        {"timestamp": NOW - timedelta(hours=h), "quantity": 1}
        for h in range(0, 18, 1)
    ],
    ("102", "8847291"): [
        {"timestamp": NOW - timedelta(hours=h), "quantity": 1}
        for h in range(0, 20, 1)
    ],
}

REPLENISHMENT_ORDERS: dict[str, dict] = {}


def require_store_key(store_id: str, x_korral_store_key: str | None) -> None:
    if store_id not in STORES:
        raise HTTPException(status_code=404, detail="unknown store_id")
    if not x_korral_store_key or get_store_for_key(x_korral_store_key) != store_id:
        raise HTTPException(status_code=401, detail="invalid or mismatched X-Korral-Store-Key")


@app.get("/v1/stores/{store_id}/inventory")
def get_inventory(store_id: str, sku: str, x_korral_store_key: str | None = Header(default=None)):
    require_store_key(store_id, x_korral_store_key)
    on_hand = INVENTORY.get((store_id, sku))
    if on_hand is None:
        raise HTTPException(status_code=404, detail="no inventory record for this store/sku")
    return {"store_id": store_id, "sku": sku, "on_hand": on_hand}


@app.get("/v1/stores/{store_id}/pos")
def get_pos(store_id: str, sku: str, since: str, x_korral_store_key: str | None = Header(default=None)):
    require_store_key(store_id, x_korral_store_key)
    since_dt = datetime.fromisoformat(since)
    transactions = [
        {"timestamp": t["timestamp"].isoformat(), "quantity": t["quantity"]}
        for t in POS_TRANSACTIONS.get((store_id, sku), [])
        if t["timestamp"] >= since_dt
    ]
    return {"store_id": store_id, "sku": sku, "since": since, "transactions": transactions}


class ReplenishmentRequest(BaseModel):
    sku: str
    quantity: int


@app.post("/v1/stores/{store_id}/replenishment")
def raise_replenishment(store_id: str, body: ReplenishmentRequest, x_korral_store_key: str | None = Header(default=None)):
    require_store_key(store_id, x_korral_store_key)
    order_id = f"ord_{uuid.uuid4().hex[:10]}"
    REPLENISHMENT_ORDERS[order_id] = {
        "order_id": order_id,
        "store_id": store_id,
        "sku": body.sku,
        "quantity": body.quantity,
        "status": "raised",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return REPLENISHMENT_ORDERS[order_id]


@app.get("/v1/stores/{store_id}/replenishment/{order_id}")
def get_replenishment_status(store_id: str, order_id: str, x_korral_store_key: str | None = Header(default=None)):
    require_store_key(store_id, x_korral_store_key)
    order = REPLENISHMENT_ORDERS.get(order_id)
    if not order or order["store_id"] != store_id:
        raise HTTPException(status_code=404, detail="unknown order_id for this store")
    return order


@app.get("/v1/skus/{sku}")
def get_sku(sku: str):
    details = SKUS.get(sku)
    if not details:
        raise HTTPException(status_code=404, detail="unknown sku")
    return {"sku": sku, **details}


@app.get("/v1/suppliers/{supplier_id}")
def get_supplier(supplier_id: str):
    details = SUPPLIERS.get(supplier_id)
    if not details:
        raise HTTPException(status_code=404, detail="unknown supplier_id")
    return {"supplier_id": supplier_id, **details}
