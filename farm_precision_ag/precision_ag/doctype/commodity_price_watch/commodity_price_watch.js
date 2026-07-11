// Commodity Price Watch — client script.
//
// Adds a "Generate Charts" button (Actions menu) that stamps out the standard
// Dashboard Chart + Number Card set for this commodity via the chart factory.
// Charts also auto-generate on insert (server-side after_insert hook), so this
// button is mainly for re-generating after edits or if the auto-run was skipped.

frappe.ui.form.on("Commodity Price Watch", {
	refresh: function (frm) {
		if (frm.is_new()) {
			return;
		}
		frm.add_custom_button(
			__("Generate Charts"),
			function () {
				frappe.confirm(
					__(
						"Create 4 Dashboard Charts + 2 Number Cards for this commodity? Existing ones with the same names will be replaced."
					),
					function () {
						frappe.call({
							method: "farm_precision_ag.utils.chart_factory.generate_charts_api",
							args: { watch_name: frm.doc.name, force_recreate: 1 },
							freeze: true,
							freeze_message: __("Generating charts…"),
							callback: function (r) {
								const m = r.message || {};
								const created =
									(m.created_charts || []).length +
									(m.created_cards || []).length;
								const errors = (m.errors || []).length;
								frappe.msgprint({
									title: __("Charts Generated"),
									message: __("Created {0} item(s). {1} error(s).", [
										created,
										errors,
									]),
									indicator: errors ? "orange" : "green",
								});
							},
						});
					}
				);
			},
			__("Actions")
		);
	},
});
