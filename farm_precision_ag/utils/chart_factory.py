"""Chart factory — generate Dashboard Charts + Number Cards per commodity.

Instead of shipping Cherry-specific chart fixtures, we generate the standard
visualization set for *any* commodity a user is watching. A Commodity Price
Watch is the parameter; the factory stamps out deterministically-named
Dashboard Charts and Number Cards filtered to that commodity.

Wired up three ways (see hooks.py / commodity_price_watch.js):
  * ``after_insert`` on Commodity Price Watch  → auto-generate
  * ``on_trash``     on Commodity Price Watch  → auto-cleanup
  * a whitelisted API behind the "Generate Charts" form button

── Frappe v15 Dashboard Chart schema notes ──────────────────────────────
The two similarly-named fields are easy to conflate:
  * ``chart_type``  = the *data mode*: Count / Sum / Average / Group By /
                      Custom / Report.  (NOT the visual style.)
  * ``type``        = the *visual*: Line / Bar / Percentage / Pie / Donut /
                      Heatmap.

Grouped time-series (one line per group over time) is where stock Frappe v15
falls down: a DocType-based chart with ``Group By`` + ``timeseries=1`` renders
a *flat line at 0* — the "Group of Groups" combination isn't supported. So the
by-Size / by-Variety / by-Origin charts are built as **Report-based** charts
(``chart_type="Report"``) backed by the ``USDA Price Trend by Grouping`` Script
Report, which pivots the data itself and returns a ready-made multi-line chart.
Those charts set ``use_report_chart=1`` so they render the report's own chart
rather than trying to auto-build one from ``x_field``/``y_axis`` (impossible
here — the per-group series columns are discovered dynamically per commodity,
so they can't be listed ahead of time).

Only the Weekly Average stays a DocType-based chart: it's a single time series
with no grouping (``chart_type="Average"``, ``timeseries=1``), which works fine.

Generated docs deliberately leave ``module`` unset so they're treated as
site/user data, not app-shipped fixtures.
"""

import json

import frappe

CHART_DOCTYPE = "Dashboard Chart"
CARD_DOCTYPE = "Number Card"
SOURCE_DOCTYPE = "USDA Market Price"
TREND_REPORT = "USDA Price Trend by Grouping"


# ── Public API ───────────────────────────────────────────────────────────


def generate_charts_for_watch(watch_name: str, force_recreate: bool = False) -> dict:
    """Create the 4 standard Dashboard Charts + 2 Number Cards for a Watch.

    Args:
        watch_name: name of the Commodity Price Watch record.
        force_recreate: if True, delete existing generated items first.

    Returns:
        dict with keys: created_charts, created_cards, skipped, errors.
    """
    result = {"created_charts": [], "created_cards": [], "skipped": [], "errors": []}

    watch = frappe.get_doc("Commodity Price Watch", watch_name)
    commodity = (watch.commodity_name or "").strip()
    if not commodity:
        result["errors"].append(f"Watch {watch_name} has no commodity_name.")
        return result

    chart_specs = [
        _shipping_point_by_size_spec(commodity),
        _shipping_point_by_variety_spec(commodity),
        _terminal_market_by_origin_spec(commodity),
        _weekly_average_spec(commodity),
    ]
    for spec in chart_specs:
        name = spec["name"]
        if force_recreate and frappe.db.exists(CHART_DOCTYPE, name):
            frappe.delete_doc(CHART_DOCTYPE, name, force=True)
        if frappe.db.exists(CHART_DOCTYPE, name):
            result["skipped"].append(name)
            continue
        try:
            doc = frappe.get_doc({"doctype": CHART_DOCTYPE, **spec})
            doc.insert(ignore_permissions=True)
            result["created_charts"].append(name)
        except Exception as e:
            result["errors"].append(f"{name}: {e}")

    card_specs = [
        _latest_shipping_price_card_spec(commodity),
        _records_cached_card_spec(commodity),
    ]
    for spec in card_specs:
        name = spec["name"]
        if force_recreate and frappe.db.exists(CARD_DOCTYPE, name):
            frappe.delete_doc(CARD_DOCTYPE, name, force=True)
        if frappe.db.exists(CARD_DOCTYPE, name):
            result["skipped"].append(name)
            continue
        try:
            doc = frappe.get_doc({"doctype": CARD_DOCTYPE, **spec})
            doc.insert(ignore_permissions=True)
            result["created_cards"].append(name)
        except Exception as e:
            result["errors"].append(f"{name}: {e}")

    frappe.db.commit()
    return result


