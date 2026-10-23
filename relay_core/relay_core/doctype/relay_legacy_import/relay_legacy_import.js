frappe.ui.form.on('Relay Legacy Import', {
 async source_bundle(frm) {
  if(!frm.doc.source_bundle)return;
  const {message:r}=await frappe.call({method:'relay_core.legacy_bundle.details',args:{file:frm.doc.source_bundle}});
  frm.set_value('source_conversation',r.source_conversation);
 },
 refresh(frm) {
  if (frm.is_new()) return;
  frm.add_custom_button(__('Preview next batch'), async () => {
   if(frm.is_dirty()) {frappe.msgprint(__('Save the mapping first.'));return;}
   const {message:r}=await frappe.call({method:'relay_core.legacy.preview',args:{name:frm.doc.name},freeze:true});
   frappe.msgprint({title:__('Legacy history preview'),message:__('Next batch: {0} messages. {1} supported local attachments. {2} messages need review.',[r.messages,r.local_attachments,r.review_required])});
  });
  if(frm.doc.status!=='Completed') frm.add_custom_button(__('Import next 50 messages'), async () => {
   if(frm.is_dirty()) {frappe.msgprint(__('Save the mapping first.'));return;}
   await frappe.call({method:'relay_core.legacy.run_batch',args:{name:frm.doc.name},freeze:true,freeze_message:__('Importing history…')});
   await frm.reload_doc();
  });
 }
});
