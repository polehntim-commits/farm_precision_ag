# Farm Precision Ag

Precision agriculture module for ERPNext / Frappe, built for tree-fruit farms
running on Umbrel. This is the first migration of Farm App features into the
Frappe ecosystem.

**Scope — Phase B: USDA Market Pricing.** This release ships only the USDA
market-price integration: daily cached pulls of commodity prices from the USDA
Market News (MARS) API, browsable in the desk. Land / Blocks / Fields /
Implements / Spray / Attestations / Costing arrive in later phases (A, C, D, E,
F) and are intentionally **not** in this app yet.

Version: **0.3.0**

---

## What it does

- **Commodity Price Watch** — a small config record: which USDA commodity +
  report slug to track. One record per watch (e.g. "Cherries" on a terminal
  market report).
- **USDA Market Price** — cached price rows pulled from the MARS API,
  de-duplicated per commodity / market / report-date / attributes.
- **USDA Query Log** — an immutable log of every API call (record counts, HTTP
  status, errors). Powers the TTL cache and debugging.
- **USDA Settings** — a Single DocType (Precision Ag → Configuration) that holds
  the API key, base URL, TTL, timeout, attribution text, and live pull status.
  The primary, UI-managed source of configuration (see **Configuration** below).
- A **Precision Ag** workspace with shortcut tiles, packaged **Dashboard
  Charts** and **Number Cards** that visualize the cached USDA prices out of the
  box (see **Charts & Dashboards** below).
- A **daily scheduler** that refreshes every active watch automatically and
  writes its outcome back to USDA Settings (last successful pull, status,
  cached-record count).

---

## Setup

### 1. Get a USDA MARS API key

Request a free key at
<https://mymarketnews.ams.usda.gov/mymarketnews-api>. It arrives by email and is
used as the HTTP Basic **username** (password is blank).

### 2. Add the key (see Configuration below)

**Preferred:** in the desk, go to **Precision Ag → Configuration → USDA
Settings**, paste the key into **API Key**, and **Save**. See
[Configuration](#configuration) for details.

**Legacy fallback:** `bench --site frontend set-config usda_api_key "YOUR_KEY"`
still works if USDA Settings has no key. Without a key from either source, the
daily pull logs a skip and does nothing.

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

## Configuration

All USDA integration settings live on the **USDA Settings** Single DocType
(**Precision Ag → Configuration → USDA Settings**). This is the primary source
of truth; `site_config.json` remains a fallback for the API key only.

### API key

- **Preferred:** open **USDA Settings**, paste your key into **API Key**, and
  **Save**. Once a key is saved here, it becomes the source of truth and the
  scheduler/client read from it.
- **Legacy:** `bench --site <site> set-config usda_api_key '...'` still works as
  a fallback when USDA Settings has no key. Precedence is: USDA Settings →
  `site_config.json` → none.
- **Rotating the key:** just paste the new value and Save — no container SSH or
  `bench` restart needed. `API Key Last Rotated` is stamped automatically.
- **Storage & access:** the key is a Frappe **Password** field — encrypted at
  rest and never returned through the API. It carries `permlevel: 1`, so only
  **System Manager** can view or edit it. HR Manager and Sales Manager can read
  the rest of USDA Settings (attribution, status) but **not** the key.

### Test Connection

The **Test Connection** button (top-right **Actions** menu on USDA Settings)
makes one lightweight call to the `/reports` endpoint to verify auth and
connectivity. It proves the key works **without** pulling any commodity data,
and reports a clear message on `401 invalid key` vs other failures.

### Other settings

| Field                     | Purpose                                                                 |
| ------------------------- | ----------------------------------------------------------------------- |
| API Base URL              | MARS endpoint. Change only if USDA moves it or you route via a proxy.   |
| Attribution Text          | Shown in reports/UI (default "Data from USDA Agricultural Marketing Service"). |
| Request Timeout (seconds) | Per-request HTTP timeout (default 30).                                  |
| Request TTL (hours)       | How long cached data is trusted before re-querying (default 6).         |

### Status (read-only)

After each scheduled pull the client writes back **Last Successful Pull**,
**Last Pull Status** (`success` / `error` / `no-data`), **Last Error Message**,
and **Total Records Cached** — a quick health view without tailing logs.

---

## Charts & Dashboards

The Precision Ag workspace ships packaged **Dashboard Charts** and **Number
Cards** so the cached USDA data is visualized the moment you land on it — no
manual setup. They live under the **USDA Market Insights** section.

### Why shipping point is the primary signal

**Shipping-point (F.O.B.) price is the grower's decision signal** — it's what
the packing shed is actually being paid at origin, so it drives
sort/pack/ship-now-vs-hold calls. That's why three of the four charts and the
headline number card are built on `report_type = shipping_point`. **Terminal
market** prices are secondary — useful as a break-even (BEP) reference to see
what the downstream market is bearing against your shipping-point price.

### Shipped charts

| Chart | Breakdown | Source | Use |
| ----- | --------- | ------ | --- |
| **Shipping Point by Size** | avg price per `item_size` (48s, 60s…) | shipping_point | Sizing/packing decisions — bigger cherries usually clear a premium. |
| **Shipping Point by Variety** | avg price per `variety` | shipping_point | Bing vs Rainier vs Sweetheart price differentiation. |
| **Terminal Market by Origin** | avg price per `origin` | terminal_market | Where competing supply is coming from and what it's fetching downstream. |
| **Weekly Average (Trend)** | avg `avg_price`, weekly time series | shipping_point | Season trend line for the shipping-point average. |

### Shipped number cards

- **Latest Cherry Shipping Price (avg)** — average shipping-point `avg_price` for
  cherries over the most recent week.
- **USDA Records Cached** — total count of cached USDA Market Price rows.

### Filter note — `commodity_name LIKE %Cherr%`

USDA labels cherry reports inconsistently (both **"Cherries"** and **"Sweet
Cherries"** appear). Every chart/card filters with `commodity_name LIKE %Cherr%`
so both variants are caught in one query.

### Schema note — grouped charts

Frappe's native Dashboard Chart has **no grouped time-series** (one line per
group over time — that was Farm App's custom Chart.js). So the three "by
Size / Variety / Origin" charts ship as **Group By bar charts** (`chart_type =
Group By`, one bar per group value showing the average price), which is the
native way to keep the per-group breakdown. Only the single-series **Weekly
Average** is a true time series (`chart_type = Average`, `timeseries = 1`).

### Adding your own charts

You don't need to touch this app to add charts. Create a **Dashboard Chart** or
**Number Card** in the desk UI (New → Dashboard Chart), point it at **USDA
Market Price**, and drop it on any workspace. To fold a UI-created chart back
into the app so it re-ships, add its name to the `fixtures` list in `hooks.py`
and run `bench --site frontend export-fixtures --app farm_precision_ag`.

The workspace itself auto-syncs from the app JSON on every `bench migrate` (via
the existing `after_migrate` `workspace_sync` hook), so packaged tiles always
reflect the shipped layout.

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

- **Grouped time series.** The by-size / by-variety / by-origin charts ship as
  Group By bar charts because stock Frappe can't do multi-line-per-group over
  time. A true grouped time-series (Farm App's Chart.js look) would need a
  custom chart source or a Query Report backing a Report-type Dashboard Chart.
- **BEP overlay.** Overlaying terminal-market price on the shipping-point trend
  for a live break-even read is a natural next chart.
- Bake this app into the `fafo-erpnext` image (separate task, following the
  `farm_i9` Dockerfile pattern).
