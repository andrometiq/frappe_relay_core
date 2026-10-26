"""Streaming recipient sheets and WhatsApp template parameters for bulk campaigns."""
import csv
import re
from urllib.parse import urlsplit
from relay_core.identity import phone_number

PHONE_COLUMNS = ('phone', 'mobile', 'mobile no', 'mobile number', 'phone number', 'whatsapp', 'number')
MEDIA_FORMATS = ('IMAGE', 'VIDEO', 'DOCUMENT')
COMPONENTS = ('HEADER', 'BODY', 'FOOTER', 'BUTTONS')
BUTTONS = ('QUICK_REPLY', 'URL', 'PHONE_NUMBER', 'COPY_CODE')
MAX_ROWS = 100000
MAX_VALUE = 1024


def template_fields(template):
    """Fields a sheet row must supply, in Meta component order. Raises ValueError for parts campaigns cannot fill."""
    named = str(template.get('parameter_format') or 'POSITIONAL').upper() == 'NAMED'
    fields = []
    for component in template.get('components') or []:
        kind = str(component.get('type') or '').upper()
        text = component.get('text') or ''
        header = str(component.get('format') or 'TEXT').upper()
        if kind not in COMPONENTS:
            raise ValueError(f'Campaigns cannot send {kind.lower() or "unknown"} templates')
        if kind == 'HEADER' and header not in (*MEDIA_FORMATS, 'TEXT'):
            raise ValueError(f'Campaigns cannot send templates with a {header.lower()} header')
        if kind == 'HEADER' and header in MEDIA_FORMATS:
            fields.append({'key': 'header_media', 'label': 'Header ' + header.lower() + ' URL',
                           'component': 'header', 'media': header.lower()})
        elif kind in ('HEADER', 'BODY'):
            for variable in variables(text, named):
                fields.append({'key': f'{kind.lower()}:{variable}', 'label': f'{kind.capitalize()} value {variable}',
                               'component': kind.lower(), 'name': variable if named else None})
        elif kind == 'BUTTONS':
            fields.extend(button_fields(component.get('buttons') or []))
    return fields


def button_fields(buttons):
    fields = []
    for index, button in enumerate(buttons):
        kind = str(button.get('type') or '').upper()
        if kind not in BUTTONS:
            raise ValueError(f"Campaigns cannot send templates with {kind.replace('_', ' ') or 'unknown'} buttons")
        label = button.get('text') or 'Button'
        if kind == 'URL' and variables(button.get('url') or '', False):
            fields.append({'key': f'button:{index}', 'label': f'{label} link value', 'component': 'button', 'index': index})
        elif kind == 'COPY_CODE':
            fields.append({'key': f'button:{index}', 'label': f'{label} coupon code', 'component': 'button',
                           'index': index, 'sub_type': 'copy_code'})
    return fields


def variables(text, named):
    pattern = r'\{\{\s*([a-z][a-z0-9_]*)\s*\}\}' if named else r'\{\{\s*(\d+)\s*\}\}'
    found = []
    for value in re.findall(pattern, text):
        if value not in found:
            found.append(value)
    return found if named else sorted(found, key=int)


def build_components(fields, values):
    grouped, buttons = {}, []
    for field in fields:
        value = values[field['key']]
        if field['component'] == 'button':
            parameter = ({'type': 'coupon_code', 'coupon_code': value} if field.get('sub_type') == 'copy_code'
                         else {'type': 'text', 'text': value})
            buttons.append({'type': 'button', 'sub_type': field.get('sub_type') or 'url', 'index': str(field['index']),
                            'parameters': [parameter]})
            continue
        target = grouped.setdefault(field['component'], {'type': field['component'], 'parameters': []})
        if field.get('media'):
            target['parameters'].append({'type': field['media'], field['media']: {'link': value}})
        else:
            parameter = {'type': 'text', 'text': value}
            if field.get('name'):
                parameter['parameter_name'] = field['name']
            target['parameters'].append(parameter)
    return [*grouped.values(), *buttons]


def read_rows(path):
    """Yield (sheet row number, header -> text) without loading the workbook."""
    lower = path.lower()
    if lower.endswith('.csv'):
        with open(path, newline='', encoding='utf-8-sig') as handle:
            yield from labelled(csv.reader(handle))
    elif lower.endswith('.xlsx'):
        from openpyxl import load_workbook
        book = load_workbook(path, read_only=True, data_only=True)
        try:
            yield from labelled(book.worksheets[0].iter_rows(values_only=True))
        finally:
            book.close()
    else:
        raise ValueError('Upload a .xlsx or .csv file')


