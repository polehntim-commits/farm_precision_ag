"""USDA Market News (MARS) API client — Frappe port.

Ported from the Farm App (``app/utils/usda_market_news.py``). The low-level
``USDAMarketNewsClient`` class is pure HTTP + parsing and carries over almost
verbatim. The persistence layer (query logging, TTL cache, price upsert) is
re-implemented against Frappe DocTypes instead of SQLAlchemy.

API docs: https://mymarketnews.ams.usda.gov/mymarketnews-api
Base URL:  https://marsapi.ams.usda.gov/services/v1.2/reports/{slug_id}
Auth:      HTTP Basic — username = API key, password = empty string

The API key is read from the site config (``frappe.conf.get("usda_api_key")``),
which replaces the Flask config / encrypted-Settings injection in the Farm App.
"""

import base64
import gc
import logging
import time
from datetime import date, datetime, timedelta

import requests

import frappe
from frappe.utils import now_datetime

from farm_precision_ag.precision_ag.doctype.usda_market_price.usda_market_price import (
    DEDUP_FIELDS,
)

logger = logging.getLogger(__name__)

# Minimum hours between live API calls for the same (report_type:commodity)
# fingerprint. Matches the brief's 6-hour TTL. The Farm App made this
# per-watch; Phase B keeps it a single constant for simplicity.
CACHE_TTL_HOURS = 6


# ---------------------------------------------------------------------------
# API Client (pure HTTP + parsing — no DB access)
# ---------------------------------------------------------------------------

