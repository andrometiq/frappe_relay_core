"""Email channel."""
from relay_core.channels.contract import ANY_FILE, Channel


class Email(Channel):
    name = 'Email'
    features = {
        'text': True, 'max_text_length': 100000, 'max_caption_length': None,
        'media': {'document': [ANY_FILE]}, 'max_media_bytes': None,
        'location': False, 'contacts': False, 'reply_quote': True, 'reactions': False, 'edits': False,
        'read_receipts': False, 'group_receipts': False,
        'templates': False, 'reply_window_hours': None, 'bulk_campaigns': False, 'forms': False, 'voice_calls': False,
        'groups': False, 'topics': False, 'email_threading': True, 'ai_automation': True, 'saved_replies': False,
    }
