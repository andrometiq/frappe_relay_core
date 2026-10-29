frappe.ui.form.on("Relay Contact Type", {
    refresh(frm) {
        if (!frm.doc.business_doctype) return;
        frappe.model.with_doctype(frm.doc.business_doctype, () => {
            const fields = (frappe.get_meta(frm.doc.business_doctype).fields || [])
                .filter(field => ["Link", "Select", "Data"].includes(field.fieldtype) && !field.hidden && !field.permlevel)
                .map(field => field.fieldname);
            frm.set_df_property("grouping_fields", "description", __("Available fields: {0}", [fields.join(", ")]));
        });
    },
    business_doctype(frm) { frm.trigger("refresh"); },
});
