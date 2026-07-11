import frappe


def execute():
    """Auto-generate charts for any existing active Commodity Price Watches.

    New installs get charts via the after_insert hook. This backfills installs
    that already have Watches (e.g. Tim's "Cherries" watch) so they pick up the
    factory-generated chart set on `bench migrate`.
    """
    from farm_precision_ag.utils.chart_factory import generate_charts_for_watch

    for watch in frappe.get_all("Commodity Price Watch", filters={"is_active": 1}):
        try:
            generate_charts_for_watch(watch.name)
        except Exception as e:
            frappe.log_error(
                f"Backfill charts failed for {watch.name}: {e}",
                "farm_precision_ag v0.3.0 patch",
            )
    frappe.db.commit()
