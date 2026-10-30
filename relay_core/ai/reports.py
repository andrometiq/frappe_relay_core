"""Installed report contracts. No model SQL, Python, URLs or arbitrary MCP methods."""
LEDGER_FIELDS = ['name', 'company', 'posting_date', 'voucher_type', 'voucher_no', 'debit', 'credit', 'remarks']
REPORTS = {
    'customer_ledger': dict(label='Customer ledger', business_doctype='Customer'),
    'supplier_ledger': dict(label='Supplier ledger', business_doctype='Supplier'),
}


def validate(contract, business_doctype):
    report = REPORTS.get(contract.get('report'))
    if (not report or report['business_doctype'] != business_doctype
            or contract.get('method') != 'get_list' or contract.get('doctype') != 'GL Entry'
            or contract.get('fields') != LEDGER_FIELDS or contract.get('scope_field') != 'party'
            or contract.get('company_field') != 'company'):
        raise ValueError('Choose an installed report with its fixed fields and business scope')


def options(business_doctype):
    return [dict(value=key, label=row['label'], contract=dict(report=key, method='get_list',
        doctype='GL Entry', fields=LEDGER_FIELDS, scope_field='party', company_field='company'))
        for key, row in REPORTS.items() if row['business_doctype'] == business_doctype]
