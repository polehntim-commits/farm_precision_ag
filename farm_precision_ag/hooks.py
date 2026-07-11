app_name = "farm_precision_ag"
app_title = "Farm Precision Ag"
app_publisher = "Polehn Farm"
app_description = (
    "Precision agriculture module for ERPNext — "
    "Land/Blocks/Implements/Spray/USDA pricing/Attestations/Costing. "
    "Phase B: USDA Market Pricing."
)
app_email = "polehntim@gmail.com"
app_license = "MIT"
app_version = "0.1.0"

# Ship the workspace's generic "Prices Fetched Today" Number Card so the tile
# renders. Commodity-specific charts/cards are NOT shipped as fixtures — they're
# generated per Commodity Price Watch by the chart factory (see doc_events).
fixtures = [
    {"dt": "Number Card", "filters": [["name", "in", ["Prices Fetched Today"]]]},
]

# ---------------------------------------------------------------------------
# doc_events: chart factory.
#
# Every Commodity Price Watch gets its own set of 4 Dashboard Charts + 2 Number
# Cards, generated on insert and cleaned up on delete. The handlers fail soft
# (log_error, never raise) so a factory hiccup can't block a Watch save/delete.
# ---------------------------------------------------------------------------
doc_events = {
    "Commodity Price Watch": {
        "after_insert": "farm_precision_ag.utils.chart_factory._auto_generate_after_insert",
        "on_trash": "farm_precision_ag.utils.chart_factory._auto_cleanup_before_trash",
    },
}

# ---------------------------------------------------------------------------
# Scheduler events
#
# NOTE ON PATHS: `tasks.py` and `utils/` sit at the Python package root
# (`farm_precision_ag/tasks.py`, `farm_precision_ag/utils/...`), NOT inside the
# nested `farm_precision_ag/precision_ag/` module dir which is reserved for
# DocType folders. So the dotted paths here are `farm_precision_ag.tasks.*`.
# ---------------------------------------------------------------------------
scheduler_events = {
    "daily": [
        "farm_precision_ag.tasks.pull_usda_prices",
    ],
}

# ---------------------------------------------------------------------------
# after_migrate: keep the Precision Ag workspace authoritative from JSON.
#
# Frappe preserves existing DB Workspace records as "customized" and skips
# re-importing the app's workspace JSON, so shortcuts/number cards added to the
# JSON in a later release never appear. We delete-and-reimport the workspace on
# every migrate so the JSON always wins. Mirrors the farm_i9 pattern.
# ---------------------------------------------------------------------------
after_migrate = [
    "farm_precision_ag.utils.workspace_sync.refresh_precision_ag_workspace",
]
