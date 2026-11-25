# OrderFlow Markets — Stock Market Order Matching Engine

A price-time-priority order matching engine with a **pure C core**, a
**Streamlit** front end, and **SQLite (WAL)** storage.

## Architecture

```
engine/orderbook.c      C core: the actual matching engine
                         - Bid/ask "priority queues" as sorted pointer
                           arrays (max-first for bids, min-first for asks)
                         - Per-price FIFO queues: doubly linked list per
                           price level -> strict time priority
                         - Matching loop: crosses bids/asks, emits trades,
                           removes depleted orders/levels
                         - Order index: chained hash table, order_id ->
                           order pointer, for O(1) cancel
                         - Event log: growable in-memory array of every
                           accept / trade / cancel
                         Compiles to:
                           liborderbook.so  -> used by Python via ctypes
                           orderbook_cli    -> standalone console demo
                                               (depth, trade tape, counters)

app/engine_bridge.py     ctypes wrapper — the ONLY way Python talks to the
                         engine. No matching logic lives in Python.
app/db.py                SQLite in WAL mode: users, verification codes,
                         order/trade history.
app/mailer.py            Sends the signup "welcome + verification code"
                         email (see note below).
app/ipo_data.py          Searchable IPO/symbol catalogue + synthetic price
                         history & order flow (see note below).
app/style.py             Premium navy / white / grey theme, Times New
                         Roman typography.
app/streamlit_app.py     The app itself: login/signup/demo flow, IPO
                         search, order entry, live book depth, trade tape,
                         pie + line charts, psutil performance counters.
```

## Running it

```bash
cd stock_matching_engine
bash engine/build.sh                 # compiles liborderbook.so + orderbook_cli
pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

Try the standalone C demo on its own (no Python needed) with:
```bash
./engine/orderbook_cli
```

## What was actually improved vs. a naive matching engine

- **No scanning on cancel/modify**: a hash-table order index gives O(1)
  average lookup instead of walking the whole book.
- **Stable price-level addresses**: price levels are individually
  allocated and the sorted arrays only ever reorder *pointers*, so the
  order index is never invalidated by a level being inserted/removed
  elsewhere in the book (a common bug in naive sorted-array books).
- **Strict time priority within a price**: a true FIFO linked list per
  level, not just "whoever's price is better."
- **Market orders are IOC (immediate-or-cancel)**: they never rest in the
  book and silently distort the visible depth; any unfilled remainder is
  logged, not hidden.
- **Full audit trail**: every accept/trade/cancel is logged with a
  monotonic sequence number, independent of wall-clock time, so ordering
  is always reconstructable even under clock skew.
- **Decoupled storage**: SQLite (WAL) persists accounts and history across
  restarts; the in-memory C book itself resets per process, by design,
  since real exchanges don't persist the live book either — the trade
  tape/history is what's durable.

## Two honest limitations (sandbox constraints while building this)

1. **Email delivery is simulated.** This build environment has no
   outbound network access, so a real SMTP call can't be placed here. The
   verification-code email is written to a local "inbox preview" panel in
   the app instead of actually being delivered. To send **real** email,
   set these environment variables before launching Streamlit and
   `mailer.py` will automatically switch to real SMTP:
   `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`.
2. **IPO/market data is synthetic.** There's no live market-data or IPO
   listing API wired in (again, no network in this sandbox) — `ipo_data.py`
   generates a deterministic, seeded random walk per symbol instead, so
   charts and the demo book always have believable, stable-looking data.
   Swap `generate_price_history()` for a real data provider call later;
   nothing else in the app needs to change.

## Login flow implemented

- New email -> verification code issued (SQLite, 10-minute expiry, rate
  limited to 5 attempts) -> code confirmed -> choose username & password
  -> account created and logged in.
- Existing email -> told the account already exists -> password prompt ->
  straight into their own dashboard.
- "Continue with Demo Account" -> full read access (IPO search, price
  chart, live order book depth, trade tape, pie/line charts, performance
  counters) but submitting or cancelling an order is blocked with a
  prompt to log in or sign up, exactly as specified.

## Notes on the design choices

- Colors are deliberately restricted to navy / white / grey per the
  brief, with one warm gold (`#e9c46a`) and one teal (`#4fb6a8`) accent
  reserved *only* for chart series, so the charts read clearly without
  breaking the overall palette.
- Typography is Times New Roman throughout (`style.py`).
- Passwords are stored as PBKDF2-HMAC-SHA256 hashes (200,000 iterations)
  with a per-user random salt — plaintext passwords are never stored.
