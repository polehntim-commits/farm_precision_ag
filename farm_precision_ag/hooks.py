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

# Ship the workspace's Dashboard Charts + Number Cards so the tiles render.
# Filtered by name so `bench --site frontend export-fixtures --app
# farm_precision_ag` re-syncs cleanly if we edit these via the UI later.
fixtures = [
    {"dt": "Dashboard Chart", "filters": [["name", "in", [
        "USDA Cherries - Shipping Point by Size",
        "USDA Cherries - Shipping Point by Variety",
        "USDA Cherries - Terminal Market by Origin",
        "USDA Cherries - Weekly Average",
    ]]]},
    {"dt": "Number Card", "filters": [["name", "in", [
        "Prices Fetched Today",
        "USDA Cherries Latest Shipping Price",
        "USDA Records Cached",
    ]]]},
]

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