def cleanup_charts_for_watch(watch_name: str, commodity_name: str = None) -> dict:
    """Delete the 4 charts + 2 cards for a Watch.

    ``commodity_name`` may be passed directly for the delete path, where the
    Watch row is already gone by the time we need its commodity.
    """
    if commodity_name is None:
        try:
            watch = frappe.get_doc("Commodity Price Watch", watch_name)
            commodity_name = watch.commodity_name
        except frappe.DoesNotExistError:
            return {"errors": [f"Cannot lookup commodity for deleted watch {watch_name}"]}

    commodity = (commodity_name or "").strip()
    if not commodity:
        return {"errors": [f"Watch {watch_name} has no commodity_name."]}

    deleted = []
    for name in _chart_names(commodity):
        if frappe.db.exists(CHART_DOCTYPE, name):
            frappe.delete_doc(CHART_DOCTYPE, name, force=True)
            deleted.append(name)
    for name in _card_names(commodity):
        if frappe.db.exists(CARD_DOCTYPE, name):
            frappe.delete_doc(CARD_DOCTYPE, name, force=True)
            deleted.append(name)
    frappe.db.commit()
    return {"deleted": deleted}


@frappe.whitelist()
def generate_charts_api(watch_name: str, force_recreate=False):
    """Called from Commodity Price Watch's "Generate Charts" button."""
    # Args from the JS layer arrive as strings; coerce the flag.
    if isinstance(force_recreate, str):
        force_recreate = force_recreate.lower() in ("1", "true", "yes")
    return generate_charts_for_watch(watch_name, force_recreate=bool(force_recreate))


# ── doc_events wrappers (soft-failing so they never block a Watch op) ─────


def _auto_generate_after_insert(doc, method=None):
    """after_insert on Commodity Price Watch — generate the chart set."""
    try:
        generate_charts_for_watch(doc.name)
    except Exception as e:
        frappe.log_error(
            f"Auto-generate charts failed for {doc.name}: {e}",
            "farm_precision_ag chart_factory",
        )


def _auto_cleanup_before_trash(doc, method=None):
    """on_trash on Commodity Price Watch — remove its chart set.

    The Watch row still exists at on_trash time, so we pass commodity_name
    explicitly to be safe against ordering surprises.
    """
    try:
        cleanup_charts_for_watch(doc.name, commodity_name=doc.commodity_name)
    except Exception as e:
        frappe.log_error(
            f"Auto-cleanup charts failed for {doc.name}: {e}",
            "farm_precision_ag chart_factory",
        )


# ── Deterministic naming (single source of truth) ────────────────────────


def _chart_names(commodity: str) -> list:
    return [
        f"USDA {commodity} - Shipping Point by Size",
        f"USDA {commodity} - Shipping Point by Variety",
        f"USDA {commodity} - Terminal Market by Origin",
        f"USDA {commodity} - Weekly Average",
    ]


def _card_names(commodity: str) -> list:
    return [
        f"USDA {commodity} Latest Shipping Price",
        f"USDA {commodity} Records Cached",
    ]


def _commodity_filter(commodity: str, report_type: str = None) -> list:
    """Build a Frappe filter list scoped to one commodity (+ optional report type).

    Exact-match on ``commodity_name`` keeps each Watch's charts scoped to its
    own commodity (the Watch's ``commodity_name`` is the canonical query term).
    """
    filters = [[SOURCE_DOCTYPE, "commodity_name", "=", commodity, False]]
    if report_type:
        filters.insert(0, [SOURCE_DOCTYPE, "report_type", "=", report_type, False])
    return filters


# ── Chart spec builders (parameterized by commodity) ─────────────────────


