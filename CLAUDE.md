**Goal:**

We're going to ship a custom MCP server to a Duvo customer.

**Context:**

Korral is a European specialty grocery chain — ~180 stores, ~18,000 active SKUs. They run a homegrown store-ordering and stock-tracking tool called **StoreLink**. Korral's category buyers spend hours every day in StoreLink doing detective work — checking on-hand vs. POS, deciding whether a store is going to be empty by afternoon, raising replenishment orders. Duvo has just signed a pilot to put an agent on top of this workflow.

Your job is to build the MCP server that lets a Duvo agent talk to StoreLink, and to plan how Duvo will deploy and operate it inside Korral's environment.

**StoreLink API (excerpt):**

```
GET   /v1/stores                                       List stores
GET   /v1/stores/{store_id}                            Store details
GET   /v1/stores/{store_id}/inventory?sku={sku}        Current on-hand for a SKU
GET   /v1/stores/{store_id}/pos?sku={sku}&since=...    Recent POS transactions for a SKU
POST  /v1/stores/{store_id}/replenishment              Raise a replenishment order
GET   /v1/stores/{store_id}/replenishment/{order_id}   Order status
GET   /v1/skus/{sku}                                   SKU details (name, category, supplier)
GET   /v1/suppliers/{supplier_id}                      Supplier details (incl. lead time)
```

Auth: `X-Korral-Store-Key: <key>` header, sent on every request. Each key is scoped to a single store and rotated weekly by Korral's IT.