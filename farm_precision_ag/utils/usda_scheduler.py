"""Scheduled USDA price pull — Frappe port.

Ported from the Farm App's ``usda_price_scheduler.py``. The Farm App ran its own
threaded 7 AM loop; under Frappe the cadence is owned by the bench scheduler
(declared in ``hooks.py`` as a ``daily`` event), so this module is just the
work that runs each day. TTL caching (skip if a watch was fetched < 6h ago)
lives in ``usda_client.should_refresh_watch``.
"""

import frappe

from farm_precision_ag.utils.usda_client import get_api_key, refresh_all_active_watches


def run_daily_pull() -> dict:
    """Pull USDA prices for every active Commodity Price Watch.

    Invoked by ``farm_precision_ag.tasks.pull_usda_prices`` (the ``daily``
    scheduler hook) and safe to run manually via::

        bench --site <site> execute farm_precision_ag.tasks.pull_usda_prices

    Returns a small summary dict for logging / manual runs.
    """
    if not get_api_key():
        frappe.logger("farm_precision_ag").info(
            "USDA daily pull skipped — no usda_api_key configured in site config."
        )
        return {"status": "skipped", "reason": "no_api_key", "watches": 0, "stored": 0}

    summaries = refresh_all_active_watches()

    stored = sum(s.get("stored", 0) for s in summaries if not s.get("error"))
    errors = [s for s in summaries if s.get("error")]
    frappe.logger("farm_precision_ag").info(
        f"USDA daily pull done: {len(summaries)} watch(es), "
        f"{stored} price(s) stored, {len(errors)} error(s)."
    )
    return {
        "status": "ok",
        "watches": len(summaries),
        "stored": stored,
        "errors": len(errors),
        "summaries": summaries,
    }