class USDAMarketNewsClient:
    """Low-level HTTP client for the USDA MARS API."""

    BASE_URL = "https://marsapi.ams.usda.gov/services/v1.2/reports"

    def __init__(self, api_key: str, timeout: int = 30):
        self.api_key = api_key
        self.timeout = timeout

    # -- public ---------------------------------------------------------------

    def _build_commodity_query(
        self,
        slug_id: str,
        commodity_name: str,
        begin_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        """Try fetching with a commodity filter, falling back through alternatives.

        Attempt order:
        1. ``commodity={name}``       — works for most report types
        2. ``commodity_name={name}``  — required by some shipping point reports
        3. No commodity filter        — fetch all, then client-side filter

        Returns the first non-empty successful result, or the last error. This
        fallback chain is important: different USDA report shapes accept
        different filter parameters.
        """
        date_part = (
            f"report_begin_date={begin_date}:{end_date}"
            if begin_date and end_date
            else ""
        )

        def _try(q_filter: str | None) -> dict:
            """Run the standard two-step fetch for a given q filter string."""
            q_parts = []
            if q_filter:
                q_parts.append(q_filter)
            if date_part:
                q_parts.append(date_part)
            q_str = ";".join(q_parts) if q_parts else None

            # Step 1: /Details (livestock / dairy / grain)
            url_details = f"{self.BASE_URL}/{slug_id}/Details"
            params_details = {"q": q_str} if q_str else {}
            r = self._do_get(url_details, params_details)
            if r["status"] == "success" and r["data"]:
                sample = r["data"][0]
                if any(
                    k in sample
                    for k in ("commodity", "low_price", "high_price", "mostly_low_price", "package")
                ):
                    return r

            # Step 2: allSections (specialty crops)
            url_base = f"{self.BASE_URL}/{slug_id}"
            params_base: dict = {"allSections": "true"}
            if q_str:
                params_base["q"] = q_str
            r2 = self._do_get(url_base, params_base)
            if r2["status"] == "success" and r2["data"]:
                return r2

            return r if r["data"] else r2

        # Attempt 1 — commodity=
        result = _try(f"commodity={commodity_name}")
        if result["status"] == "success" and result["data"]:
            return result

        # Attempt 2 — commodity_name= (shipping point reports)
        result2 = _try(f"commodity_name={commodity_name}")
        if result2["status"] == "success" and result2["data"]:
            return result2

        # Attempt 3 — no filter, client-side match
        result3 = _try(None)
        if result3["status"] == "success" and result3["data"]:
            name_lower = commodity_name.lower()
            filtered = [
                rec
                for rec in result3["data"]
                if name_lower in str(rec.get("commodity_name", "")).lower()
                or name_lower in str(rec.get("commodity", "")).lower()
            ]
            if filtered:
                return {
                    "status": "success",
                    "data": filtered,
                    "record_count": len(filtered),
                    "http_status": result3["http_status"],
                }

        # Return the first non-error result we got, or the last result
        for r in (result, result2, result3):
            if r["status"] == "success":
                return r
        return result3

    def fetch_prices(
        self,
        slug_id: str,
        commodity_name: str,
        begin_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        """Fetch price records from a MARS report.

        Returns ``{status, data: list, record_count: int, http_status: int|None}``.
        ``begin_date`` / ``end_date`` use ``MM/DD/YYYY`` format; both must be set.
        """
        return self._build_commodity_query(slug_id, commodity_name, begin_date, end_date)

    def _do_get(self, url: str, params: dict | None = None) -> dict:
        """Shared GET with auth fallback, retry for transient errors, and
        standard error handling.

        Handles two response shapes: a flat list of record dicts
        (livestock/dairy/grain), and a sectioned list of
        ``{reportSection, results: [...]}`` dicts (specialty crops with
        ``allSections=true``).

        Returns ``{status, data: list, record_count: int, http_status: int|None}``.
        """
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                resp = requests.get(
                    url,
                    headers=self._get_headers(),
                    params=params,
                    timeout=self.timeout,
                )
                if resp.status_code == 401:
                    resp = requests.get(
                        url,
                        auth=(self.api_key, ""),
                        params=params,
                        timeout=self.timeout,
                    )
                resp.raise_for_status()
                payload = resp.json()
                results = self._extract_results(payload)
                return {
                    "status": "success",
                    "data": results,
                    "record_count": len(results),
                    "http_status": resp.status_code,
                }
            except requests.exceptions.Timeout:
                if attempt < max_retries:
                    wait = 2 ** attempt
                    logger.warning(
                        "USDA API timeout (attempt %d/%d), retrying in %ds — url=%s",
                        attempt + 1, max_retries + 1, wait, url,
                    )
                    time.sleep(wait)
                    continue
                msg = f"USDA API timeout after {self.timeout}s (all retries exhausted)"
                logger.warning("%s — url=%s params=%s", msg, url, params)
                return {"status": "error", "error": msg, "http_status": None, "data": []}
            except requests.exceptions.HTTPError as exc:
                code = exc.response.status_code if exc.response is not None else None
                reason = exc.response.reason if exc.response is not None else str(exc)
                msg = f"HTTP {code}: {reason}"
                if code == 400:
                    # 400 Bad Request — expected when a slug has no data for
                    # that commodity/date. Not an error worth escalating.
                    logger.debug(
                        "USDA API 400 Bad Request — url=%s params=%s | %s",
                        url, params, reason,
                    )
                    return {"status": "error", "error": msg, "http_status": code, "data": []}
                if code is not None and code >= 500 and attempt < max_retries:
                    wait = 2 ** attempt
                    logger.warning(
                        "USDA API server error %s (attempt %d/%d), retrying in %ds — url=%s",
                        code, attempt + 1, max_retries + 1, wait, url,
                    )
                    time.sleep(wait)
                    continue
                logger.warning("USDA API error: %s — url=%s params=%s", msg, url, params)
                return {"status": "error", "error": msg, "http_status": code, "data": []}
            except Exception as exc:  # noqa: BLE001
                logger.exception("USDA API unexpected error — url=%s params=%s", url, params)
                return {"status": "error", "error": str(exc), "http_status": None, "data": []}

    @staticmethod
    def _extract_results(payload) -> list:
        """Extract the actual data records from a MARS API response.

        Handles: a dict with ``results``/``data`` key; a plain list of record
        dicts; and a sectioned list (Specialty Crops ``allSections=true``) where
        we return the *Report Details* section's ``results`` (or the largest
        non-header section).
        """
        if isinstance(payload, dict):
            inner = payload.get("results", payload.get("data", []))
            return [inner] if isinstance(inner, dict) else (inner if isinstance(inner, list) else [])

        if not isinstance(payload, list) or len(payload) == 0:
            return []

        first = payload[0]
        if isinstance(first, dict) and "reportSection" in first and "results" in first:
            detail_results = []  # noqa: F841 (kept for parity with Farm App)
            best_section = []
            for section in payload:
                sec_name = section.get("reportSection", "")
                sec_results = section.get("results", [])
                if not isinstance(sec_results, list):
                    continue
                if sec_name.lower() == "report details":
                    return sec_results
                if sec_name.lower() != "report header" and len(sec_results) > len(best_section):
                    best_section = sec_results
            if best_section:
                return best_section

        if isinstance(first, dict):
            return payload
        return []

    def _get_headers(self) -> dict:
        """Build auth headers using HTTP Basic via the Authorization header."""
        token = base64.b64encode(f"{self.api_key}:".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def test_connection(self) -> dict:
        """Quick connectivity test — tries multiple auth methods against the
        reports index and a known public report endpoint.
        """
        auth_methods = [
            ("header_basic", lambda: requests.get(
                self.BASE_URL, headers=self._get_headers(), timeout=10)),
            ("tuple_basic", lambda: requests.get(
                self.BASE_URL, auth=(self.api_key, ""), timeout=10)),
            ("header_basic_report", lambda: requests.get(
                f"{self.BASE_URL}/2458", headers=self._get_headers(), timeout=10)),
            ("tuple_basic_report", lambda: requests.get(
                f"{self.BASE_URL}/2458", auth=(self.api_key, ""), timeout=10)),
            ("api_key_param", lambda: requests.get(
                self.BASE_URL, params={"api_key": self.api_key}, timeout=10)),
        ]

        last_status = None
        last_reason = "Unknown"

        for method_name, call_fn in auth_methods:
            try:
                resp = call_fn()
                last_status = resp.status_code
                last_reason = resp.reason
                logger.info("USDA test_connection method=%s status=%s", method_name, resp.status_code)
                if resp.status_code == 200:
                    return {
                        "status": "success",
                        "http_status": 200,
                        "message": f"Connected (via {method_name})",
                        "auth_method": method_name,
                    }
            except Exception as exc:  # noqa: BLE001
                logger.debug("USDA test_connection method=%s error=%s", method_name, exc)
                continue

        return {
            "status": "error",
            "http_status": last_status,
            "message": (
                f"All auth methods failed. Last: HTTP {last_status} {last_reason}. "
                f"Verify your API key at mymarketnews.ams.usda.gov"
            ),
        }

    # -- parsers --------------------------------------------------------------

    def _parse_common_fields(self, record: dict) -> dict:
        """Extract fields common to terminal market, shipping point, and retail."""
        low = self._parse_price(record.get("low_price"))
        high = self._parse_price(record.get("high_price"))
        mostly_low = self._parse_price(record.get("mostly_low_price") or record.get("mostly_low"))
        mostly_high = self._parse_price(record.get("mostly_high_price") or record.get("mostly_high"))

        if low is None and mostly_low is not None:
            low = mostly_low
        if high is None and mostly_high is not None:
            high = mostly_high

        avg = self._parse_price(record.get("avg_price") or record.get("price"))
        if avg is None and low is not None and high is not None:
            avg = round((low + high) / 2, 2)

        # Detect "unchanged" status from USDA data — signalled via tone/offerings
        # comments or a literal UNCH price string.
        is_unchanged = False
        tone = (record.get("market_tone_comments") or "").strip().upper()
        offerings = (record.get("offerings_comments") or "").strip().upper()
        price_text = str(record.get("low_price") or "").strip().upper()
        if any(kw in tone for kw in ("UNCHANGED", "UNCH", "STEADY")):
            is_unchanged = True
        elif any(kw in offerings for kw in ("UNCHANGED", "UNCH")):
            is_unchanged = True
        elif price_text in ("UNCH", "UNCHANGED"):
            is_unchanged = True

        return {
            "low_price": low,
            "high_price": high,
            "mostly_low_price": mostly_low,
            "mostly_high_price": mostly_high,
            "avg_price": avg,
            "is_unchanged": is_unchanged,
            "variety": (record.get("variety") or record.get("class") or "").strip() or None,
            "grade": (record.get("grade") or "").strip() or None,
            "packaging": (
                record.get("package") or record.get("size_desc") or record.get("container") or ""
            ).strip() or None,
            "price_unit": (
                record.get("unit_sales") or record.get("unit_of_sale") or record.get("unit") or "per unit"
            ).strip(),
            "report_date": self._parse_date(
                record.get("report_date")
                or record.get("published_date")
                or record.get("published_Date")
            ),
            "commodity_name": (record.get("commodity") or "").strip() or None,
            "category": (record.get("category") or "").strip() or None,
            "item_size": (record.get("item_size") or "").strip() or None,
            "organic": self._normalise_organic(record.get("organic")),
            "quality": (record.get("quality") or "").strip() or None,
            "condition": (record.get("condition") or "").strip() or None,
            "appearance": (record.get("appearance") or "").strip() or None,
            "environment": (record.get("environment") or "").strip() or None,
            "market_tone_comments": (record.get("market_tone_comments") or "").strip() or None,
            "offerings_comments": (record.get("offerings_comments") or "").strip() or None,
        }

    def parse_terminal_market_record(self, record: dict) -> dict:
        """Normalise a terminal-market record into our price schema."""
        parsed = self._parse_common_fields(record)
        parsed["market_name"] = (
            record.get("market_location_city")
            or record.get("market_location_name")
            or record.get("city")
            or record.get("market")
            or ""
        ).strip()
        parsed["origin"] = (record.get("origin") or record.get("district") or "").strip() or None
        return parsed

    def parse_shipping_point_record(self, record: dict) -> dict:
        """Normalise a shipping-point record into our price schema."""
        parsed = self._parse_common_fields(record)
        parsed["market_name"] = (
            record.get("market_location_city")
            or record.get("market_location_name")
            or record.get("origin")
            or record.get("district")
            or ""
        ).strip()
        parsed["origin"] = (record.get("origin") or record.get("district") or "").strip() or None
        return parsed

    def parse_retail_record(self, record: dict) -> dict:
        """Normalise a retail report record (e.g. FVWRETAIL) into our schema.

        Retail records use advertised shelf prices at major supermarket outlets.
        """
        parsed = self._parse_common_fields(record)
        retailer = (record.get("store_name") or record.get("retailer") or "").strip()
        region = (record.get("region") or "").strip()
        parsed["market_name"] = ", ".join(filter(None, [retailer, region])) or ""
        if parsed.get("avg_price") is None:
            raw_price = record.get("price") or record.get("advertised_price")
            if raw_price is not None:
                try:
                    parsed["avg_price"] = float(raw_price)
                except (TypeError, ValueError):
                    pass
        if not parsed.get("price_unit"):
            parsed["price_unit"] = (record.get("unit") or "").strip() or None
        organic = record.get("organic", "")
        if organic and not parsed.get("variety"):
            parsed["variety"] = (
                "Organic"
                if str(organic).strip().lower() in ("yes", "true", "1", "organic")
                else None
            )
        parsed["origin"] = None  # retail records don't carry shipping origin
        return parsed

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def _parse_price(raw) -> float | None:
        if raw is None:
            return None
        try:
            return float(str(raw).replace("$", "").replace(",", "").strip())
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def _parse_date(raw) -> date | None:
        if raw is None:
            return None
        raw = str(raw).strip()
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _normalise_organic(raw) -> str | None:
        """Coerce the USDA organic value to the DocType's ``Y`` / ``N`` options."""
        if raw is None:
            return None
        val = str(raw).strip().lower()
        if val in ("y", "yes", "true", "1", "organic"):
            return "Y"
        if val in ("n", "no", "false", "0", "conventional"):
            return "N"
        return None


# ---------------------------------------------------------------------------
# Site config / API key
# ---------------------------------------------------------------------------

def get_api_key() -> str | None:
    """Read the USDA MARS API key from the site config.

    Set it with ``bench --site <site> set-config usda_api_key "abc123"`` or by
    adding ``"usda_api_key": "abc123"`` to ``site_config.json``.
    """
    return frappe.conf.get("usda_api_key")


# ---------------------------------------------------------------------------
# Persistence layer (Frappe DocTypes) — replaces the SQLAlchemy helpers
# ---------------------------------------------------------------------------

def _fingerprint(report_type: str, commodity_name: str) -> str:
    """Cache/dedup fingerprint for USDA Query Log: ``{report_type}:{commodity}``."""
    return f"{report_type}:{commodity_name}"


def should_refresh_watch(watch) -> bool:
    """Return ``True`` if this watch needs a fresh API call (TTL expired).

    Looks up the most recent successful (HTTP 200) USDA Query Log for the
    watch's ``{report_type}:{commodity_name}`` fingerprint and compares its age
    against ``CACHE_TTL_HOURS``.
    """
    fingerprint = _fingerprint(watch.report_type, watch.commodity_name)
    rows = frappe.get_all(
        "USDA Query Log",
        filters={
            "commodity_price_watch": watch.name,
            "query_fingerprint": fingerprint,
            "http_status": 200,
        },
        fields=["queried_at"],
        order_by="queried_at desc",
        limit=1,
    )
    if not rows:
        return True
    last = frappe.utils.get_datetime(rows[0].queried_at)
    age = now_datetime() - last
    return age > timedelta(hours=CACHE_TTL_HOURS)


def log_query(watch_name: str, fingerprint: str, report_type: str, result: dict) -> None:
    """Insert an immutable USDA Query Log row for one API call."""
    frappe.get_doc(
        {
            "doctype": "USDA Query Log",
            "commodity_price_watch": watch_name,
            "query_fingerprint": fingerprint,
            "report_type": report_type,
            "record_count": result.get("record_count"),
            "http_status": result.get("http_status"),
            "error_message": result.get("error") if result.get("status") != "success" else None,
        }
    ).insert(ignore_permissions=True)


def _dedup_filters(watch_name: str, report_type: str, parsed: dict) -> dict:
    """Build the DEDUP_FIELDS filter dict for a parsed record."""
    values = {
        "commodity_price_watch": watch_name,
        "report_type": report_type,
        "report_date": parsed["report_date"],
        "market_name": parsed["market_name"] or "",
        "commodity_name": parsed.get("commodity_name"),
        "origin": parsed.get("origin"),
        "packaging": parsed.get("packaging"),
        "variety": parsed.get("variety"),
        "grade": parsed.get("grade"),
        "item_size": parsed.get("item_size"),
        "organic": parsed.get("organic"),
    }
    # Frappe treats None and "" differently in filters; normalise to "" so the
    # dedup lookup is stable (mirrors the controller's validate()).
    return {f: (values.get(f) or "") for f in DEDUP_FIELDS}


def upsert_price(watch, report_type: str, parsed: dict, raw_record: dict) -> bool:
    """Insert or update a USDA Market Price row, de-duplicated on DEDUP_FIELDS.

    Returns ``True`` if a row was inserted/updated, ``False`` if skipped. When a
    record has null prices (unchanged / no new quote), the most recent known
    price for the same dedup key is carried forward and ``is_unchanged`` is set.
    """
    if parsed["report_date"] is None:
        return False

    is_unchanged = parsed.get("is_unchanged", False)
    prices_null = (
        parsed["low_price"] is None
        and parsed["high_price"] is None
        and parsed["avg_price"] is None
    )

    fill_low = parsed["low_price"]
    fill_high = parsed["high_price"]
    fill_avg = parsed["avg_price"]
    fill_mostly_low = parsed.get("mostly_low_price")
    fill_mostly_high = parsed.get("mostly_high_price")

    if prices_null:
        # Null prices on a report date almost always mean "unchanged" — forward
        # fill from the most recent non-null price with the same attributes.
        is_unchanged = True
        prev = _find_prior_price(watch.name, report_type, parsed)
        if prev:
            fill_low = prev.get("low_price")
            fill_high = prev.get("high_price")
            fill_avg = prev.get("avg_price")
            fill_mostly_low = prev.get("mostly_low_price")
            fill_mostly_high = prev.get("mostly_high_price")
        else:
            # Nothing to carry forward — skip this record entirely.
            return False

    update_fields = {
        "low_price": fill_low,
        "high_price": fill_high,
        "mostly_low_price": fill_mostly_low,
        "mostly_high_price": fill_mostly_high,
        "avg_price": fill_avg,
        "price_unit": parsed["price_unit"],
        "is_unchanged": 1 if is_unchanged else 0,
        "category": parsed.get("category"),
        "quality": parsed.get("quality"),
        "condition": parsed.get("condition"),
        "appearance": parsed.get("appearance"),
        "environment": parsed.get("environment"),
        "market_tone_comments": parsed.get("market_tone_comments"),
        "offerings_comments": parsed.get("offerings_comments"),
        "raw_data": frappe.as_json(raw_record),
        "cached_at": now_datetime(),
    }

    dedup = _dedup_filters(watch.name, report_type, parsed)
    existing = frappe.db.get_value("USDA Market Price", dedup, "name")

    if existing:
        doc = frappe.get_doc("USDA Market Price", existing)
        for k, v in update_fields.items():
            doc.set(k, v)
        doc.save(ignore_permissions=True)
    else:
        doc = frappe.get_doc({"doctype": "USDA Market Price", **dedup, **update_fields})
        doc.insert(ignore_permissions=True)
    return True


def _find_prior_price(watch_name: str, report_type: str, parsed: dict) -> dict | None:
    """Most recent USDA Market Price with the same key and a non-null price."""
    filters = {
        "commodity_price_watch": watch_name,
        "report_type": report_type,
        "commodity_name": parsed.get("commodity_name") or "",
        "market_name": parsed["market_name"] or "",
        "origin": parsed.get("origin") or "",
        "packaging": parsed.get("packaging") or "",
        "variety": parsed.get("variety") or "",
        "grade": parsed.get("grade") or "",
        "item_size": parsed.get("item_size") or "",
        "organic": parsed.get("organic") or "",
        "report_date": ("<", parsed["report_date"]),
        "avg_price": (">", 0),
    }
    rows = frappe.get_all(
        "USDA Market Price",
        filters=filters,
        fields=[
            "low_price", "high_price", "avg_price",
            "mostly_low_price", "mostly_high_price",
        ],
        order_by="report_date desc",
        limit=1,
    )
    return rows[0] if rows else None


def fetch_and_cache_watch(client: USDAMarketNewsClient, watch) -> dict:
    """Fetch + cache prices for a single Commodity Price Watch.

    Queries the last 14 days, logs the call, then upserts each matching record.
    Returns the raw API result dict (with an added ``stored`` count).
    """
    end_dt = now_datetime()
    begin_dt = end_dt - timedelta(days=14)

    result = client.fetch_prices(
        slug_id=watch.slug_id,
        commodity_name=watch.commodity_name,
        begin_date=begin_dt.strftime("%m/%d/%Y"),
        end_date=end_dt.strftime("%m/%d/%Y"),
    )

    fingerprint = _fingerprint(watch.report_type, watch.commodity_name)
    log_query(watch.name, fingerprint, watch.report_type, result)

    if result["status"] != "success":
        http_code = result.get("http_status")
        if http_code != 400:
            frappe.log_error(
                f"USDA fetch failed (HTTP {http_code}) for watch={watch.name} "
                f"slug={watch.slug_id} commodity={watch.commodity_name}: {result.get('error')}",
                "farm_precision_ag usda_client",
            )
        result["stored"] = 0
        return result

    parser = (
        client.parse_terminal_market_record
        if watch.report_type == "terminal_market"
        else client.parse_retail_record
        if watch.report_type == "retail"
        else client.parse_shipping_point_record
    )

    watch_commodity = (watch.commodity_name or "").strip().lower()
    market_filter = (watch.market_name or "").strip().lower()
    stored = 0

    for raw_rec in result["data"]:
        parsed = parser(raw_rec)

        # Only store records matching the watched commodity (partial, case-insensitive)
        record_commodity = (parsed.get("commodity_name") or "").strip().lower()
        if watch_commodity and record_commodity:
            if watch_commodity not in record_commodity and record_commodity not in watch_commodity:
                continue

        # Optional market-name filter
        if market_filter:
            record_market = (parsed.get("market_name") or "").strip().lower()
            if market_filter not in record_market:
                continue

        try:
            if upsert_price(watch, watch.report_type, parsed, raw_rec):
                stored += 1
        except frappe.DuplicateEntryError:
            # Two records in the same batch collapsed to the same dedup key —
            # harmless, the first one won.
            frappe.db.rollback()
        except Exception:  # noqa: BLE001
            frappe.log_error(
                f"USDA upsert error for watch={watch.name} on {parsed.get('report_date')}",
                "farm_precision_ag usda_client",
            )

    result["stored"] = stored
    return result


def refresh_watch(watch) -> dict:
    """Refresh a single watch, respecting the TTL cache. Updates the watch's
    ``last_fetched_at`` / ``last_record_count`` book-keeping fields.
    """
    api_key = get_api_key()
    if not api_key:
        return {"status": "error", "error": "No usda_api_key configured in site config."}

    if not should_refresh_watch(watch):
        return {"status": "cached", "stored": 0}

    client = USDAMarketNewsClient(api_key)
    result = fetch_and_cache_watch(client, watch)

    frappe.db.set_value(
        "Commodity Price Watch",
        watch.name,
        {
            "last_fetched_at": now_datetime(),
            "last_record_count": result.get("record_count") or 0,
        },
        update_modified=False,
    )
    frappe.db.commit()
    gc.collect()  # Umbrel is a Pi — free the response payload promptly.
    return result


def refresh_all_active_watches() -> list[dict]:
    """Refresh every active Commodity Price Watch. Returns per-watch summaries."""
    api_key = get_api_key()
    if not api_key:
        frappe.log_error(
            "USDA daily pull skipped: no usda_api_key in site config.",
            "farm_precision_ag usda_client",
        )
        return []

    names = frappe.get_all(
        "Commodity Price Watch", filters={"is_active": 1}, pluck="name"
    )
    summaries = []
    for name in names:
        watch = frappe.get_doc("Commodity Price Watch", name)
        try:
            res = refresh_watch(watch)
            summaries.append({"watch": name, "commodity": watch.commodity_name, **res})
        except Exception as exc:  # noqa: BLE001
            frappe.db.rollback()
            frappe.log_error(
                f"Error refreshing watch {name}: {exc}",
                "farm_precision_ag usda_client",
            )
            summaries.append({"watch": name, "error": str(exc)})
    return summaries
