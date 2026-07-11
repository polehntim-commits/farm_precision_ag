"""USDA Price Trend by Grouping — pivoted multi-series price trend.

Powers the by-Size / by-Variety / by-Origin Dashboard Charts (via the chart
factory) *and* works as a standalone Query Report at
``/app/query-report/USDA Price Trend by Grouping``.

Why a Script Report:
    Frappe v15 has no native "grouped time series" (one line per group over
    time). A DocType-based Dashboard Chart with ``Group By`` + ``timeseries``
    renders a flat line at 0. This report pivots the data itself — one column
    per distinct group value, one row per report_date — and returns a
    ready-made multi-line chart config as the 4th ``execute()`` value.

    The backing Dashboard Charts set ``use_report_chart = 1`` so they render
    THIS chart rather than trying to auto-build one from ``x_field``/``y_axis``
    (which can't work here, since the series columns are discovered
    dynamically per commodity and aren't known ahead of time).

Filters:
    commodity_name (required): e.g. "Cherries"
    report_type (required):    "shipping_point" or "terminal_market"
    group_by (required):       one of ALLOWED_GROUP_FIELDS (default "item_size")
    from_date (optional):      default 90 days ago
    to_date (optional):        default today
"""

import frappe
from frappe import _

# Only these columns of USDA Market Price may be used as the pivot dimension.
# Whitelisting is a hard guard because ``group_by`` is interpolated straight
# into SQL (identifiers can't be parameterized).
ALLOWED_GROUP_FIELDS = (
    "item_size",
    "variety",
    "origin",
    "grade",
    "packaging",
    "market_name",
)

SOURCE_TABLE = "`tabUSDA Market Price`"


def execute(filters=None):
    filters = filters or {}
    commodity = (filters.get("commodity_name") or "").strip()
    report_type = (filters.get("report_type") or "").strip()
    group_by = filters.get("group_by") or "item_size"
    from_date = filters.get("from_date") or frappe.utils.add_days(frappe.utils.today(), -90)
    to_date = filters.get("to_date") or frappe.utils.today()

    base_columns = [
        {"label": _("Report Date"), "fieldname": "report_date", "fieldtype": "Date", "width": 120},
    ]

    # Nothing to pivot without both scoping filters.
    if not commodity or not report_type:
        return base_columns, [], None, None

    if group_by not in ALLOWED_GROUP_FIELDS:
        group_by = "item_size"

    query_params = {
        "commodity": commodity,
        "report_type": report_type,
        "from_date": from_date,
        "to_date": to_date,
    }

    # ── Step 1: discover distinct group values for this commodity + report ──
    distinct_rows = frappe.db.sql(
        f"""
        SELECT DISTINCT `{group_by}`
        FROM {SOURCE_TABLE}
        WHERE commodity_name = %(commodity)s
          AND report_type = %(report_type)s
          AND report_date BETWEEN %(from_date)s AND %(to_date)s
          AND `{group_by}` IS NOT NULL AND `{group_by}` != ''
        ORDER BY `{group_by}`
        """,
        query_params,
    )
    distinct_values = [r[0] for r in distinct_rows if r[0]]

    # ── Step 2: build columns dynamically (one per group value) ────────────
    # Positional fieldnames (``s_0``, ``s_1``, …) sidestep any collision from
    # scrubbing free-text group values that differ only past 40 chars.
    columns = list(base_columns)
    field_for = {}
    for i, val in enumerate(distinct_values):
        fieldname = f"s_{i}"
        field_for[val] = fieldname
        columns.append(
            {
                "label": str(val),
                "fieldname": fieldname,
                "fieldtype": "Currency",
                "width": 130,
                "options": "USD",
            }
        )

    if not distinct_values:
        return columns, [], None, None

    # ── Step 3: aggregated pivot query (AVG price per date per group) ───────
    pivot_selects = ",\n            ".join(
        f"AVG(CASE WHEN `{group_by}` = %(val_{i})s THEN avg_price END) AS s_{i}"
        for i in range(len(distinct_values))
    )
    for i, val in enumerate(distinct_values):
        query_params[f"val_{i}"] = val

    rows = frappe.db.sql(
        f"""
        SELECT
            report_date,
            {pivot_selects}
        FROM {SOURCE_TABLE}
        WHERE commodity_name = %(commodity)s
          AND report_type = %(report_type)s
          AND report_date BETWEEN %(from_date)s AND %(to_date)s
          AND avg_price IS NOT NULL
        GROUP BY report_date
        ORDER BY report_date
        """,
        query_params,
        as_dict=True,
    )

    chart = _build_chart(rows, distinct_values, field_for)
    return columns, rows, None, chart


def _build_chart(rows, distinct_values, field_for):
    """Assemble a frappe-charts multi-line config from the pivoted rows.

    Returned as ``execute()``'s 4th value so the standalone Query Report page
    renders it, and so Dashboard Charts with ``use_report_chart = 1`` reuse it
    verbatim instead of trying to auto-build a chart from static y-fields.
    """
    labels = [str(r.get("report_date")) for r in rows]
    datasets = []
    for val in distinct_values:
        fieldname = field_for[val]
        values = [r.get(fieldname) for r in rows]
        datasets.append({"name": str(val), "values": values})

    return {
        "data": {"labels": labels, "datasets": datasets},
        "type": "line",
        "lineOptions": {"hideDots": 0, "regionFill": 0},
        "axisOptions": {"xIsSeries": 1},
    }
