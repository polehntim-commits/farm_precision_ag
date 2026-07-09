"""Keep the Precision Ag workspace in sync with the shipped JSON.

Wired as an ``after_migrate`` hook. Frappe treats an existing DB Workspace
record as user-customized and skips re-importing the app JSON, so shortcuts /
number cards added to the workspace JSON in a later release stay hidden. We
delete-and-reimport on every migrate so the JSON is authoritative. Mirrors
farm_i9's ``workspace_sync`` pattern.
"""

import frappe


def refresh_precision_ag_workspace():
    """Force reload of the Precision Ag workspace from the app's JSON.

    Safe because the Precision Ag workspace has no user customization surface —
    it's fully app-owned. If a user later wants to customize (add their own
    charts/links), they should fork this app rather than editing the workspace
    in the desk.
    """
    if not frappe.db.exists("Workspace", "Precision Ag"):
        return
    try:
        # Delete the existing workspace, then re-import from the app's JSON so
        # any newly-added shortcuts / number cards appear.
        frappe.delete_doc(
            "Workspace", "Precision Ag", force=True, ignore_permissions=True
        )

        import os

        from frappe.modules.import_file import import_file_by_path

        app_path = frappe.get_app_path(
            "farm_precision_ag",
            "precision_ag",
            "workspace",
            "precision_ag",
            "precision_ag.json",
        )
        if os.path.exists(app_path):
            import_file_by_path(app_path, force=True)
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(
            f"Failed to refresh Precision Ag workspace: {e}",
            "farm_precision_ag workspace_sync",
        )
