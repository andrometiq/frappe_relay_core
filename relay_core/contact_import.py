"""Bounded contact spreadsheets; preview is read-only and apply revalidates the file."""
from contextlib import ExitStack
from io import BytesIO

import frappe
from relay_core.business_access import document_name
from relay_core import bulk_sheet, contacts, identity, locks

COLUMNS = ('Mobile', 'Email', 'Contact name', 'Business type', 'Business record')
MAX_ROWS = 2000


class RowProblem(ValueError):
    """A validation reason safe to display in the preview."""


def allowed(user=None, roles=None):
    return (user or frappe.session.user) == 'Administrator' or bool(
        {'Relay Communication Manager', 'System Manager'} & set(roles if roles is not None else frappe.get_roles()))


def require_manager():
    if not allowed():
        frappe.throw('Only communication managers can import or export contacts', frappe.PermissionError)
    contacts.require_access()


def source_rows(file_url):
    from relay_core.bulk_campaigns import uploaded_file
    if not isinstance(file_url, str) or not file_url.lower().endswith(('.xlsx', '.csv')):
        raise RowProblem('Choose an Excel (.xlsx) or CSV file.')
    file = uploaded_file(file_url)
    if file.file_size and file.file_size > 5 * 1024 * 1024:
        raise RowProblem('Choose a file smaller than 5 MB.')
    rows = []
    try:
        for number, values in bulk_sheet.read_rows(file.get_full_path()):
            if set(values) != set(COLUMNS):
                raise RowProblem('Use these columns: ' + ', '.join(COLUMNS) + '.')
            if len(rows) == MAX_ROWS:
                raise RowProblem('Import at most 2000 rows at a time.')
            rows.append((number, values))
    except RowProblem:
        raise
    except Exception:
        raise RowProblem('The file could not be read. Save it as Excel (.xlsx) or UTF-8 CSV.') from None
    if not rows:
        raise RowProblem('The file has no contact rows.')
    return rows


def options(channel=None):
    if channel:
        contacts.whatsapp_channel(channel)
        from relay_core.bulk_campaigns import channel_region
        return channel_region(channel)
    return identity.default_region()


def normalize_row(values, region):
    row = {key: bulk_sheet.text(values.get(key)) for key in COLUMNS}
    if any(len(value) > 200 for value in row.values()):
        raise RowProblem('A cell is too long (maximum 200 characters).')
    mobile = bulk_sheet.sheet_phone(row['Mobile'], region) if row['Mobile'] else None
    if row['Mobile'] and not mobile:
        raise RowProblem(bulk_sheet.SCIENTIFIC_PHONE if bulk_sheet.is_scientific(row['Mobile'])
                         else 'Enter a valid mobile number, including its country code.')
    try:
        email = identity.normalize('Email', row['Email']) if row['Email'] else ''
    except ValueError:
        raise RowProblem('Enter a valid email address.') from None
    if not mobile and not email:
        raise RowProblem('Enter a mobile number or email address.')
    label = row['Contact name'] or row['Mobile'] or email
    try:
        label = contacts.display_name(label)
    except frappe.ValidationError:
        raise RowProblem('Enter a plain contact name of at most 140 characters.') from None
    business = (row['Business type'], row['Business record'])
    if any(business):
        if not all(business):
            raise RowProblem('Enter both a business type and a business record.')
        if not frappe.db.exists('Relay Contact Type', {'business_doctype': business[0], 'enabled': 1}):
            raise RowProblem('Choose an enabled business type.')
        try:
            contacts.business_links([dict(doctype=business[0], name=business[1])])
        except (frappe.DoesNotExistError, frappe.PermissionError):
            raise RowProblem('The business record does not exist or you cannot read it.') from None
    return dict(mobile=mobile or '', email=email, label=label, business=business)


