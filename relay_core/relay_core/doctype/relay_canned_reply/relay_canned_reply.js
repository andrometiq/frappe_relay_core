frappe.ui.form.on('Relay Canned Reply', {
  async refresh(frm) {
    frm.page.wrapper.addClass('relay-desk-form');
    frappe.require('/assets/relay_core/css/desk_forms.css');
    frm.set_df_property('action_key', 'description', __('Enter the action ID supplied by your administrator. It runs only when staff choose the action in the saved reply picker.'));
    if (!frappe.user.has_role('System Manager')) return;
    frm.add_custom_button(__('Choose business action'), async () => {
      const {message: actions} = await frappe.call('relay_core.saved_reply_actions.catalog');
      if (!actions?.length) { frappe.msgprint(__('No saved reply actions are registered by installed apps.')); return; }
      const dialog = new frappe.ui.Dialog({
        title: __('Choose business action'),
        fields: [{fieldname:'action',label:__('Action'),fieldtype:'Select',reqd:1,
          options:actions.map(row=>({label:row.label,value:row.key}))}],
        primary_action_label: __('Select'),
        primary_action(values) {
          frm.set_value('action_key',values.action);
          dialog.hide();
          const action=actions.find(row=>row.key===values.action);
          frappe.msgprint({title:__('Action input schema'),message:'<pre>'+frappe.utils.escape_html(JSON.stringify(action.parameters,null,2))+'</pre>'});
        }
      });
      dialog.show();
    });
  }
});
