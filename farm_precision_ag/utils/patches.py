"""Frappe monkey-patches for farm_precision_ag.

Applied at boot via hooks.py's boot_session (and re-asserted on migrate) so the
fix is active for every request, before any Script Report gets called.
"""

import frappe


def patch_report_execute_module(bootinfo=None):
    """Normalize list-of-lists filters to dict at Report.execute_module.

    Frappe v15 lets Dashboard-level filters propagate to Script Report charts
    in DocType list-of-lists format `[[doctype, fieldname, op, value, hidden], ...]`.
    Script Reports expect dict filters, and Frappe's `Report.execute_module`
    does `frappe._dict(filters)` unconditionally — which crashes with
    `ValueError: dictionary update sequence element #0 has length 5; 2 is required`
    when filters is a list. Patch execute_module to convert list-format to dict
    before calling the original, so Script Reports co-exist with DocType charts
    on the same dashboard.

    Accepts an optional `bootinfo` arg so this doubles as a `boot_session` hook
    (Frappe calls boot_session methods with the bootinfo dict). The arg is
    ignored — we only need the side effect of installing the patch.

    Idempotent — safe to call from any hook. Only patches once per process.
    """
    from frappe.core.doctype.report.report import Report

    if getattr(Report, "_farm_precision_ag_patched", False):
        return

    original = Report.execute_module

    def patched(self, filters):
        if isinstance(filters, (list, tuple)):
            converted = {}
            for f in filters:
                if isinstance(f, (list, tuple)) and len(f) >= 4:
                    # DocType filter list: [doctype, fieldname, operator, value, ...]
                    _, fieldname, operator, value = f[0], f[1], f[2], f[3]
                    # Only support "=" — other operators (>, <, like, in) don't
                    # map cleanly to Script Report dict filter semantics. Silently
                    # drop them; the Script Report's execute() applies its own
                    # defaults for missing filters.
                    if operator == "=" and value is not None:
                        converted[fieldname] = value
            filters = converted
        return original(self, filters)

    Report.execute_module = patched
    Report._farm_precision_ag_patched = True
