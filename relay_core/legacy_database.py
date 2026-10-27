"""Bulk import of frappe_whatsapp_core history, read straight from its database tables.

The source is another database (read-only session) or this site's own tables. Rows are
written with direct inserts, so no hook, notification, socket event, hub send or business
event runs. Every message keeps its source name in legacy_source and a site-scoped
source_key, so a re-run skips what is already imported.
"""
import hashlib
import os
import re
import tempfile
from collections import Counter
from pathlib import Path

import frappe

from relay_core import legacy
from relay_core import legacy_bundle as bundles
from relay_core.contact_lifecycle import endpoint_key
from relay_core.identity import phone_number
from relay_core.legacy_media import attach, copy_stream
from relay_core.legacy_metadata import direct_document
from relay_core.opt_out import apply_history
from relay_core.permissions import sequential_name

MESSAGE = 'tabWhatsApp Core Message'


class Source:
    """Read-only access to the frappe_whatsapp_core tables of one database."""

    def __init__(self, database=None, host=None, port=None, user=None, password=None):
        self.db = frappe.db
        self.database = database
        if database:
            from frappe.database import get_db
            target = frappe.db
            self.db = get_db(socket=None if host else target.socket, host=host or target.host, port=port or target.port,
                             user=user or 'root', password=password, cur_db_name=database)
            self.db.connect()
            self.db.sql('SET SESSION TRANSACTION READ ONLY')

    def sql(self, query, values=None):
        return self.db.sql(query, values or (), as_dict=True)

    def close(self):
        if self.database:
            self.db.close()