def matches(rows, region):
    """Resolve distinct identities once per import, including hidden owners and misses."""
    numbers = {bulk_sheet.sheet_phone(value, region) for value in
               {bulk_sheet.text(values.get('Mobile')) for _, values in rows}} - {None}
    emails = set()
    for value in {bulk_sheet.text(values.get('Email')) for _, values in rows} - {''}:
        try:
            emails.add(identity.normalize('Email', value))
        except ValueError:
            pass  # normalize_row supplies the friendly validation reason.
    found = {(kind, value): set() for kind, values in (('mobile', numbers), ('email', emails)) for value in values}
    if numbers:
        # Scan once without a suffix filter: national numbers may have fewer than ten digits.
        phones = identity.contacts_by_phone(region=region)
        for number in numbers:
            found['mobile', number].update(phones.get(number, []))
    if emails:
        for doctype, owner in (('Contact Email', 'parent'), ('Contact', 'name')):
            filters = {'email_id': ['in', sorted(emails)]}
            if doctype == 'Contact Email':
                filters['parenttype'] = 'Contact'
            for row in frappe.get_all(doctype, filters=filters, fields=['email_id', owner]):
                found['email', row.email_id.strip().lower()].add(row[owner])
    endpoints = {value: (kind, value) for kind, value in found}
    endpoints.update({'+' + number: ('mobile', number) for number in numbers})
    if endpoints:
        bindings = frappe.get_all('Relay Contact Endpoint', filters={'endpoint': ['in', sorted(endpoints)]},
                                 fields=['endpoint', 'relay_contact'])
        relays = sorted({row.relay_contact for row in bindings if row.relay_contact})
        people = {row.name: row.contact for row in frappe.get_all('Relay Contact',
                  filters={'name': ['in', relays]}, fields=['name', 'contact'])} if relays else {}
        for row in bindings:
            if people.get(row.relay_contact):
                found[endpoints[row.endpoint.strip().lower()]].add(people[row.relay_contact])
    return found


def existing_person(name, *, write=False):
    document_name(name)
    person = frappe.get_doc('Contact', name)
    from relay_core.business_access import require_person
    require_person(name)
    if write and not contacts.can_manage_links(name):
        person.check_permission('write')
    return person


def process(rows, region, *, apply=False, channel=None):
    results, owners, planned_links = [], {}, {}
    counts = dict(created=0, linked=0, skipped=0, errors=0)
    matched = matches(rows, region)
    for number, values in rows:
        result = dict(row=number, values=values, status='error', reason='')
        if apply:
            frappe.db.savepoint('contact_import_row')
        try:
            row = normalize_row(values, region)
            keys = [(kind, row[kind]) for kind in ('mobile', 'email') if row[kind]]
            found = set().union(*(matched.get(key, set()) for key in keys)) | {owners[key] for key in keys if key in owners}
            if len(found) > 1:
                raise RowProblem('These identities match different contacts. Review them before importing.')
            owner = next(iter(found), None)
            person = existing_person(owner) if isinstance(owner, str) else None
            links = planned_links.get(owner, set()) | ({(link.link_doctype, link.link_name) for link in person.links} if person else set())
            if owner and (not any(row['business']) or row['business'] in links):
                result.update(status='skip', reason='Already linked - skip' if any(row['business']) else 'Contact already exists - skip')
                counts['skipped'] += 1
            else:
                if person:
                    existing_person(owner, write=True)
                elif not owner and not frappe.has_permission('Contact', 'create'):
                    raise PermissionError
                status = 'link' if owner else 'create'
                if apply:
                    if not owner:
                        person = contacts.new_person(row['label'], row['mobile'], email=row['email'])
                        owner = person.name
                        relay = contacts.ensure_relay(person)
                        if channel and row['mobile']:
                            from relay_core.contact_lifecycle import enroll
                            if not enroll(relay, channel, 'WhatsApp', row['mobile']):
                                raise RowProblem('This number has an existing channel binding. Review the contact.')
                    if any(row['business']):
                        contacts.add_link(owner, *row['business'])
                owner = owner or -number
                planned_links.setdefault(owner, set()).add(row['business'])
                result.update(status=status, reason='Create contact' if status == 'create' else 'Add link')
                counts['created' if status == 'create' else 'linked'] += 1
            for key in keys:
                owners[key] = owner
        except (frappe.PermissionError, PermissionError):
            result['reason'] = 'You do not have permission to create or update this contact.'
        except RowProblem as exc:
            result['reason'] = str(exc)
        except Exception:
            result['reason'] = 'This row could not be imported. Check the contact details and try again.'
            if apply:
                frappe.log_error(title='Relay contact import row failed')
        if result['status'] == 'error':
            if apply:
                frappe.db.rollback(save_point='contact_import_row')
            counts['errors'] += 1
        results.append(result)
    return dict(rows=results, counts=counts, region=region)


