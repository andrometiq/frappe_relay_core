"""Local script hints. The model resolves languages sharing a script from the latest text."""
import unicodedata
from collections import Counter

SCRIPTS = {'MALAYALAM': 'Malayalam', 'DEVANAGARI': 'Hindi', 'TAMIL': 'Tamil',
           'BENGALI': 'Bengali', 'TELUGU': 'Telugu', 'KANNADA': 'Kannada',
           'GUJARATI': 'Gujarati', 'GURMUKHI': 'Punjabi', 'ARABIC': 'Arabic',
           'CYRILLIC': 'Cyrillic', 'THAI': 'Thai', 'HANGUL': 'Korean',
           'HIRAGANA': 'Japanese', 'KATAKANA': 'Japanese', 'CJK': 'Chinese', 'LATIN': 'English'}


def detect(text):
    counts = Counter()
    for char in str(text or ''):
        if char.isalpha():
            script = unicodedata.name(char, '').split(' ')[0]
            if script in SCRIPTS:
                counts[script] += 1
    if not counts:
        return {'language': 'undetermined', 'script': None}
    script = counts.most_common(1)[0][0]
    return {'language': SCRIPTS[script], 'script': script}


def matches(text, expected):
    """Check dominant script, not vocabulary; Latin/Devanagari do not identify one language."""
    script = expected.get('script')
    return not script or detect(text)['script'] == script


def incoming(message):
    if message.get('message_type') in ('audio', 'voice'):
        transcript = message.get('transcript')
        if not isinstance(transcript, str) or not transcript.strip():
            raise ValueError('Voice message needs staff review: no transcript is available; AI cannot infer its contents')
        return transcript.strip()
    return message.get('content') or ''


def instruction(text):
    hint = detect(text)
    return ('Reply in the language and script of the latest customer message or voice transcript, '
            'not earlier history or the language of reference material. '
            f"Local hint: {hint['language']} / {hint['script'] or 'unknown'}. "
            'Resolve shared scripts from the text (Latin is not necessarily English; Devanagari may be Marathi). '
            'Preserve names, identifiers and amounts exactly. If language is unclear, ask briefly.')


NOTICES = {
    'handoff': {
        'Malayalam': 'അറിയിച്ചതിന് നന്ദി. ഞങ്ങളുടെ ടീമിലെ ഒരാൾ നിങ്ങളെ സഹായിക്കാൻ ബന്ധപ്പെടും.',
        'Hindi': 'बताने के लिए धन्यवाद। हमारी टीम का एक सदस्य आपकी मदद के लिए संपर्क करेगा।',
        'Tamil': 'தகவலுக்கு நன்றி. எங்கள் குழுவில் ஒருவர் உங்களுக்கு உதவ தொடர்பு கொள்வார்.',
    },
    'decline': {
        'Malayalam': 'ക്ഷമിക്കണം, നിങ്ങളുടെ സ്വന്തം രേഖകളും ഉപഭോക്താക്കൾക്കുള്ള വിവരങ്ങളും സംബന്ധിച്ച ബിസിനസ് ചോദ്യങ്ങളിൽ മാത്രമേ സഹായിക്കാനാകൂ.',
        'Hindi': 'क्षमा करें, मैं केवल आपके अपने रिकॉर्ड और ग्राहकों के लिए उपलब्ध जानकारी से जुड़े व्यावसायिक प्रश्नों में मदद कर सकता हूँ।',
        'Tamil': 'மன்னிக்கவும், உங்கள் சொந்த பதிவுகள் மற்றும் வாடிக்கையாளர்களுக்கான தகவல்கள் தொடர்பான வணிகக் கேள்விகளுக்கு மட்டுமே உதவ முடியும்.',
    },
}


def notice(kind, text, fallback):
    return NOTICES[kind].get(detect(text)['language'], fallback)


def message_notice(kind, message, fallback):
    # With no transcript there is no language evidence; do not guess from audio metadata.
    return notice(kind, message.get('transcript') or message.get('content') or '', fallback)
