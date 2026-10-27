import frappe
from frappe.model.document import Document
from relay_core.permissions import require_access, can_manage


class InternalRecord(Document):
    def validate(self):
        if not getattr(frappe.flags, 'relay_automation_internal', False):
            frappe.throw('Automation records are maintained by the execution service', frappe.PermissionError)


class CannedReply(Document):
    def validate(self):
        require_access(configure=True)
        from relay_core.saved_reply_actions import configured_action
        if self.get('action_key'):
            if self.channel not in ('Telegram','WhatsApp') or self.ai_enabled:
                frappe.throw('Saved reply actions require a chat channel and explicit operator execution')
            configured_action(self)
        kind = self.get('reply_type') or 'Text'
        if kind not in ('Text', 'Location', 'Contact'):
            frappe.throw('Choose a supported reply type')
        if kind != 'Text' and (self.channel not in ('Telegram', 'WhatsApp') or self.ai_enabled):
            frappe.throw('Structured replies require Telegram or WhatsApp and cannot be used as AI text replies')
        if kind == 'Text' and (not isinstance(self.body, str) or not 1 <= len(self.body.strip()) <= 2000):
            frappe.throw('Reply must contain 1–2000 characters')
        if kind == 'Location':
            from relay_core.message_types import location
            try:
                location({'latitude':self.latitude, 'longitude':self.longitude})
            except ValueError:
                frappe.throw('Enter valid latitude and longitude')
        if kind == 'Contact':
            import re
            if not isinstance(self.contact_name,str) or not self.contact_name.strip() or len(self.contact_name)>64:
                frappe.throw('Contact name must contain 1–64 characters')
            if not isinstance(self.phone,str) or not re.fullmatch(r'[+0-9 ()-]{1,32}',self.phone) or not any(c.isdigit() for c in self.phone):
                frappe.throw('Enter a valid contact phone number')
        if not self.language or len(self.language) > 40:
            frappe.throw('Reply language is required')


class AutomationPolicy(Document):
    def validate(self):
        require_access(configure=True)
        if self.execution_user in ('Administrator', 'Guest'):
            frappe.throw('Choose a dedicated non-administrator execution user')
        if 'System Manager' in frappe.get_roles(self.execution_user):
            frappe.throw('Execution user must not be a System Manager')
        if not frappe.db.get_value('User', self.execution_user, 'enabled'):
            frappe.throw('Execution user must be enabled')
        if not can_manage(self.execution_user):
            frappe.throw('Execution user needs Relay Communication Manager access')
        if not 1 <= int(self.daily_limit or 0) <= 1000:
            frappe.throw('Daily limit must be between 1 and 1000')
        if len(self.instructions or '') > 4000:
            frappe.throw('Instructions exceed 4000 characters')
        ids = (self.reply_ids or '').splitlines()
        if len(ids) > 20 or len(ids) != len(set(ids)):
            frappe.throw('Select at most 20 distinct replies')
        if self.fallback_reply and self.fallback_reply not in ids:
            frappe.throw('Fallback must be in the allowed reply list')
        if self.enabled and not self.get('ai_model'):
            frappe.throw('Choose an AI Model from frappe_tools')
        if self.get('allow_report'):
            frappe.throw('AI reports are unavailable; use a scoped read skill')
        if self.get('allow_voice'):
            if not self.get('transcription_provider'):
                frappe.throw('Choose a transcription provider for voice input')
            transcription=frappe.get_doc('Relay AI Provider',self.transcription_provider)
            if transcription.provider!='OpenAI':
                frappe.throw('Voice transcription requires an OpenAI provider with a transcription model')
        channel = frappe.get_doc('Relay Channel', self.channel)
        for name in ids:
            reply = frappe.get_doc('Relay Canned Reply', name)
            if not reply.published or not reply.ai_enabled or reply.channel != channel.channel:
                frappe.throw('Policy replies must be published, AI enabled and match the channel')
