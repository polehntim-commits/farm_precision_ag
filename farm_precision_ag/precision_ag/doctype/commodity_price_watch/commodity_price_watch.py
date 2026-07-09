"""Controller for the Commodity Price Watch DocType.

A watch is a small configuration record telling the daily scheduler which USDA
commodity + report slug to pull. Business logic lives in the USDA client /
scheduler; the controller only normalises input.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class CommodityPriceWatch(Document):
    def validate(self):
        # Normalise the free-text identifiers so cache fingerprints and dedup
        # keys stay stable regardless of stray whitespace.
        if self.commodity_name:
            self.commodity_name = self.commodity_name.strip()
        if self.slug_id:
            self.slug_id = self.slug_id.strip()
        if self.market_name:
            self.market_name = self.market_name.strip() or None

        if not self.commodity_name:
            frappe.throw(_("Commodity Name is required."))
        if not self.slug_id:
            frappe.throw(_("USDA Report Slug is required."))
