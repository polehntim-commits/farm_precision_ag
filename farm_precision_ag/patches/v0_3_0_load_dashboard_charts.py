import frappe


def execute():
    """Reload Dashboard Chart + Number Card fixtures.

    Called on `bench migrate`. Deletes any stale versions of our
    charts/cards so the fresh fixtures land clean, then Frappe's
    normal fixture sync (which runs later in the same migrate) re-imports
    them from the app JSON.

    Runs under [post_model_sync], i.e. after the model is synced but before
    `sync_fixtures`, so the delete-then-reimport ordering holds.
    """
    chart_names = [
        "USDA Cherries - Shipping Point by Size",
        "USDA Cherries - Shipping Point by Variety",
        "USDA Cherries - Terminal Market by Origin",
        "USDA Cherries - Weekly Average",
    ]
    card_names = [
        "USDA Cherries Latest Shipping Price",
        "USDA Records Cached",
    ]
    # Delete stale charts so fixture reimport is clean
    for name in chart_names:
        if frappe.db.exists("Dashboard Chart", name):
            frappe.delete_doc("Dashboard Chart", name, force=True)
    for name in card_names:
        if frappe.db.exists("Number Card", name):
            frappe.delete_doc("Number Card", name, force=True)

    frappe.db.commit()
