frappe.ui.form.on('Relay Settings', {
 refresh(frm) {
    frm.page.wrapper.addClass('relay-desk-form');
    frappe.require('/assets/relay_core/css/desk_forms.css');
  frm.add_custom_button(__('Verify Hub connection'), async () => {
   if (frm.is_dirty()) { frappe.msgprint(__('Save your settings before verifying the connection.')); return; }
   await frappe.call({method:'relay_core.settings.verify_connection',freeze:true,freeze_message:__('Verifying Hub connection…')});
   frappe.show_alert({message:__('Hub account and site verified'),indicator:'green'});
  });
 }
});
