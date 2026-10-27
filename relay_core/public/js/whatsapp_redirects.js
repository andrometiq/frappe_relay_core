// The old WhatsApp Core flow builder desk page opens the Relay flow builder once WhatsApp Core is off.
frappe.router.on('change', () => {
  if (frappe.boot.relay_whatsapp_redirect && frappe.get_route()[0] === 'whatsapp-flow-builder') {
    window.location.replace('/relay#/flows')
  }
})
