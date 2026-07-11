frappe.ui.form.on('USDA Settings', {
    refresh: function(frm) {
        frm.add_custom_button('Test Connection', function() {
            frappe.call({
                method: 'farm_precision_ag.precision_ag.doctype.usda_settings.usda_settings.test_connection',
                callback: function(r) {
                    if (r.message && r.message.ok) {
                        frappe.msgprint({
                            title: 'Success',
                            message: `Connected to USDA MARS. ${r.message.message}`,
                            indicator: 'green',
                        });
                    } else {
                        frappe.msgprint({
                            title: 'Connection Failed',
                            message: r.message ? r.message.message : 'Unknown error',
                            indicator: 'red',
                        });
                    }
                },
            });
        }, 'Actions');
    },
});