def run(file_url, channel=None, *, apply=False):
    require_manager()
    try:
        rows, region = source_rows(file_url), options(channel)
    except RowProblem as exc:
        return {'error': str(exc)}
    # Shared phone mutex with inbound enrollment; serialize imports across all identities.
    with ExitStack() as held:
        if apply:
            held.enter_context(locks.lock('relay-contact-import', timeout=900, blocking_timeout=5))
            numbers = sorted({bulk_sheet.sheet_phone(values['Mobile'], region) for _, values in rows} - {None})
            for number in numbers:
                held.enter_context(locks.lock('relay-whatsapp-person:' + number, timeout=900))
        result = process(rows, region, apply=apply, channel=channel)
        if apply:
            # Keep import/enrollment mutexes until the created identities are visible
            # to another request. The endpoint owns this bounded transaction.
            frappe.db.commit()
        return result


@frappe.whitelist(methods=['POST'])
def preview(file_url, channel=None):
    return run(file_url, channel)


@frappe.whitelist(methods=['POST'])
def apply(file_url, channel=None):
    return run(file_url, channel, apply=True)


EXPORT_PAGE = 1000


def export_rows(query='', business_type=None, business_name=None, unlinked=0):
    """Keyset pages of the Contacts list scope; each page reads its links and their records in batches."""
    from relay_core.api import contact_filters
    from relay_core.business_access import allowed_types, people_query
    filters, or_filters = contact_filters(query, business_type, business_name, unlinked)
    types = allowed_types()
    yield list(COLUMNS)
    after = None
    while True:
        page = people_query(filters=[*filters, *([['Contact', 'name', '>', after]] if after else [])],
            or_filters=or_filters, fields=['name', 'mobile_no', 'phone', 'email_id', 'full_name', 'first_name'],
            order_by='name asc', limit=EXPORT_PAGE, distinct=True).run(as_dict=True)
        if not page:
            break
        links, readable = page_links([person.name for person in page], types)
        for person in page:
            base = [person.mobile_no or person.phone or '', person.email_id or '',
                    person.full_name or person.first_name or person.name]
            for link in links.get(person.name, ()):
                if ((link.link_doctype, link.link_name) in readable and business_type in (None, '', link.link_doctype)
                        and business_name in (None, '', link.link_name)):
                    yield [*base, link.link_doctype, link.link_name]
            if person.name not in links:
                yield [*base, '', '']
        after = page[-1].name


def page_links(people, types):
    """Business links of `people` by Contact, and the (doctype, name) pairs whose records exist in `types`."""
    links = {}
    for row in frappe.get_all('Dynamic Link', filters={'parenttype': 'Contact', 'parentfield': 'links', 'parent': ['in', people]},
                              fields=['parent', 'link_doctype', 'link_name'], order_by='parent asc, idx asc'):
        links.setdefault(row.parent, []).append(row)
    wanted = {}
    for rows in links.values():
        for row in rows:
            if row.link_doctype in types:
                wanted.setdefault(row.link_doctype, set()).add(row.link_name)
    readable = set()
    for doctype, names in wanted.items():
        try:
            readable.update((doctype, name) for name in frappe.get_all(doctype, filters={'name': ['in', list(names)]}, pluck='name'))
        except frappe.DoesNotExistError:
            pass
    return links, readable


@frappe.whitelist(methods=['GET'])
def export(query='', business_type=None, business_name=None, unlinked=0):
    require_manager()
    from frappe.utils.xlsxutils import make_xlsx
    from xlsxwriter import Workbook
    output = BytesIO()
    # Preserve literal strings (including phone '+' and names beginning '=') in Excel.
    book = Workbook(output, {'constant_memory': True, 'strings_to_formulas': False, 'strings_to_urls': False})
    make_xlsx(export_rows(query, business_type, business_name, unlinked), 'Contacts', wb=book)
    book.close()
    scope = business_type or ('Not linked' if str(unlinked) == '1' else '')
    frappe.response.update(filename=f'Relay contacts - {scope}.xlsx' if scope else 'Relay contacts.xlsx',
                           filecontent=output.getvalue(), type='binary')
