"""Controller for the USDA Query Log DocType.

Entries are append-only: once inserted they can never be modified or deleted.
The DocType JSON marks every field read-only; this controller is the
belt-and-suspenders guard against writes via ignore_permissions or direct API
calls (mirrors farm_i9's I-9 Audit Log).
"""

import frappe
from frappe import _
from frappe.model.document import Document


class USDAQueryLog(Document):
    def validate(self):
        # Allow the first insert (still new / local), block every later write.
        if not self.is_new() and not frappe.flags.in_install:
            frappe.throw(_("USDA Query Log entries are immutable."))

    def on_trash(self):
        if not frappe.flags.in_install:
            frappe.throw(_("USDA Query Log entries cannot be deleted."))
