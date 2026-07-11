import frappe


def execute():
    """Regenerate grouped Dashboard Charts to use the new Report-based data source.

    v0.3.0 shipped DocType-based charts with ``Group By`` + ``timeseries`` which
    Frappe v15 renders as a flat line at 0 ("Group of Groups" isn't supported).
    This patch deletes those charts and re-runs the chart factory, which now
    creates Report-based charts (``chart_type="Report"`` + ``use_report_chart``)
    backed by the ``USDA Price Trend by Grouping`` Script Report — a proper
    multi-line time series.

    The Weekly Average chart is left alone: it's a single time series that works.
    """
    from farm_precision_ag.utils.chart_factory import generate_charts_for_watch

    # Delete stale grouped charts (keep Weekly Average — it wasn't broken).
    suffixes_to_delete = [
        "Shipping Point by Size",
        "Shipping Point by Variety",
        "Terminal Market by Origin",
    ]
    for watch in frappe.get_all("Commodity Price Watch", fields=["name", "commodity_name"]):
        for suffix in suffixes_to_delete:
            chart_name = f"USDA {watch.commodity_name} - {suffix}"
            if frappe.db.exists("Dashboard Chart", chart_name):
                frappe.delete_doc("Dashboard Chart", chart_name, force=True)

    # Regenerate — new specs are Report-based. Charts already present (e.g.
    # Weekly Average) are skipped by the factory's exists() check.
    for watch in frappe.get_all("Commodity Price Watch", filters={"is_active": 1}):
        try:
            generate_charts_for_watch(watch.name)
        except Exception as e:
            frappe.log_error(
                f"Regenerate charts failed for {watch.name}: {e}",
                "farm_precision_ag v0.4.0 patch",
            )
    frappe.db.commit()
