# korral-mcp

MCP server that lets a Duvo agent talk to Korral's StoreLink store-ordering/stock-tracking API, so category buyers can offload the daily "check on-hand vs. POS, decide if a store will go empty, raise a replenishment order" detective work described in `CLAUDE.md`.

## Files

- `server.py` — the MCP server (`FastMCP`). Exposes 3 tools to the agent.
- `storelink.py` — mock StoreLink API (FastAPI), standing in for the real Korral system during local dev.
- `key_manager.py` — loads per-store `X-Korral-Store-Key` values from `keys.json` and resolves store_id ↔ key.
- `keys.json` — store_id → key map (git-ignored; seeded with test keys for local dev).
- `.env` / `.env.example` — `STORELINK_API_URL` and `STORELINK_KEYS_FILE` config.
- `requirements.txt` — `mcp`, `fastapi`, `uvicorn`, `httpx`, `python-dotenv`, `pydantic`.

## Running locally

```bash
pip install -r requirements.txt

# terminal 1: mock StoreLink API
uvicorn storelink:app --reload --port 8000

# terminal 2: MCP server (reads STORELINK_API_URL=http://localhost:8000/v1 from .env)
python server.py
```

## Tools exposed

- **`check_stock_status(store_id, sku, fields=None)`** — on-hand units and/or recent sales for a SKU (`fields`: subset of `["on_hand", "hours_of_stock_left"]`, defaults to both; field names match the result keys, and an unknown field is rejected with a clear error rather than silently ignored). Requesting `hours_of_stock_left` returns `units_sold_last_24h`, `hourly_sales_rate`, and `hours_of_stock_left` (all derived from trailing-24h POS). `units_sold_last_24h` is returned explicitly so the "gap between on-hand and last 24h of sales" comparison a buyer makes is a direct subtraction, not something the agent has to reconstruct from the rate. `hours_of_stock_left` is `None` when there are no recent sales to project from.
- **`raise_replenishment(store_id, sku, quantity)`** — raises a replenishment order, returns `order_id` and status.
- **`get_replenishment_status(store_id, order_id)`** — looks up the status of a previously raised order.

## StoreLink endpoints not exposed as tools

The mock implements the full StoreLink surface these tools need, but several endpoints from the spec are deliberately not wrapped as MCP tools at all:

| Endpoint | Why it's not a tool |
|---|---|
| `GET /v1/stores` (list stores) | The agent operates on a `store_id` the buyer already gave it; browsing the full store list isn't part of the "is this SKU about to run out" workflow and would let the agent wander into stores/regions it has no reason to touch. |
| `GET /v1/stores/{store_id}` (store detail) | Same reasoning — store metadata (name, address, etc.) isn't needed to check stock or raise a reorder. |
| `GET /v1/skus/{sku}` (SKU detail) | Only used internally to resolve a SKU's `supplier_id` for the (now-removed) lead-time enrichment. With that scoped out, there's no current caller for this data, so it's not exposed. |
| `GET /v1/suppliers/{supplier_id}` (supplier detail) | Same as above — was only reachable via the SKU lookup, and had no other use. |

These aren't gaps — they're the API's general-browsing/reference endpoints, and the tool surface is intentionally narrowed to the three actions a buyer's agent actually needs: check status, reorder, track the order. If a future workflow needs store or supplier metadata, adding it back is a deliberate decision, not something we forgot.

## Key decisions and tradeoffs

**Only 3 tools, not a 1:1 wrapper of the StoreLink API.** StoreLink exposes 8 endpoints (stores list, store detail, inventory, POS, replenishment create/status, SKU detail, supplier detail). We deliberately don't expose store list/detail, raw SKU lookup, or raw supplier lookup as tools — the agent's job is narrowly "is this SKU about to run out at this store, and if so, reorder it," not general StoreLink browsing. Fewer tools means a smaller, easier-to-reason-about surface for the agent and less risk of it wandering into unrelated data.
*Tradeoff:* if a future workflow needs store metadata or supplier browsing, those tools don't exist yet and would need to be added deliberately (a feature, not a gap we forgot).

**`check_stock_status` takes an optional `fields` list instead of being two separate tools.** On-hand and hours-left both start from the same inventory lookup, and a caller sometimes only wants on-hand (cheap) without paying for the POS call (more expensive, more data). One tool with optional fields avoids duplicating the store/key/HTTP plumbing across near-identical tools, while still letting the caller avoid unnecessary calls.
*Tradeoff:* the tool's contract is slightly more complex than a plain single-purpose tool (caller needs to know the `fields` values), but this is a small, well-documented list.

**Supplier lead-time enrichment (`time_to_replenish`) was scoped out.** An earlier draft had `check_stock_status` also return the SKU's supplier lead time, so the agent could compare "hours left" vs. "time to replenish" and judge urgency in one call. We pulled it back out: the *comparison logic* (small gap between hours-left and lead-time ⇒ trigger reorder) is exactly the kind of decision that should stay explicit and reviewable rather than buried in a tool's return value, and until that policy is defined, a lead-time field would just be unused surface area on the tool.
*Tradeoff:* the agent (or buyer) currently has to know or separately determine supplier lead time to judge urgency — there's no shortcut for that yet. Revisit once the reorder-trigger policy is actually decided.

**`storelink.py` is a real HTTP mock (FastAPI + uvicorn), not an in-process fake.** `server.py` talks to it over `httpx` exactly as it would talk to the real StoreLink API, including the `X-Korral-Store-Key` auth header and per-store key validation (a mismatched key/store_id pair gets a 401). This exercises the real integration path (auth, HTTP errors, JSON shapes) rather than a shortcut that would need to be re-validated when pointed at the real API.
*Tradeoff:* more moving parts locally (two processes) than a pure in-memory fake.

**Keys are per-store, loaded from `keys.json`, not baked into `server.py`.** StoreLink keys are scoped to a single store and rotated weekly by Korral IT. `key_manager.py` centralizes key lookup so a key rotation only means updating `keys.json`, not code, and one MCP server instance can serve a buyer who covers multiple stores.
