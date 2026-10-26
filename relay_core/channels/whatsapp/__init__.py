"""WhatsApp channel."""
from relay_core.channels.contract import Channel

AUDIO = ['audio/mpeg', 'audio/mp4', 'audio/ogg', 'audio/aac']
DOCUMENTS = [
    'application/pdf', 'text/plain', 'application/msword', 'application/vnd.ms-excel', 'application/vnd.ms-powerpoint',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
]


class WhatsApp(Channel):
    name = 'WhatsApp'
    features = {
        'text': True, 'max_text_length': 4096, 'max_caption_length': 1024,
        'media': {'photo': ['image/jpeg', 'image/png'], 'video': ['video/mp4'], 'audio': AUDIO,
                  'voice': AUDIO, 'document': DOCUMENTS, 'sticker': ['image/webp']},
        'location': True, 'contacts': True, 'reply_quote': True, 'reactions': True, 'edits': False,
        'read_receipts': True, 'group_receipts': True,
        'templates': True, 'reply_window_hours': 24, 'bulk_campaigns': True, 'forms': True, 'voice_calls': True,
        'groups': True, 'topics': False, 'email_threading': False, 'ai_automation': True, 'saved_replies': True,
    }
    account_flags = {'templates': 'templates', 'forms': 'flows'}

    def get_account_flags(self) -> dict:
        import frappe
        from relay_core.hub import HubError
        from relay_core.whatsapp import checked_client
        try:
            return checked_client()[1]
        except (HubError, ValueError, frappe.ValidationError):
            # An unconfigured or unreachable account only switches the account features off.
            return {}
