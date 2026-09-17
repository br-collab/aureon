# AUR-I-18 — Thifur-H books its ledger from the Kraken acknowledgement, not from the fill

**Status:** finding, recorded 17 September 2026 (W2B fix order F3). **Priority:** P1.
**Not built.** Bill decides when, because it touches the live Kraken account.

## What happens today

`aureon/thifur/thifur_h.py` places a maker-or-cancel limit order, and as soon as Kraken returns a
transaction id it writes the position into its own ledger:

```python
kraken_txids = (order_response.get("result") or {}).get("txid") or []
order_id = kraken_txids[0] if kraken_txids else order_response.get("order_id", "UNKNOWN")
self.ledger.orders_placed += 1
self.ledger.open_positions[order_id] = {
    "signal_id": signal.signal_id,
    "symbol":    signal.symbol,
    "side":      signal.side,
    "price":     signal.suggested_price,   # the signal's price, not an execution price
    "qty":       signal.suggested_qty,     # the signal's quantity, not a filled quantity
    "placed_at": datetime.now(timezone.utc).isoformat(),
    "status":    order_response.get("is_live", False),
}
```

Two separate problems:

1. **A placement is not an execution.** A maker-or-cancel order can rest unfilled, be cancelled, or
   be filled later, partially or at a different price. The ledger says the position is open the
   moment Kraken says "received".
2. **The recorded terms come from the intent.** `price` and `qty` are the signal's suggested
   values. Nothing in the ledger is evidence of what executed.

The exit path compounds it: it estimates profit and loss with `TAKER_FEE`/`MAKER_FEE` "assuming
immediate-fill semantics", with a comment saying the real figure will reconcile when Kraken reports
the fill. Nothing reconciles it.

This is the AUR-I-02 and AUR-I-06 defect class — booking from approved intent, and an execution
record derived from the intent it should be checked against — on the **live-money** path. Wave 2
fixed it for the paper path only (`aureon/booking/consumer.py` books from a venue fill, and
`aureon/booking/reconcile.py` compares intent with execution).

**What is not affected.** Thifur-H does not touch `aureon_state` cash, positions or trades, so the
$100M paper book is not polluted by this. The damage is confined to Thifur-H's own ledger and to the
DSOR (Deterministic Sequenced Operational Record) entries and profit-and-loss figures derived from
it, which are the evidence a validator would read for the live account.

## How to fix it: book from fill events

**Source of truth.** Kraken reports executions in three ways, in increasing order of reliability:

| Source | What it gives | Notes |
|---|---|---|
| `QueryOrders` (REST, private) | `vol_exec`, `cost`, `fee`, `price` (average), `status` | Poll per order id. Simple; a poll can miss intermediate states, but the terminal numbers are right. |
| `TradesHistory` / `QueryTrades` (REST, private) | one record per fill: `ordertxid`, `pair`, `type`, `price`, `vol`, `fee`, `time` | The real fill events. Paginate by `ofs` or by time. Correct for partial fills. |
| WebSocket `ownTrades` (private feed) | the same fill records, pushed | Lowest latency, but needs a socket, a token and reconnection handling. |

**Recommendation:** poll `TradesHistory` on the existing loop interval, keyed by order id, and treat
each returned trade as one execution event. It needs no new transport, it is the same shape as the
paper venue's fill, and it handles partial fills naturally. WebSocket `ownTrades` can replace the
poll later without changing anything downstream.

**Shape.** Reuse what Wave 2 already built rather than inventing a second one. A Kraken trade maps
onto the fill contract in `aureon/integration_adapters/paper_venue.py`:

| Fill field | From the Kraken trade |
|---|---|
| `fill_id` | the trade id (`TXID` of the trade, not the order) |
| `release_id` / `decision_id` | the order's `client_order_id`, which already carries the signal id |
| `symbol`, `action` | `pair`, `type` |
| `quantity`, `price`, `notional` | `vol`, `price`, `cost` |
| `venue` | `KRAKEN` |
| `price_observed_at`, `filled_at` | `time` |
| `provenance` | `FACT_EXTERNAL` — a real external execution, **not** `FACT_SYNTHETIC` |
| new: `fee` | `fee`, so profit and loss stops being an estimate |

**Ledger states.** The ledger needs the state a placement actually has:

- `SUBMITTED` — Kraken acknowledged the order. Records the order id and the **intended** terms,
  clearly labelled as intent, with no position.
- `PARTIALLY_FILLED` — one or more fills, cumulative quantity below the order quantity.
- `FILLED` — cumulative quantity equals the order quantity.
- `CANCELLED` / `EXPIRED` / `REJECTED` — terminal, no position.

A position exists only from the first fill, and its price is the volume-weighted average of the
fills, never the signal's suggested price.

## Partial fills

1. **Accumulate, do not overwrite.** Keep `filled_qty` and `cost` per order and add each new trade.
   The position's average price is `cost / filled_qty`.
2. **Idempotency by trade id.** Each Kraken trade id books once, exactly as `booked_fill_ids` works
   for the paper venue. A repeated poll must not double-book, and this is the main risk in a polling
   design.
3. **Exits size to what is held.** The auto-close and kill-switch paths must close `filled_qty`, not
   the signal's quantity. Closing a quantity that was never bought would open a short position on a
   live account.
4. **An unfilled remainder is not a position.** When an order is cancelled with a partial fill, the
   ledger keeps the filled part and drops the rest.
5. **Reconciliation.** Compare the intent with the accumulated fills using
   `aureon/booking/reconcile.py`: quantity exactly, price and notional within tolerance. A partial
   fill is not a break; a fill at an unexpected price is.

## Positions opened before the fix

Existing `open_positions` entries record intent, and there is no way to tell from the entry whether
that intent executed. Do not silently reinterpret them.

1. **Freeze and label.** On the first run of the new code, mark every existing entry
   `provenance: "INTENT_ONLY"` with `booked_from: "kraken_acknowledgement"` and the note that its
   price and quantity are the signal's.
2. **Backfill from `TradesHistory`.** Kraken keeps trade history; fetch it for the period the ledger
   covers and match on order id. For each matched entry, write the real filled quantity, average
   price and fees, and relabel it `FACT_EXTERNAL`.
3. **What does not match.** An entry with no trades never executed: mark it `NO_FILL_FOUND` and
   remove the position, without touching the audit record of the original entry.
4. **Restate profit and loss.** Figures derived from estimated fills are restated from the real
   fills, and the old figures are kept with an erratum, in the shape of
   `aureon/doctrine/ERRATA-2026-09-SR26-2.md`. Do not overwrite an audit artifact in place.
5. **Reconcile balances.** After the backfill, compare the ledger's implied position with Kraken's
   `Balance`. A difference means the backfill is incomplete, and it should be surfaced, not smoothed.

## Sequencing and risk

- The backfill and the labelling are read-only against Kraken and can land first, on their own.
- Booking from fills changes when a position is considered open, which changes when the auto-close
  logic arms. Run it with the auto-close disarmed until a full session reconciles cleanly.
- The kill-switch path must keep working throughout: it cancels orders and must never wait for a
  fill event.
- Validate against the sandbox account first, including a deliberate partial fill.

## Acceptance

- No ledger position exists without at least one Kraken trade id behind it.
- Ledger price and quantity always come from fills; the signal's values appear only under an
  `intent` key.
- The same trade delivered twice books once.
- A partial fill, then a cancel, leaves exactly the filled quantity.
- Profit and loss uses actual fees from the fills.
- Every pre-existing entry ends as `FACT_EXTERNAL` (backfilled), or `NO_FILL_FOUND` (removed, with
  the original kept as audit).
