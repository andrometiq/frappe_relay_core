frappe.ui.form.on("Relay Contact Type", {
	setup(frm) {
		frm.trigger("load_grouping_fields");
	},

	refresh(frm) {
		frm.trigger("load_grouping_fields");
	},

	business_doctype(frm) {
		if (frm.doc.grouping_field) {
			frm.set_value("grouping_field", "");
		}
		frm.trigger("load_grouping_fields");
	},

	load_grouping_fields(frm) {
		const control = frm.fields_dict.grouping_field;
		if (!control) return;

		if (!frm.doc.business_doctype) {
			control.set_data([]);
			frm.set_df_property("grouping_field", "read_only", 1);
			return;
		}

		frappe.model.with_doctype(frm.doc.business_doctype, () => {
			const fields = (frappe.get_meta(frm.doc.business_doctype).fields || [])
				.filter(
					(field) =>
						field.fieldname &&
						["Link", "Select", "Data"].includes(field.fieldtype) &&
						!field.permlevel &&
						!field.hidden,
				)
				.map((field) => ({
					label: __(field.label || field.fieldname),
					value: field.fieldname,
					description: field.fieldname,
				}));

			control.set_data(fields);
			frm.set_df_property("grouping_field", "read_only", 0);
			control.refresh();
		});
	},
});