class Importer:
    """One pass over every source conversation. Failures are listed, never rolled back."""

    def __init__(self, source, site_label, channel_map=None, batch=2000, dry_run=False, files_dir=None):
        self.source, self.site_label, self.batch, self.dry_run = source, site_label, batch, dry_run
        self.files_dir = Path(files_dir) if files_dir else None
        self.channels = self.target_channels(channel_map or {})
        self.counts = Counter()
        self.failures = []
        self.phones = None

    def target_channels(self, channel_map):
        """Source channel name -> Relay Channel: explicit map, else the WhatsApp channel with the same number."""
        result = {}
        for row in self.source.sql('SELECT name, phone_number_id, display_name FROM `tabWhatsApp Core Channel`'):
            target = channel_map.get(row.name) or matching_channel(row)
            if not target or not frappe.db.exists('Relay Channel', {'name': target, 'channel': 'WhatsApp'}):
                frappe.throw(f'Map source channel {row.name} ({row.display_name}) with --channel {row.name}=<Relay Channel>')
            result[row.name] = target
        return result

    def run(self):
        conversations = self.source.sql("""SELECT c.name, c.channel, i.normalized_value, i.identifier_type, i.display_value,
                i.name identity, (SELECT a.alias_value FROM `tabWhatsApp Core Identity Alias` a WHERE a.identity = i.name
                    AND a.alias_type = 'Phone' ORDER BY a.creation LIMIT 1) phone_alias
            FROM `tabWhatsApp Core Conversation` c JOIN `tabWhatsApp Core Identity` i ON i.name = c.remote_identity
            ORDER BY c.name""")
        for conversation in conversations:
            try:
                self.import_conversation(conversation)
                frappe.db.commit()
            except Exception as exc:
                frappe.db.rollback()
                self.failures.append({'conversation': conversation.name, 'error': f'{type(exc).__name__}: {exc}'})
        self.counts['conversations'] = len(conversations)
        return {'counts': dict(self.counts), 'failures': self.failures}

    def import_conversation(self, conversation):
        rows = self.page(conversation.name, ('', ''))
        if not rows:
            self.counts['empty_conversations'] += 1
            return
        channel = self.channels[conversation.channel]
        endpoint, is_phone = legacy_endpoint(conversation)
        created = {}
        contact = self.contact_for(channel, endpoint, is_phone, conversation, created)
        manifest = {'source_site': self.site_label, 'endpoint': endpoint, 'source_conversation': conversation.name,
                    'identifier_type': 'Phone' if is_phone else conversation.identifier_type}
        job = frappe._dict(channel=channel, relay_contact=contact)
        before = self.counts['created']
        while rows:
            self.import_rows(rows, job, manifest)
            rows = self.page(conversation.name, bundles.order_key(rows[-1]))
        if not self.dry_run:
            refresh_activity(contact)
            apply_history(channel, endpoint)
            self.mark(conversation, channel, contact, self.counts['created'] - before, created)

    def page(self, conversation, after):
        return self.source.sql(f'SELECT * FROM `{MESSAGE}` WHERE conversation=%s AND (creation, name) > (%s, %s) '
                               'ORDER BY creation, name LIMIT %s', (conversation, *after, self.batch))

    def mark(self, conversation, channel, contact, imported, created):
        """One Relay Legacy Import row per source conversation: the undo and audit marker."""
        filters = {'source_site': self.site_label, 'source_conversation': conversation.name, 'channel': channel}
        name = frappe.db.get_value('Relay Legacy Import', filters, 'name')
        if name:
            frappe.db.set_value('Relay Legacy Import', name, 'imported', (frappe.db.get_value('Relay Legacy Import', name, 'imported') or 0) + imported,
                                update_modified=False)
            return
        direct_document('Relay Legacy Import', dict(filters, source_channel=conversation.channel, relay_contact=contact,
                        status='Completed', imported=imported, source_metadata=bundles.canonical({'created': created})))

    def import_rows(self, rows, job, manifest):
        keys = {legacy.source_key(self.site_label, row.name): row for row in rows}
        existing = {row.source_key: row for row in frappe.get_all('Relay Message', filters={'source_key': ['in', list(keys)]},
                                                                  fields=['name', 'source_key', 'legacy_checksum'])}
        self.counts['read'] += len(rows)
        records = []
        for key, row in keys.items():
            try:
                if key in existing:
                    self.refresh(existing[key], row, job, manifest)
                else:
                    records.append(self.message(row, job, manifest))
            except ValueError as exc:
                self.failures.append({'message': row.name, 'error': str(exc)})
        provider_keys = [record['provider_message_key'] for record in records if record['provider_message_key']]
        live = set(frappe.get_all('Relay Message', filters={'provider_message_key': ['in', provider_keys]},
                                  pluck='provider_message_key')) if provider_keys else set()
        for record in [record for record in records if record['provider_message_key'] in live]:
            records.remove(record)
            self.failures.append({'message': record['legacy_source'], 'error': 'Provider message already in Relay (live copy kept)'})
        if not self.dry_run:
            legacy.insert_rows('Relay Message', records)
        self.counts['created'] += len(records)

    def refresh(self, message, row, job, manifest):
        """A source row changed since the last run (such as a later read receipt): take its status and payload."""
        if message.legacy_checksum == bundles.checksum(row):
            self.counts['skipped'] += 1
            return
        values, _, _ = legacy.projection(row, job, manifest)
        if not self.dry_run:
            frappe.db.set_value('Relay Message', message.name, {field: values[field] for field in
                                ('status', 'legacy_checksum', 'legacy_data')}, update_modified=False)
        self.counts['updated'] += 1

    def message(self, row, job, manifest):
        values, data, _ = legacy.projection(row, job, manifest)
        name = 'dry-run' if self.dry_run else sequential_name('message')
        url = legacy.converted(row)[2]
        if url and not self.dry_run:
            data.update(self.attachment(url, name))
        failure = legacy.object_value(row.failure)
        now = frappe.utils.now_datetime()
        values.update(name=name, legacy_triage=0, message_type=data['kind'], message_data=bundles.canonical(data),
                      delivery_error=str(failure.get('message') or failure.get('error') or '')[:500] or None,
                      owner=frappe.session.user, modified_by=frappe.session.user, creation=now, modified=now, docstatus=0, idx=0)
        return values

    def attachment(self, url, message):
        """Copy the bytes from --files-dir when present, else link the source File URL as it is."""
        path = self.files_dir / Path(url).name if self.files_dir else None
        if path and path.is_file():
            with open(path, 'rb') as source, tempfile.TemporaryFile() as temporary:
                digest, size = copy_stream(source, temporary)
                temporary.seek(0)
                result = attach(temporary, {'sha256': digest, 'size': size, 'filename': path.name}, message)
            self.counts['media_copied'] += 1
        else:
            result = link_file(url, message)
            self.counts['media_linked'] += 1
        return {'attachment': result['attachment'], 'attachment_source': message, 'legacy_attachments': [result]}

    def contact_for(self, channel, endpoint, is_phone, conversation, created):
        """Relay Contact of the number on this channel, else of the same verified number on another
        channel, else of the Frappe Contact with this phone, else a new Contact."""
        found = frappe.db.get_value('Relay Contact Endpoint', {'endpoint_key': endpoint_key(channel, endpoint)}, 'relay_contact')
        if found:
            self.counts['relay_contacts_reused'] += 1
            return found
        relay = frappe.db.get_value('Relay Contact Endpoint', {'endpoint': endpoint, 'verified': 1}, 'relay_contact')
        person = None if relay or not is_phone else self.phone_contact(endpoint)
        if person:
            relay = frappe.db.get_value('Relay Contact', {'contact': person}, 'name')
        self.counts['relay_contacts_reused' if relay else 'frappe_contacts_matched' if person else 'contacts_created'] += 1
        if self.dry_run:
            return relay or 'dry-run'
        if not person and not relay:
            person = created['contact'] = self.new_contact(endpoint, is_phone, conversation)
        if not relay:
            relay = created['relay_contact'] = direct_document('Relay Contact', {'contact': person, 'display_name': contact_title(person)},
                                                               sequential_name('contact')).name
        created['endpoint'] = direct_document('Relay Contact Endpoint', {'channel': channel, 'endpoint': endpoint, 'relay_contact': relay,
                                              'verified': 1, 'endpoint_key': endpoint_key(channel, endpoint)}).name
        return relay

    def phone_contact(self, endpoint):
        if self.phones is None:
            self.phones = contacts_by_phone()
        return self.phones.get(endpoint)

    def new_contact(self, endpoint, is_phone, conversation):
        number = '+' + endpoint if is_phone else None
        title = (conversation.display_value or '').strip()[:140] or number or endpoint
        person = frappe.get_doc({'doctype': 'Contact', 'first_name': title, 'full_name': title, 'mobile_no': number,
                                 'phone_nos': [{'phone': number, 'is_primary_mobile_no': 1}] if number else [],
                                 'links': [{'link_doctype': 'Customer', 'link_name': name} for name in self.customers(conversation)]})
        from frappe.model.naming import set_new_name
        set_new_name(person)
        insert_with_children(person)
        if number:
            self.phones[endpoint] = person.name
        return person.name

    def customers(self, conversation):
        """ERPNext Customers that the old party bindings name, when they exist on this site."""
        rows = self.source.sql("SELECT attributes FROM `tabWhatsApp Core Party Binding` WHERE identity=%s AND status='Verified'",
                               (conversation.identity,))
        names = {legacy.object_value(row.attributes).get('erpnext_customer') for row in rows}
        return sorted(name for name in names if name and frappe.db.exists('Customer', name))


