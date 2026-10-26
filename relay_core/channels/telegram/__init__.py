"""Telegram channel."""
from relay_core.channels.contract import ANY_FILE, Channel


class Telegram(Channel):
    name = 'Telegram'
    features = {
        'text': True, 'max_text_length': 4096, 'max_caption_length': 1024,
        'media': {'photo': ['image/jpeg', 'image/png', 'image/webp'], 'video': ['video/mp4'],
                  'audio': ['audio/mpeg', 'audio/mp4'], 'voice': ['audio/ogg'], 'document': [ANY_FILE],
                  'sticker': ['image/webp']},
        'location': True, 'contacts': True, 'reply_quote': True, 'reactions': True, 'edits': False,
        'read_receipts': False, 'group_receipts': False,
        'templates': False, 'reply_window_hours': None, 'bulk_campaigns': False, 'forms': False, 'voice_calls': False,
        'groups': True, 'topics': True, 'email_threading': False, 'ai_automation': True, 'saved_replies': True,
    }