def labelled(source):
    header = None
    for number, raw in enumerate(source, start=1):
        cells = [text(value) for value in raw]
        if header is None:
            header = cells
            if not any(header) or len(set(filter(None, header))) != len([c for c in header if c]):
                raise ValueError('The first row must hold unique column names')
            continue
        if not any(cells):
            continue
        if number - 1 > MAX_ROWS:
            raise ValueError(f'A campaign supports at most {MAX_ROWS} rows')
        yield number, {column: cells[i] if i < len(cells) else '' for i, column in enumerate(header) if column}


def text(value):
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def columns(path, sample=5):
    rows = []
    header = []
    for _, row in read_rows(path):
        header = header or list(row)
        rows.append(row)
        if len(rows) >= sample:
            break
    return header, rows


def suggest(header, fields):
    """Phone column by name; named values by their column name; positional template values take the
    remaining columns left to right."""
    by_name = {column.lower(): column for column in header}
    mapping = {'phone': next((by_name[c] for c in PHONE_COLUMNS if c in by_name), ''), 'fields': {}, 'fixed': {}}
    positional = [field for field in fields if is_positional(field)]
    for field in fields:
        if field in positional:
            continue
        guess = (field.get('name') or field['key'].split(':')[-1]).lower() if field['key'] != 'header_media' else 'image'
        for candidate in (guess, field['label'].lower(), 'image url', 'media url', 'url'):
            if candidate in by_name:
                mapping['fields'][field['key']] = by_name[candidate]
                break
    used = {mapping['phone'], *mapping['fields'].values()}
    mapping['fields'].update(zip((field['key'] for field in positional), (c for c in header if c not in used)))
    return mapping


def is_positional(field):
    return field['component'] in ('header', 'body') and not field.get('media') and not field.get('name')


def check_mapping(mapping, header, fields):
    if not isinstance(mapping, dict) or set(mapping) - {'phone', 'fields', 'fixed', 'extra'}:
        raise ValueError('Invalid column mapping')
    extra = mapping.get('extra') or []
    if not isinstance(extra, list) or len(extra) > 10 or any(column not in header for column in extra):
        raise ValueError('Choose up to 10 extra columns from the file')
    columns_used, fixed = mapping.get('fields') or {}, mapping.get('fixed') or {}
    if not isinstance(columns_used, dict) or not isinstance(fixed, dict):
        raise ValueError('Invalid column mapping')
    if mapping.get('phone') not in header:
        raise ValueError('Choose the phone number column')
    keys = {field['key'] for field in fields}
    if set(columns_used) - keys or set(fixed) - keys:
        raise ValueError('Mapping names a value this template does not use')
    for key, column in columns_used.items():
        if column not in header:
            raise ValueError(f'Column {column} is not in the file')
    for field in fields:
        if field['key'] not in columns_used and not str(fixed.get(field['key']) or '').strip():
            raise ValueError(f"Choose a column or fixed value for {field['label']}")
        if field['key'] in fixed and field.get('media'):
            media_url(fixed[field['key']])
    return {'phone': mapping['phone'], 'fields': dict(columns_used), 'extra': list(dict.fromkeys(extra)),
            'fixed': {key: str(value).strip() for key, value in fixed.items() if key not in columns_used}}


def media_url(value):
    parts = urlsplit(value)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.fragment or len(value) > 2048:
        raise ValueError('Media needs an HTTPS link without credentials')
    return value


def prepare_row(row, mapping, fields, region):
    """Return (destination, values, problem). Problems are user-facing reasons."""
    destination = phone_number(row.get(mapping['phone']), region)
    if not destination:
        return None, None, 'Invalid phone number'
    values = {}
    for field in fields:
        column = mapping['fields'].get(field['key'])
        value = row.get(column, '') if column else mapping['fixed'].get(field['key'], '')
        if not value:
            return destination, None, f"Missing {field['label']}"
        if len(value) > MAX_VALUE:
            return destination, None, f"{field['label']} is too long"
        if field.get('media'):
            try:
                media_url(value)
            except ValueError:
                return destination, None, f"{field['label']} must be an HTTPS link"
        values[field['key']] = value
    extra = {column: row.get(column, '')[:MAX_VALUE] for column in mapping.get('extra', [])}
    return destination, {'values': values, **({'extra': extra} if extra else {})}, None
