"""Controller for the USDA Market Price DocType.

Frappe JSON can't express a multi-column unique index, so uniqueness is enforced
here in ``validate()``. The dedup key mirrors the Farm App's
``uix_usda_price_dedup_v3`` constraint: a price is unique per watch + report
type + report date + market + commodity + origin + packaging + variety + grade +
item size + organic. The USDA client upserts on this same key, so in normal
operation validate() never fires — it's the belt-and-suspenders guard against
manual/API inserts that would otherwise create duplicates.
"""

import frappe
from frappe import _
from frappe.model.document import Document

# Fields that together uniquely identify a price quote. Kept as a module
# constant so the USDA client can build the same dedup filter when upserting.
DEDUP_FIELDS = (
    "commodity_price_watch",
    "report_type",
    "report_date",
    "market_name",
    "commodity_name",
    "origin",
    "packaging",
    "variety",
    "grade",
    "item_size",
    "organic",
)


class USDAMarketPrice(Document):
    def validate(self):
        self._enforce_unique_dedup_key()

    def _enforce_unique_dedup_key(self):
        filters = {f: (self.get(f) or "") for f in DEDUP_FIELDS}
        # Exclude self so re-saving an existing row doesn't trip the guard.
        if not self.is_new():
            filters["name"] = ("!=", self.name)
        if frappe.db.exists("USDA Market Price", filters):
            frappe.throw(
                _(
                    "A USDA Market Price already exists for this "
                    "commodity/market/report-date/attribute combination."
                ),
                frappe.DuplicateEntryError,
            )
