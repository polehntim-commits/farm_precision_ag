"""Scheduler entry points for farm_precision_ag.

Phase B keeps this minimal: a single daily pull of USDA market prices for every
active Commodity Price Watch. The heavy lifting lives in
``farm_precision_ag.utils.usda_scheduler`` so this module stays a thin,
hooks-wired shim.
"""


def pull_usda_prices():
    """Daily pull of USDA prices for all active Commodity Price Watches."""
    from farm_precision_ag.utils.usda_scheduler import run_daily_pull

    run_daily_pull()
