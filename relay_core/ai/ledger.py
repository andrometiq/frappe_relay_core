"""Ledger arithmetic and outbound presentation are code-owned, never model-generated."""
from decimal import Decimal

MAX_LENGTH = 1850
LABELS = {
    'Malayalam': ('ലെഡ്ജർ', 'രേഖകൾ', 'ഡെബിറ്റ്', 'ക്രെഡിറ്റ്', 'ആകെ ഡെബിറ്റ്',
        'കാണിച്ച രേഖകളുടെ ആകെ തുക മാത്രം; ആരംഭ അല്ലെങ്കിൽ അവസാന ബാലൻസ് അല്ല.',
        'ഭാഗിക തുകകൾ മാത്രം. കൂടുതൽ രേഖകളുണ്ട്; ചെറിയ തീയതി പരിധി നൽകുക അല്ലെങ്കിൽ ജീവനക്കാരന്റെ സഹായം തേടുക.'),
    'Hindi': ('खाता विवरण', 'रिकॉर्ड', 'डेबिट', 'क्रेडिट', 'शुद्ध डेबिट',
        'कुल केवल दिखाए गए रिकॉर्ड का है; यह प्रारंभिक या अंतिम शेष नहीं है।',
        'आंशिक कुल। अधिक रिकॉर्ड हैं; छोटी तारीख सीमा दें या कर्मचारी की मदद लें।'),
    'Tamil': ('கணக்கு விவரம்', 'பதிவுகள்', 'பற்று', 'வரவு', 'நிகர பற்று',
        'மொத்தம் காட்டப்பட்ட பதிவுகளுக்கு மட்டுமே; தொடக்க அல்லது இறுதி இருப்பு அல்ல.',
        'பகுதி மொத்தம். மேலும் பதிவுகள் உள்ளன; குறுகிய தேதி வரம்பைக் கொடுக்கவும் அல்லது ஊழியரின் உதவியை நாடவும்.'),
}
FULL = 'Totals cover returned rows only; they are not an opening or closing balance.'
PARTIAL = 'Partial totals: more rows match. Choose a narrower date range or ask for a person.'
OMITTED = 'More returned details are omitted from this message. Ask for a narrower range or a person.'


def totals(rows: list[dict]) -> dict:
    def amount(value):
        number = Decimal(str(value or 0))
        if not number.is_finite():
            raise ValueError('Invalid ledger amount')
        return number
    debit = sum((amount(row['debit']) for row in rows), Decimal(0))
    credit = sum((amount(row['credit']) for row in rows), Decimal(0))
    return {'debit': str(debit), 'credit': str(credit), 'net_debit': str(debit - credit)}


def render(rows: list[dict], language: str, truncated: bool, business_type: str = 'Customer') -> str:
    """Totals and one line per entry. Remarks appear only when the pack shows them to the customer."""
    title, count, debit, credit, net, full, partial = LABELS.get(language, (
        business_type + ' ledger', 'returned rows', 'Debit', 'Credit', 'Net debit', FULL, PARTIAL))
    amounts = totals(rows)
    omitted = OMITTED if language not in LABELS else partial
    lines = [f'{title} — {len(rows)} {count}.',
        f"{debit}: {amounts['debit']}; {credit}: {amounts['credit']}; {net}: {amounts['net_debit']}.",
        partial if truncated else full]
    for row in rows:
        line = f"{row.get('posting_date')} · {row.get('voucher_type')} {row.get('voucher_no')} · {debit} {row['debit']}, {credit} {row['credit']}"
        if 'remarks' in row:
            line += f" · {row['remarks'] or ''}"
        if len('\n'.join([*lines, line, omitted])) > MAX_LENGTH:
            lines.append(omitted)
            break
        lines.append(line)
    return '\n'.join(lines)


def supplier(rows: list[dict], language: str, truncated: bool) -> str:
    return render(rows, language, truncated, 'Supplier')
