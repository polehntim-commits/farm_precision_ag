"""Controller for the USDA Settings Single DocType.

UI-managed configuration for the USDA MARS integration. The ``api_key`` field is
a Frappe Password type (encrypted at rest, never returned via the API, and
guarded by ``permlevel: 1`` so only System Manager can view/edit it).

Module-level getters (``get_api_key``, ``get_base_url``, ``get_ttl_seconds``,
``get_timeout_seconds``) are the single source of truth the client and scheduler
read from. Precedence for the API key: USDA Settings first, then the legacy
``site_config.json`` ``usda_api_key`` value, then ``None``.
"""

import frappe
from frappe.model.document import Document


class USDASettings(Document):
    def validate(self):
        # Track when the api_key was last rotated. Frappe stores Password
        # fields as encrypted values; compare against the saved value via
        # has_value_changed() to detect a real rotation (not just re-save).
        if self.has_value_changed("api_key"):
            self.api_key_last_rotated = frappe.utils.today()
        # Auto-count cached records for the status field
        self.total_records_cached = frappe.db.count("USDA Market Price")


# ---------------------------------------------------------------------------
# Effective-config getters — the client and scheduler read from these so that
# UI-managed settings win, with site_config / hardcoded values as fallbacks.
# ---------------------------------------------------------------------------

def get_api_key():
    """Return the effective USDA API key.

    Precedence:
    1. USDA Settings.api_key (Password field, encrypted at rest)
    2. site_config.json "usda_api_key" (legacy / fallback)
    3. None (client should log a "no key configured" error)
    """
    key = None
    try:
        settings = frappe.get_single("USDA Settings")
        key = settings.get_password("api_key", raise_exception=False)
    except Exception:
        pass
    if not key:
        key = frappe.conf.get("usda_api_key")
    return key


def get_base_url():
    try:
        settings = frappe.get_single("USDA Settings")
        if settings.api_base_url:
            return settings.api_base_url
    except Exception:
        pass
    return "https://marsapi.ams.usda.gov/services/v1.2/reports"


def get_ttl_seconds():
    try:
        settings = frappe.get_single("USDA Settings")
        if settings.request_ttl_hours:
            return int(settings.request_ttl_hours) * 3600
    except Exception:
        pass
    return 6 * 3600


def get_timeout_seconds():
    try:
        settings = frappe.get_single("USDA Settings")
        if settings.request_timeout_seconds:
            return int(settings.request_timeout_seconds)
    except Exception:
        pass
    return 30


def record_pull_result(status: str, error_message: str = "", records_added: int = 0):
    """Called from the scheduler to update Status fields after a pull."""
    try:
        settings = frappe.get_single("USDA Settings")
        settings.last_pull_status = status
        settings.last_error_message = error_message[:1400] if error_message else ""
        if status == "success":
            settings.last_successful_pull = frappe.utils.now_datetime()
        settings.total_records_cached = frappe.db.count("USDA Market Price")
        settings.flags.ignore_permissions = True
        settings.save()
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(f"Failed to update USDA Settings status: {e}", "farm_precision_ag")


# ---------------------------------------------------------------------------
# Whitelisted endpoints
# ---------------------------------------------------------------------------

@frappe.whitelist()
def test_connection():
    """Make a lightweight request against the USDA API to verify the key.

    Uses the /reports endpoint which returns a list of available reports —
    a small, always-available response that proves auth + connectivity
    without pulling any commodity data.
    """
    import requests
    api_key = get_api_key()
    if not api_key:
        return {"ok": False, "message": "No USDA API key configured."}
    base = get_base_url()
    try:
        r = requests.get(base, auth=(api_key, ""), timeout=get_timeout_seconds())
        r.raise_for_status()
        # /reports returns a list of report metadata
        n = len(r.json()) if isinstance(r.json(), list) else "?"
        return {"ok": True, "message": f"API returned {n} available reports."}
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        if status == 401:
            return {"ok": False, "message": f"HTTP 401 — invalid API key."}
        return {"ok": False, "message": f"HTTP {status} — {e}"}
    except Exception as e:
        return {"ok": False, "message": f"Connection error: {e}"}
