// Relay Document Actions: "Send on WhatsApp" buttons on configured desk forms.
// Other desk code can open the same dialog: relay_core.send_document_dialog(doctype, name, action).
frappe.provide("relay_core");

relay_core.send_document_dialog = function (doctype, name, action) {
	frappe.call({
		method: "relay_core.api.preview_document",
		type: "GET",
		args: { doctype, name, action },
		freeze: true,
		freeze_message: __("Preparing message..."),
	}).then(({ message: preview }) => relay_core.show_send_dialog(doctype, name, preview));
};

relay_core.show_send_dialog = function (doctype, name, preview) {
	const options = preview.recipients.map((row) => ({
		label: `${row.name} (${row.numbers.length ? row.numbers.map((number) => "+" + number).join(", ") : __("no WhatsApp number")})`,
		value: row.contact,
		checked: row.numbers.length > 0,
	}));
	const request_key = frappe.utils.get_random(20);
	const dialog = new frappe.ui.Dialog({
		title: preview.label,
		fields: [
			{ fieldtype: "HTML", fieldname: "message" },
			{
				fieldtype: "MultiCheck",
				fieldname: "contacts",
				label: preview.all_numbers ? __("Contacts (every WhatsApp number)") : __("Contacts"),
				options,
				columns: 1,
			},
		],
		primary_action_label: __("Send"),
		primary_action(values) {
			if (!values.contacts?.length) {
				frappe.msgprint(__("Choose at least one contact."));
				return;
			}
			dialog.disable_primary_action();
			frappe.call({
				method: "relay_core.api.send_document",
				args: { doctype, name, action: preview.action, contacts: values.contacts, request_key },
				freeze: true,
				freeze_message: __("Sending..."),
			})
				.then(({ message }) => {
					dialog.hide();
					relay_core.show_send_results(message.results);
				})
				.always(() => dialog.enable_primary_action());
		},
	});
	const file = preview.file_name
		? `<p class="text-muted small">${__("PDF")}: ${frappe.utils.escape_html(preview.file_name)}</p>`
		: "";
	dialog.fields_dict.message.$wrapper.html(
		`<p class="text-muted small">${__("Template")}: ${frappe.utils.escape_html(preview.template)}</p>
		<div class="border rounded p-3 mb-3" style="white-space: pre-wrap">${frappe.utils.escape_html(preview.text)}</div>${file}`,
	);
	dialog.show();
};

relay_core.show_send_results = function (results) {
	const sent = results.filter((row) => ["Submitted", "Queued"].includes(row.status));
	const failed = results.filter((row) => !sent.includes(row));
	if (!failed.length) {
		frappe.show_alert({ message: __("Sent to {0} WhatsApp number(s)", [sent.length]), indicator: "green" });
		return;
	}
	const lines = failed.map((row) => `${frappe.utils.escape_html(row.contact)}: ${frappe.utils.escape_html(row.error || row.status)}`);
	frappe.msgprint({
		title: __("Sent to {0}, not sent to {1}", [sent.length, failed.length]),
		message: lines.join("<br>"),
		indicator: sent.length ? "orange" : "red",
	});
};

// Desk sets frappe.boot before app scripts load, so the handlers exist before any form opens.
Object.entries(frappe.boot?.relay_document_actions || {}).forEach(([doctype, actions]) => {
	frappe.ui.form.on(doctype, {
		refresh(frm) {
			if (frm.is_new()) return;
			actions.forEach((action) =>
				frm.add_custom_button(__(action.label), () =>
					relay_core.send_document_dialog(frm.doctype, frm.doc.name, action.name),
				),
			);
		},
	});
});
