import frappe


def execute():
    """Regenerate the grouped Dashboard Charts with a populated Filter child table.

    v0.4.1 got the standalone Report rendering cleanly, but the Dashboard-embedded
    Report charts still showed "No Data". Cause: on a Dashboard, Frappe strips a
    Report chart's ``filters_json`` dict down to only the keys whose fieldname is a
    field on ``ref_doctype`` (``USDA Market Price``) — which drops ``group_by`` (a
    report meta-parameter) and ``report_type``. With ``report_type`` empty the
    Script Report's ``execute()`` returns nothing.

    The chart factory now also populates the Dashboard Chart's Filter *child table*
    (``filters``), which Frappe forwards to the report verbatim (the boot
    monkey-patch normalizes the list-format rows back to a dict). This patch drops
    the existing ``USDA Cherries%`` charts and rebuilds them so the child table gets
    populated. Mirrors the v0.4.0 regenerate patch.
    """
    from farm_precision_ag.utils.chart_factory import generate_charts_for_watch

    # Delete every stale Cherries chart so force_recreate rebuilds a clean set.
    for chart in frappe.get_all(
        "Dashboard Chart",
        filters={"name": ["like", "USDA Cherries%"]},
        pluck="name",
    ):
        frappe.delete_doc("Dashboard Chart", chart, force=True)

    # Rebuild for each Cherries watch (Commodity Price Watch autonames on
    # commodity_name, so the record name IS "Cherries"). Fall back to the plain
    # name lookup in case a site pre-dates the autoname rule.
    watches = frappe.get_all(
        "Commodity Price Watch",
        filters={"commodity_name": "Cherries"},
        pluck="name",
    )
    if not watches and frappe.db.exists("Commodity Price Watch", "Cherries"):
        watches = ["Cherries"]

    for watch_name in watches:
        try:
            generate_charts_for_watch(watch_name, force_recreate=True)
        except Exception as e:
            frappe.log_error(
                f"Regenerate charts (filter table) failed for {watch_name}: {e}",
                "farm_precision_ag v0.4.2 patch",
            )

    frappe.db.commit()