def matching_channel(row):
    """The one WhatsApp Relay Channel whose hub channel or address is the source number."""
    digits = {re.sub(r'\D', '', value or '') for value in (row.phone_number_id, row.display_name)} - {''}
    matches = [channel.name for channel in frappe.get_all('Relay Channel', filters={'channel': 'WhatsApp'},
                                                          fields=['name', 'hub_channel', 'address'])
               if {re.sub(r'\D', '', channel.hub_channel or ''), re.sub(r'\D', '', channel.address or '')} & digits]
    return matches[0] if len(matches) == 1 else None


def legacy_endpoint(conversation):
    """(endpoint, is_phone). A business-scoped user ID uses the identity's phone alias when it has one."""
    if conversation.identifier_type == 'Phone' or conversation.phone_alias:
        value = conversation.normalized_value if conversation.identifier_type == 'Phone' else conversation.phone_alias
        number = phone_number(value)
        if number:
            return number, True
    if not conversation.normalized_value:
        raise ValueError('Conversation identity has no value')
    return conversation.normalized_value, False


def contacts_by_phone():
    """Normalized number -> Frappe Contact: one with a Relay Contact first, else the oldest."""
    rows = frappe.db.sql("""SELECT c.name, c.creation, p.phone, c.mobile_no, c.phone contact_phone, r.name relay
        FROM `tabContact` c LEFT JOIN `tabContact Phone` p ON p.parent = c.name AND p.parenttype = 'Contact'
        LEFT JOIN `tabRelay Contact` r ON r.contact = c.name""", as_dict=True)
    rows.sort(key=lambda row: (not row.relay, row.creation, row.name))
    result = {}
    for row in rows:
        for value in (row.phone, row.mobile_no, row.contact_phone):
            number = phone_number(value) if value else None
            if number:
                result.setdefault(number, row.name)
    return result


