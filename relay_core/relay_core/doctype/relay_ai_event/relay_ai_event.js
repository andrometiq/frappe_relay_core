frappe.ui.form.on("Relay AI Event", {
	setup(frm) {
		frm.set_query("business_doctype", "audience", () => ({ filters: { enabled: 1 } }));
	},

	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Rebuild memory"), () =>
			frappe
				.xcall("relay_core.ai.event_memory.rebuild", { event: frm.doc.name })
				.then(() => frm.reload_doc()),
		);
	},
});
