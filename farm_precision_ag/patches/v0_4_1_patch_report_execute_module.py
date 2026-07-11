def execute():
    """Install the Report.execute_module list-filter normalizer on migrate.

    The patch is also wired into boot_session (active from the first /desk
    request), but running it here guarantees it's installed even in code paths
    that trigger a Script Report before any interactive session boots (e.g. a
    scheduled dashboard refresh right after `bench migrate`). The underlying
    function is idempotent — guarded by `Report._farm_precision_ag_patched` —
    so re-running on every migrate is a harmless no-op after the first call.

    See `farm_precision_ag.utils.patches.patch_report_execute_module` for the
    full rationale (Dashboard/Script-Report co-render ValueError crash).
    """
    from farm_precision_ag.utils.patches import patch_report_execute_module

    patch_report_execute_module()