def contact_title(person):
    return (frappe.db.get_value('Contact', person, 'full_name') or person)[:140]


def insert_with_children(doc):
    now = frappe.utils.now_datetime()
    doc.owner = doc.modified_by = frappe.session.user
    doc.creation = doc.modified = now
    doc.db_insert()
    for child in doc.get_all_children():
        child.parent, child.parenttype = doc.name, doc.doctype
        child.db_insert()


def link_file(url, message):
    """A File record that points at the source URL as it is; the bytes stay where they are."""
    name = 'relay-archive-' + hashlib.sha256((message + ':' + url).encode()).hexdigest()
    direct_document('File', {'file_name': Path(url).name[:140], 'file_url': url, 'is_private': int(url.startswith('/private/')),
                             'attached_to_doctype': 'Relay Message', 'attached_to_name': message}, name)
    return {'attachment': name, 'availability': 'linked', 'source_url': url}


def refresh_activity(contact):
    """Directory order follows the newest message, imported or live."""
    from relay_core.inbox import message_created
    from relay_core.timeline import newest
    row = newest({'relay_contact': contact}, ('name', 'relay_contact', 'sent_at', 'creation'))
    if row:
        message_created(row)


def source_password(path=None):
    """The source password from a file or RELAY_SOURCE_DB_PASSWORD; never from the command line."""
    if path:
        return Path(path).read_text().strip()
    return os.environ.get('RELAY_SOURCE_DB_PASSWORD')


def undo(site_label):
    """Delete what one --source-site-label import created: messages, their Files, and the
    Contacts, Relay Contacts and endpoints it made. Matched existing contacts stay."""
    messages = frappe.db.sql_list("""SELECT name FROM `tabRelay Message` WHERE legacy_source IS NOT NULL
        AND JSON_UNQUOTE(JSON_EXTRACT(legacy_data, '$.source_site')) = %s""", site_label)
    contacts = set(frappe.get_all('Relay Message', filters={'name': ['in', messages]}, pluck='relay_contact', distinct=True)) if messages else set()
    for start in range(0, len(messages), 1000):
        chunk = messages[start:start + 1000]
        frappe.db.delete('File', {'attached_to_doctype': 'Relay Message', 'attached_to_name': ['in', chunk]})
        frappe.db.delete('Relay Message', {'name': ['in', chunk]})
    removed = Counter(messages=len(messages))
    for job in frappe.get_all('Relay Legacy Import', filters={'source_site': site_label}, fields=['name', 'source_metadata']):
        remove_created(legacy.object_value(job.source_metadata).get('created', {}), removed)
        frappe.db.delete('Relay Legacy Import', job.name)
    for contact in contacts:
        if frappe.db.exists('Relay Contact', contact):
            frappe.db.set_value('Relay Contact', contact, {'last_message_at': None, 'last_message': None}, update_modified=False)
            refresh_activity(contact)
    frappe.db.commit()
    return dict(removed)


def remove_created(created, removed):
    """Delete the endpoint, Relay Contact and Contact one conversation import made, unless live messages use them."""
    if created.get('relay_contact') and frappe.db.exists('Relay Message', {'relay_contact': created['relay_contact']}):
        removed['contacts_kept_with_new_messages'] += 1
        return
    for doctype, key in (('Relay Contact Endpoint', 'endpoint'), ('Relay Contact', 'relay_contact'), ('Contact', 'contact')):
        if created.get(key):
            frappe.db.delete(doctype, created[key])
            removed[doctype] += 1
    if created.get('contact'):
        frappe.db.delete('Contact Phone', {'parent': created['contact']})
        frappe.db.delete('Dynamic Link', {'parenttype': 'Contact', 'parent': created['contact']})
