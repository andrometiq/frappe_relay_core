"""Ledger arithmetic and outbound presentation are code-owned, never model-generated."""
from decimal import Decimal


def summarize(rows, truncated):
    def amount(value):
        number = Decimal(str(value or 0))
        if not number.is_finite():
            raise ValueError('Invalid ledger amount')
        return number
    companies = {row.get('company') for row in rows}
    if len(companies) > 1 or any(not company for company in companies):
        raise ValueError('Choose one company before totaling ledger entries')
    debit = sum((amount(row['debit']) for row in rows), Decimal(0))
    credit = sum((amount(row['credit']) for row in rows), Decimal(0))
    return {'rows': rows, 'totals': {'debit': str(debit), 'credit': str(credit), 'net_debit': str(debit - credit)},
        'truncated': truncated,
        'note': ('Partial totals: more rows match. Choose a narrower date range or ask for a person.' if truncated else
                 'Totals cover returned rows only; they are not an opening or closing balance.')}


def reply(result, *, language='English', business_type='Supplier'):
    totals = result['totals']
    labels = {
        'Malayalam': ('ലെഡ്ജർ', 'രേഖകൾ', 'ഡെബിറ്റ്', 'ക്രെഡിറ്റ്', 'ആകെ ഡെബിറ്റ്',
            'കാണിച്ച രേഖകളുടെ ആകെ തുക മാത്രം; ആരംഭ അല്ലെങ്കിൽ അവസാന ബാലൻസ് അല്ല.',
            'ഭാഗിക തുകകൾ മാത്രം. കൂടുതൽ രേഖകളുണ്ട്; ചെറിയ തീയതി പരിധി നൽകുക അല്ലെങ്കിൽ ജീവനക്കാരന്റെ സഹായം തേടുക.'),
        'Hindi': ('खाता विवरण', 'रिकॉर्ड', 'डेबिट', 'क्रेडिट', 'शुद्ध डेबिट',
            'कुल केवल दिखाए गए रिकॉर्ड का है; यह प्रारंभिक या अंतिम शेष नहीं है।',
            'आंशिक कुल। अधिक रिकॉर्ड हैं; छोटी तारीख सीमा दें या कर्मचारी की मदद लें।'),
        'Tamil': ('கணக்கு விவரம்', 'பதிவுகள்', 'பற்று', 'வரவு', 'நிகர பற்று',
            'மொத்தம் காட்டப்பட்ட பதிவுகளுக்கு மட்டுமே; தொடக்க அல்லது இறுதி இருப்பு அல்ல.',
            'பகுதி மொத்தம். மேலும் பதிவுகள் உள்ளன; குறுகிய தேதி வரம்பைக் கொடுக்கவும் அல்லது ஊழியரின் உதவியை நாடவும்.'),
    }.get(language, (business_type + ' ledger', 'returned rows', 'Debit', 'Credit', 'Net debit',
        'Totals cover returned rows only; they are not an opening or closing balance.',
        'Partial totals: more rows match. Choose a narrower date range or ask for a person.'))
    title, count, debit, credit, net, full, partial = labels
    lines = [f"{title} — {len(result['rows'])} {count}.",
        f"{debit}: {totals['debit']}; {credit}: {totals['credit']}; {net}: {totals['net_debit']}.",
        partial if result['truncated'] else full]
    for row in result['rows']:
        line = f"{row.get('posting_date')} · {row.get('voucher_type')} {row.get('voucher_no')} · {debit} {row['debit']}, {credit} {row['credit']} · {row.get('remarks') or ''}"
        if len('\n'.join(lines)) + len(line) > 1850:
            lines.append(partial if language != 'English' else 'More returned details are omitted from this message. Ask for a narrower range or a person.')
            break
        lines.append(line)
    return '\n'.join(lines)
