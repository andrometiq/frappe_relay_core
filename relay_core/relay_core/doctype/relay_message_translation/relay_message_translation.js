frappe.ui.form.on('Relay Message Translation', {
  refresh(frm) {
    if (frm.doc.status === 'Failed' && frappe.user.has_role('System Manager')) {
      frm.add_custom_button(__('Retry translation'), async () => {
        const result = await frappe.call({method:'relay_core.translations.retry', args:{name:frm.doc.name}, freeze:true});
        if (result.message.name !== frm.doc.name) frappe.set_route('Form','Relay Message Translation',result.message.name);
        else await frm.reload_doc();
      });
    }
  }
});
