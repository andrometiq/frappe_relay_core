const PROFILE_FIELDTYPES = ["Data", "Link", "Select", "Int", "Float", "Currency", "Date", "Datetime", "Check", "Small Text", "Phone"];

frappe.ui.form.on("Relay Contact Type", {
    refresh(frm) {
        if (!frm.doc.business_doctype) return;
        frappe.model.with_doctype(frm.doc.business_doctype, () => {
            const fields = (frappe.get_meta(frm.doc.business_doctype).fields || [])
                .filter(field => ["Link", "Select", "Data"].includes(field.fieldtype) && !field.hidden && !field.permlevel)
                .map(field => field.fieldname);
            frm.set_df_property("grouping_fields", "description", __("Available fields: {0}", [fields.join(", ")]));
            const profile = (frappe.get_meta(frm.doc.business_doctype).fields || [])
                .filter(field => PROFILE_FIELDTYPES.includes(field.fieldtype) && !field.hidden && !field.permlevel)
                .map(field => field.fieldname);
            frm.set_df_property("profile_fields", "description", __("At most 12, shown in row order. Available fields: {0}", [profile.join(", ")]));
        });
    },
    business_doctype(frm) { frm.trigger("refresh"); },
});
