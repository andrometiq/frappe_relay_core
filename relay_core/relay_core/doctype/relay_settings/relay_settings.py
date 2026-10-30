import re
import frappe
from frappe.model.document import Document
from relay_core.permissions import require_access
from relay_core.hub import HubClient

class RelaySettings(Document):
    def validate(self):
        require_access(configure=True)
        previous = self.get_doc_before_save()
        if previous and not self.get('enable_ai_features'):
            fields = ('ai_handoff_owner', 'transcription_provider', 'memory_model',
                      'event_memory_model', 'max_ai_file_size_mb')
            if any(self.get(field) != previous.get(field) for field in fields):
                frappe.throw('Enable AI features before changing AI settings', frappe.PermissionError)
        if self.hub_url:
            HubClient(self.hub_url,'validation-only-placeholder-token-32-characters')

        if self.hub_account and not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',self.hub_account):
            frappe.throw('Hub account must contain 1–100 letters, numbers, underscores or hyphens')
        for field,maximum in (('hub_token',4096),('callback_secret',512)):
            value=self.get(field)
            if value and not set(value)=={'*'} and (not 32<=len(value)<=maximum or any(ord(c)<32 for c in value)):
                frappe.throw('Credentials must contain at least 32 printable characters')
        if not 0 <= (self.whatsapp_margin_percent or 0) <= 1000:
            frappe.throw('WhatsApp margin percent must be between 0 and 1000')
        if self.transcription_provider:
            provider=frappe.get_doc('Relay AI Provider',self.transcription_provider)
            if provider.provider!='OpenAI' or not provider.enabled:
                frappe.throw('Voice transcription requires an enabled OpenAI provider with a transcription model')

    def on_update(self):
        from relay_core.whatsapp import clear_hub_capabilities
        clear_hub_capabilities()
