# Farm Precision Ag

Precision agriculture module for ERPNext / Frappe, built for tree-fruit farms
running on Umbrel. This is the first migration of Farm App features into the
Frappe ecosystem.

**Scope — Phase B: USDA Market Pricing.** This release ships only the USDA
market-price integration: daily cached pulls of commodity prices from the USDA
Market News (MARS) API, browsable in the desk. Land / Blocks / Fields /
Implements / Spray / Attestations / Costing arrive in later phases (A, C, D, E,
F) and are intentionally **not** in this app yet.

Version: **0.1.0**

---

## What it does

- **Commodity Price Watch** — a small config record: which USDA commodity +
  report slug to track. One record per watch (e.g. "Cherries" on a terminal
  market report).
- **USDA Market Price** — cached price rows pulled from the MARS API,
  de-duplicated per commodity / market / report-date / attributes.
- **USDA Query Log** — an immutable log of every API call (record counts, HTTP
  status, errors). Powers the 6-hour TTL cache and debugging.
- A **Precision Ag** workspace with shortcut tiles and a "Prices Fetched Today"
  number card.
- A **daily scheduler** that refreshes every active watch automatically.

---

## Setup

### 1. Get a USDA MARS API key

Request a free key at
<https://mymarketnews.ams.usda.gov/mymarketnews-api>. It arrives by email and is
used as the HTTP Basic **username** (password is blank).

### 2. Add the key to your site config

```bash
bench --site frontend set-config usda_api_key "YOUR_KEY_HERE"
```

(or add `"usda_api_key": "YOUR_KEY_HERE"` to the site's `site_config.json`).

The app reads it via `frappe.conf.get("usda_api_key")`. Without it, the daily
pull logs a skip and does nothing.

### 3. Create a Commodity Price Watch

In the desk: **Precision Ag → Commodity Price Watch → New**. Fields:

| Field           | Meaning                                                              |
| --------------- | ------------------------------------------------------------------- |
| Commodity Name  | Exact USDA commodity name, e.g. `Cherries`, `Sweet Cherries`.        |
| USDA Report Slug| The MARS report id (see slug notes below).                          |
| Report Type     | `terminal_market`, `shipping_point`, or `retail`.                   |
| Market Name     | Optional filter to one market/location; blank = all markets.        |
| Active          | Only active watches are pulled by the scheduler.                    |

### 4. First manual pull (verifies auth + connectivity)

```bash
bench --site frontend execute farm_precision_ag.tasks.pull_usda_prices
```

Then open **USDA Market Price** — you should see rows. Check **USDA Query Log**
for the HTTP status of each call if nothing appears.

### 5. Ongoing

The `daily` scheduler event runs `pull_usda_prices` automatically. Each watch is
skipped if it was successfully fetched less than **6 hours** ago (TTL cache,
tracked via USDA Query Log). Make sure the bench scheduler is enabled:

```bash
bench --site frontend enable-scheduler
```

---

## Report types & slugs

**Report types**

- `terminal_market` — wholesale prices at big-city terminal markets (Specialty
  Crops Terminal Market reports). Best proxy for "what the market is paying".
- `shipping_point` — F.O.B. prices at the shipping-point / origin district.
  Closest to grower-side pricing.
- `retail` — advertised retail shelf prices at major supermarket chains
  (e.g. FVWRETAIL).

**Finding slug ids.** The Farm App did not hard-code slugs — Tim looked them up
per commodity using the MARS report finder. Do the same:

- Browse/search reports at
  <https://mymarketnews.ams.usda.gov/> (Tools → Reports) or the API report
  catalogue `GET https://marsapi.ams.usda.gov/services/v1.2/reports`.
- For **cherries**, the brief's starting guesses were slug **3080** (Specialty
  Crops Terminal Market) and **3040** (shipping point) — **verify these against
  the live catalogue before relying on them**; MARS renumbers reports and the
  right slug depends on the market you care about (e.g. the specific terminal
  city). A quick connectivity/shape check:

  ```bash
  curl -u "YOUR_KEY:" "https://marsapi.ams.usda.gov/services/v1.2/reports/3080?lastReports=1&allSections=true"
  ```

If a slug returns no rows for your commodity, the client automatically falls
back through `commodity=` → `commodity_name=` → no-filter + client-side match,
so a partial commodity name usually still resolves.

---

## Architecture notes

- **`farm_precision_ag/utils/usda_client.py`** — ported from the Farm App's
  `usda_market_news.py`. The `USDAMarketNewsClient` HTTP/parsing class is nearly
  verbatim; the persistence helpers were rewritten against Frappe DocTypes
  (`frappe.get_doc`, `frappe.db`) instead of SQLAlchemy.
- **`farm_precision_ag/utils/usda_scheduler.py`** — ported from
  `usda_price_scheduler.py`. Frappe owns the cadence via the `daily` hook, so
  this is just the per-run work.
- **`tasks.py`** — thin scheduler shim wired in `hooks.py`.
- The USDA Market Price uniqueness constraint (11 columns) can't be expressed in
  Frappe DocType JSON, so it's enforced in the controller's `validate()` and by
  an upsert-on-dedup-key path in the client.

## Follow-ups (not in this release)

- **Chart tile.** "Cherry Prices Last 30 Days" (line chart of `report_date` ×
  `avg_price`) was scoped out of Phase B to keep the first workspace simple. Add
  a Dashboard Chart on USDA Market Price later.
- Bake this app into the `fafo-erpnext` image (separate task, following the
  `farm_i9` Dockerfile pattern).
