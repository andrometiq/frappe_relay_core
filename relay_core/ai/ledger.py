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


def reply(result):
    totals = result['totals']
    lines = [f"Supplier ledger — {len(result['rows'])} returned rows.",
        f"Debit: {totals['debit']}; Credit: {totals['credit']}; Net debit: {totals['net_debit']}.", result['note']]
    for row in result['rows']:
        line = f"{row.get('posting_date')} · {row.get('voucher_type')} {row.get('voucher_no')} · debit {row['debit']}, credit {row['credit']} · {row.get('remarks') or ''}"
        if len('\n'.join(lines)) + len(line) > 1850:
            lines.append('More returned details are omitted from this message. Ask for a narrower range or a person.')
            break
        lines.append(line)
    return '\n'.join(lines)