def _report_chart_spec(
    commodity: str,
    report_type: str,
    group_by: str,
    name_suffix: str,
    chart_type: str = "Line",
) -> dict:
    """Build a Report-based Dashboard Chart backed by the trend Script Report.

    The three grouped charts are multi-line time series, which stock Frappe v15
    can't produce from a DocType source (``Group By`` + ``timeseries`` renders a
    flat line at 0). Instead they read from the ``USDA Price Trend by Grouping``
    Script Report, which pivots the data and returns its own multi-line chart.

    Field notes (verified against the v15 Dashboard Chart schema):
      * ``chart_type="Report"``  — the *data mode* (not the visual). This is the
        field that selects a Report source; there is no ``data_source_type``.
      * ``type``                 — the *visual* (Line).
      * ``report_name``          — the backing Report.
      * ``use_report_chart=1``   — render the chart the report returns. Required
        here: the y-series columns are discovered dynamically per commodity, so
        we can't populate the ``y_axis`` child table with static fieldnames.
      * ``filters_json``         — for Report charts this is a *dict* of report
        filters (not the ``[[doctype, field, op, val, meta]]`` list used by
        DocType charts). It pre-populates the report so the chart "just works"
        with no user interaction.
    """
    return {
        "name": f"USDA {commodity} - {name_suffix}",
        "chart_name": f"USDA {commodity} — {name_suffix}",
        "chart_type": "Report",
        "type": chart_type,
        "report_name": TREND_REPORT,
        "use_report_chart": 1,
        "filters_json": json.dumps(
            {
                "commodity_name": commodity,
                "report_type": report_type,
                "group_by": group_by,
            }
        ),
        "is_public": 1,
    }


def _shipping_point_by_size_spec(commodity: str) -> dict:
    return _report_chart_spec(
        commodity=commodity,
        report_type="shipping_point",
        group_by="item_size",
        name_suffix="Shipping Point by Size",
    )


def _shipping_point_by_variety_spec(commodity: str) -> dict:
    return _report_chart_spec(
        commodity=commodity,
        report_type="shipping_point",
        group_by="variety",
        name_suffix="Shipping Point by Variety",
    )


def _terminal_market_by_origin_spec(commodity: str) -> dict:
    return _report_chart_spec(
        commodity=commodity,
        report_type="terminal_market",
        group_by="origin",
        name_suffix="Terminal Market by Origin",
    )


def _weekly_average_spec(commodity: str) -> dict:
    return {
        "name": f"USDA {commodity} - Weekly Average",
        "chart_name": f"USDA {commodity} — Weekly Average",
        "chart_type": "Average",
        "type": "Bar",
        "document_type": SOURCE_DOCTYPE,
        "based_on": "report_date",
        "value_based_on": "avg_price",
        "timeseries": 1,
        "timespan": "Last Year",
        "time_interval": "Weekly",
        "is_public": 1,
        "filters_json": json.dumps(_commodity_filter(commodity, "shipping_point")),
        "color": "#29CD42",
    }


# ── Number Card spec builders ────────────────────────────────────────────


def _latest_shipping_price_card_spec(commodity: str) -> dict:
    filters = _commodity_filter(commodity, "shipping_point")
    # Most-recent-week window. Frappe has no rolling-7-day token, so "last week"
    # (previous calendar week) is the closest Timespan; widen if it reads empty.
    filters.append([SOURCE_DOCTYPE, "report_date", "Timespan", "last week", False])
    return {
        "name": f"USDA {commodity} Latest Shipping Price",
        "label": f"Latest {commodity} Shipping Price (avg)",
        "type": "Document Type",
        "document_type": SOURCE_DOCTYPE,
        "function": "Average",
        "aggregate_function_based_on": "avg_price",
        "is_public": 1,
        "show_percentage_stats": 0,
        "filters_json": json.dumps(filters),
        "color": "#449CF0",
    }


def _records_cached_card_spec(commodity: str) -> dict:
    return {
        "name": f"USDA {commodity} Records Cached",
        "label": f"{commodity} Records Cached",
        "type": "Document Type",
        "document_type": SOURCE_DOCTYPE,
        "function": "Count",
        "is_public": 1,
        "show_percentage_stats": 0,
        "filters_json": json.dumps(_commodity_filter(commodity)),
        "color": "#7575FF",
    }
