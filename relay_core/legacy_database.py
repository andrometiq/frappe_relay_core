"""Bulk import of frappe_whatsapp_core history, read straight from its database tables.

The source is another database (read-only session) or this site's own tables. Rows are
written with direct inserts, so no hook, notification, socket event, hub send or business
event runs. Every message keeps its source name in legacy_source and a site-scoped
source_key, so a re-run skips what is already imported.
"""
import os
import re
import tempfile
import time
from collections import Counter
from pathlib import Path

import frappe

from relay_core import legacy
from relay_core import legacy_bundle as bundles
from relay_core.contact_lifecycle import endpoint_key
from relay_core.identity import contacts_by_phone, phone_number
from relay_core.legacy_media import attach, copy_stream
from relay_core.legacy_metadata import direct_document, project_reactions
from relay_core.message_updates import provider_key
from relay_core.opt_out import apply_history
from relay_core.permissions import sequential_name

MESSAGE = 'tabWhatsApp Core Message'
RETRIES = 3
ACTIVITY = ('last_message_at', 'last_message')
OPT_OUT = ('marketing_opt_out', 'opt_out_changed_at', 'modified')
REACTION = ('reactions', 'message_updates')
ARCHIVE = '/private/files/relay-archive-'
# What a re-run takes from a changed source row; identity, contact and channel never change.
REFRESHED = ('status', 'content', 'message_type', 'message_data', 'delivery_error', 'provider_id', 'provider_context',
             'sent_at', 'legacy_author', 'legacy_checksum', 'legacy_data')


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
        self.phones = self.links = self.bindings = None
        self.unresolved = []
        # What the open transaction did: rewound on rollback, kept on commit.
        self.committed_counts = Counter()
        self.pending_unresolved = []
        self.copied = set()

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
            except Exception as exc:
                self.rollback()
                self.failures.append({'conversation': conversation.name, 'error': f'{type(exc).__name__}: {exc}'})
        self.counts['conversations'] = len(conversations)
        return {'counts': dict(self.counts), 'failures': self.failures, 'identity_unresolved': self.unresolved}

    def commit(self):
        frappe.db.commit()
        self.committed_counts = Counter(self.counts)
        self.unresolved += self.pending_unresolved
        self.pending_unresolved, self.copied = [], set()

    def rollback(self):
        """Forget what the open transaction did: counts, cached contact matches and copied bytes."""
        frappe.db.rollback()
        self.counts = Counter(self.committed_counts)
        self.phones = self.links = None
        remove_unused_copies(self.copied)
        self.pending_unresolved, self.copied = [], set()

    def import_conversation(self, conversation):
        """Import one conversation in transactions of at most --batch messages."""
        rows = self.page(conversation.name, ('', ''))
        if not rows:
            self.counts['empty_conversations'] += 1
            return
        channel = self.channels[conversation.channel]
        endpoint, is_phone = legacy_endpoint(conversation)
        manifest = {'source_site': self.site_label, 'endpoint': endpoint, 'source_conversation': conversation.name,
                    'identifier_type': 'Phone' if is_phone else conversation.identifier_type}
        created = {}

        def first_page():
            created.clear()
            contact = self.contact_for(channel, endpoint, is_phone, conversation, created)
            # The marker comes before the first message, so undo finds what an interrupted run made.
            marker = None if self.dry_run else self.mark(conversation, channel, contact, created)
            job = frappe._dict(channel=channel, relay_contact=contact, marker=marker)
            self.import_page(rows, job, manifest)
            return job

        job = self.transaction(first_page)
        while rows := self.page(conversation.name, bundles.order_key(rows[-1])):
            self.transaction(lambda: self.import_page(rows, job, manifest))
        if not self.dry_run:
            self.transaction(lambda: self.finish(conversation, endpoint, job, created))

    def transaction(self, work):
        """Run and commit one unit of work. A deadlock with live traffic (such as an inbound message
        taking the same naming series) rolls it back and runs it again."""
        for attempt in range(1, RETRIES + 1):
            failures = len(self.failures)
            try:
                result = work()
                self.commit()
                return result
            except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
                self.rollback()
                del self.failures[failures:]
                if attempt == RETRIES:
                    raise
                time.sleep(attempt)

    def import_page(self, rows, job, manifest):
        before = self.counts['created']
        self.import_rows(rows, job, manifest)
        if job.marker:
            frappe.db.sql('UPDATE `tabRelay Legacy Import` SET imported = imported + %s WHERE name = %s',
                          (self.counts['created'] - before, job.marker))

    def finish(self, conversation, endpoint, job, created):
        self.project_reactions(job, created)
        # A resumed run must know what the interrupted run created, not only what it created itself.
        stored = legacy.object_value(frappe.db.get_value('Relay Legacy Import', job.marker, 'source_metadata')).get('created', {})
        self.finish_contact(job.channel, endpoint, job.relay_contact, created, merge_created(stored, created))
        self.mark(conversation, job.channel, job.relay_contact, created)
        frappe.db.set_value('Relay Legacy Import', job.marker, 'status', 'Completed', update_modified=False)

    def finish_contact(self, channel, endpoint, contact, created, owned):
        """Set the directory activity and opt-out choice from the imported history. On a contact or
        endpoint the import did not create (`owned` lists what it did), the marker keeps the earlier values for undo."""
        if not owned.get('relay_contact'):
            created['activity'] = frappe.db.get_value('Relay Contact', contact, ACTIVITY, as_dict=True)
        refresh_activity(contact)
        before = None if owned.get('endpoint') else frappe.db.get_value(
            'Relay Contact Endpoint', {'endpoint_key': endpoint_key(channel, endpoint)}, ('name',) + OPT_OUT, as_dict=True)
        apply_history(channel, endpoint)
        after = before and frappe.db.get_value('Relay Contact Endpoint', before.name, OPT_OUT, as_dict=True)
        if before and after != {field: before[field] for field in OPT_OUT}:
            created['opt_out'] = {before.pop('name'): {'before': before, 'after': after}}

    def project_reactions(self, job, created):
        """Show imported reactions on their target messages the way live reactions are shown.
        A live target keeps its earlier reaction state in the marker, so undo can put it back."""
        rows = frappe.get_all('Relay Message', filters={'relay_contact': job.relay_contact, 'channel': job.channel,
                              'legacy_source': ['is', 'set'], 'message_type': 'reaction'}, fields=['message_data', 'sender_endpoint'])
        if not rows:
            return
        targets = [provider_key(job.channel, row.sender_endpoint, target) for row in rows
                   if (target := legacy.object_value(row.message_data).get('reaction', {}).get('message_id'))]
        saved = created.setdefault('reactions', {})
        live = frappe.get_all('Relay Message', filters={'provider_message_key': ['in', targets], 'legacy_source': ['is', 'not set']},
                              fields=['name', 'reactions', 'message_updates']) if targets else []
        for target in live:
            saved.setdefault(target.name, {'reactions': target.reactions, 'message_updates': target.message_updates})
        report = {'mismatches': []}
        project_reactions(job, report)
        # The state after the import: undo puts back the earlier state only while the target still has it.
        if live:
            created['reactions_after'] = {target.name: frappe.db.get_value('Relay Message', target.name, REACTION, as_dict=True)
                                          for target in live}
        self.counts['reactions_projected'] += len(rows) - len(report['mismatches'])
        for item in report['mismatches']:
            self.failures.append({'message': item['source'], 'error': item['detail']})

    def page(self, conversation, after):
        return self.source.sql(f'SELECT * FROM `{MESSAGE}` WHERE conversation=%s AND (creation, name) > (%s, %s) '
                               'ORDER BY creation, name LIMIT %s', (conversation, *after, self.batch))

    def mark(self, conversation, channel, contact, created):
        """One Relay Legacy Import row per source conversation: the undo and audit marker.
        It is written before the first message, so undo finds what an interrupted run made."""
        filters = {'source_site': self.site_label, 'source_conversation': conversation.name, 'channel': channel}
        row = frappe.db.get_value('Relay Legacy Import', filters, ['name', 'source_metadata'], as_dict=True)
        if row:
            metadata = legacy.object_value(row.source_metadata)
            merged = merge_created(metadata.get('created', {}), created)
            if merged != metadata.get('created', {}):
                frappe.db.set_value('Relay Legacy Import', row.name, 'source_metadata',
                                    bundles.canonical(dict(metadata, created=merged)), update_modified=False)
            return row.name
        return direct_document('Relay Legacy Import', dict(filters, source_channel=conversation.channel, relay_contact=contact,
                               status='Running', imported=0, source_metadata=bundles.canonical({'created': created}))).name

    def import_rows(self, rows, job, manifest):
        keys = {legacy.source_key(self.site_label, row.name): row for row in rows}
        existing = {row.source_key: row for row in frappe.get_all('Relay Message', filters={'source_key': ['in', list(keys)]},
                    fields=['name', 'source_key', 'relay_contact', 'channel', 'legacy_checksum', 'legacy_data', 'message_data'])}
        self.counts['read'] += len(rows)
        files = self.source_files([row.name for row in rows])
        new = []
        for key, row in keys.items():
            try:
                if key in existing:
                    self.refresh(existing[key], row, job, manifest, files.get(row.name, []))
                else:
                    new.append(row)
            except ValueError as exc:
                self.failures.append({'message': row.name, 'error': str(exc)})
        records = []
        # Live copies are dropped before any File is made for them.
        for row in self.without_live_copies(new, job, manifest):
            try:
                records.append(self.message(row, job, manifest, files.get(row.name, [])))
            except ValueError as exc:
                self.failures.append({'message': row.name, 'error': str(exc)})
        if not self.dry_run:
            legacy.insert_rows('Relay Message', records)
        self.counts['created'] += len(records)

    def without_live_copies(self, rows, job, manifest):
        """Rows whose provider message is not in Relay yet (a live copy wins) and not repeated in this page."""
        keys = {row.name: provider_key(job.channel, manifest['endpoint'], row.provider_message_id)
                for row in rows if row.provider_message_id}
        # A row without a provider ID is unique by its source name, so only provider keys are compared.
        live = set(frappe.get_all('Relay Message', filters={'provider_message_key': ['in', list(set(keys.values()))]},
                                  pluck='provider_message_key')) if keys else set()
        result, seen = [], set()
        for row in rows:
            key = keys.get(row.name)
            if key in live:
                self.failures.append({'message': row.name, 'error': 'Provider message already in Relay (live copy kept)'})
            elif key and key in seen:
                self.failures.append({'message': row.name, 'error': 'Provider message repeats in the source'})
            else:
                seen.add(key)
                result.append(row)
        return result

    def refresh(self, message, row, job, manifest, files):
        """Bring an imported message up to its source row (such as a later read receipt) and repair
        missing media. The message must belong to this conversation, and an older source row never wins."""
        if (message.relay_contact, message.channel) != (job.relay_contact, job.channel):
            raise ValueError(f'Imported message {message.name} belongs to another conversation')
        stored = legacy.object_value(message.legacy_data).get('row', {}).get('modified')
        if stored and row.modified and frappe.utils.get_datetime(row.modified) < frappe.utils.get_datetime(stored):
            self.counts['stale_skipped'] += 1
            return
        if message.legacy_checksum == bundles.checksum(row) and not self.missing_media(message, row, files):
            self.counts['skipped'] += 1
            return
        values = self.message(row, job, manifest, files, message.name)
        if not self.dry_run:
            frappe.db.set_value('Relay Message', message.name, {field: values[field] for field in REFRESHED}, update_modified=False)
        self.counts['updated'] += 1

    def missing_media(self, message, row, files):
        if not files and not legacy.converted(row)[2]:
            return False
        data = legacy.object_value(message.message_data)
        stored = data.get('legacy_attachments') or []
        return (not data.get('attachment') or any(item.get('availability') != 'available' for item in stored)
                or not all(has_copy(item) for item in stored or [{'attachment': data['attachment']}]))

    def message(self, row, job, manifest, files, name=None):
        values, data, _ = legacy.projection(row, job, manifest)
        name = name or ('dry-run' if self.dry_run else sequential_name('message'))
        data.update(self.attachments(row, files, name, data))
        failure = legacy.object_value(row.failure)
        now = frappe.utils.now_datetime()
        values.update(name=name, legacy_triage=0, message_type=data['kind'], message_data=bundles.canonical(data),
                      delivery_error=str(failure.get('message') or failure.get('error') or '')[:500] or None,
                      owner=frappe.session.user, modified_by=frappe.session.user, creation=now, modified=now, docstatus=0, idx=0)
        return values

    def source_files(self, messages):
        """Source message name -> its registered File rows. These, not payload URLs, list a message's media."""
        rows = self.source.sql("""SELECT name, file_name, file_url, attached_to_name FROM `tabFile`
            WHERE attached_to_doctype = 'WhatsApp Core Message' AND attached_to_name IN %s ORDER BY creation, name""", (messages,))
        result = {}
        for row in rows:
            result.setdefault(row.attached_to_name, []).append(row)
        return result

    def attachments(self, row, files, message, data):
        """Copy every source File of the message (the payload URL only when it has none).
        A file that cannot be found is a counted failure, never a link to the old site."""
        urls = list(dict.fromkeys(file.file_url for file in files if file.file_url))
        payload_url = legacy.converted(row)[2]
        if not urls and payload_url:
            urls = [payload_url]
        results = {}
        for url in urls:
            path = self.source_file(url)
            if not path:
                self.counts['media_failed'] += 1
                self.failures.append({'message': row.name, 'error': 'Media file not found: ' + url})
                results[url] = {'availability': 'missing', 'source_url': url}
            elif not self.dry_run:
                result = self.copy(path, message)
                if result['attachment'] not in results:
                    self.counts['media_copied'] += 1
                    results[result['attachment']] = result
        if not results:
            return {}
        listed = list(results.values())
        available = [item for item in listed if item['availability'] == 'available']
        update = {'legacy_attachments': listed}
        if available:
            update.update(attachment=available[0]['attachment'], attachment_source=message)
            if data['kind'] in ('text', 'unsupported'):
                update.update(kind='document', caption=data.get('text') or row.body or '')
        return update

    def copy(self, path, message):
        with open(path, 'rb') as source, tempfile.TemporaryFile() as temporary:
            digest, size = copy_stream(source, temporary)
            temporary.seek(0)
            # Tracked before attach() writes the bytes, so a failed File insert never leaves them behind.
            self.copied.add(ARCHIVE + digest)
            return attach(temporary, {'sha256': digest, 'size': size, 'filename': path.name}, message)

    def source_file(self, url):
        """The file in --files-dir by name, else, when the source is this site, the file at its own URL.
        Relay opens only private copies, so a public file of this site is copied too."""
        name = Path(url).name
        if self.files_dir and (self.files_dir / name).is_file():
            return self.files_dir / name
        if self.source.database or not url.startswith(('/files/', '/private/files/')):
            return None
        path = Path(frappe.get_site_path('private' if url.startswith('/private/') else 'public', 'files', name))
        return path if path.is_file() else None

    def contact_for(self, channel, endpoint, is_phone, conversation, created):
        """Relay Contact of the number on this channel, else a new endpoint (see new_endpoint).
        Its Contact gets a link to every Customer the source party bindings name."""
        bound = self.bound_customers(conversation)
        self.check_identity(conversation, endpoint, is_phone, bound)
        relay = frappe.db.get_value('Relay Contact Endpoint', {'endpoint_key': endpoint_key(channel, endpoint)}, 'relay_contact')
        if relay:
            self.counts['relay_contacts_reused'] += 1
        else:
            relay = self.new_endpoint(channel, endpoint, is_phone, conversation, bound, created)
        if not self.dry_run:
            self.link_customers(frappe.db.get_value('Relay Contact', relay, 'contact'), bound, created)
        return relay

    def new_endpoint(self, channel, endpoint, is_phone, conversation, bound, created):
        """Relay Contact of the same verified number on another channel, else of the Frappe Contact
        with this phone (the one linked to a bound Customer first), else a new Contact."""
        relay = frappe.db.get_value('Relay Contact Endpoint', {'endpoint': endpoint, 'verified': 1}, 'relay_contact')
        person = None if relay or not is_phone else self.phone_contact(endpoint, bound)
        if person:
            relay = frappe.db.get_value('Relay Contact', {'contact': person}, 'name')
        self.counts['relay_contacts_reused' if relay else 'frappe_contacts_matched' if person else 'contacts_created'] += 1
        if self.dry_run:
            return relay or 'dry-run'
        if not person and not relay:
            person = created['contact'] = self.new_contact(endpoint, is_phone, conversation, bound)
        if not relay:
            relay = created['relay_contact'] = direct_document('Relay Contact', {'contact': person, 'display_name': contact_title(person)},
                                                               sequential_name('contact')).name
        created['endpoint'] = direct_document('Relay Contact Endpoint', {'channel': channel, 'endpoint': endpoint, 'relay_contact': relay,
                                              'verified': 1, 'endpoint_key': endpoint_key(channel, endpoint)}).name
        return relay

    def phone_contact(self, endpoint, bound):
        candidates = self.candidates(endpoint)
        links = self.customer_links()
        return next((person for person in candidates if links.get(person, set()) & bound), candidates[0] if candidates else None)

    def candidates(self, endpoint):
        if self.phones is None:
            self.phones = contacts_by_phone()
        return self.phones.get(endpoint, [])

    def customer_links(self):
        if self.links is None:
            self.links = {}
            for row in frappe.db.sql("""SELECT parent, link_name FROM `tabDynamic Link`
                    WHERE parenttype = 'Contact' AND link_doctype = 'Customer'""", as_dict=True):
                self.links.setdefault(row.parent, set()).add(row.link_name)
        return self.links

    def link_customers(self, person, bound, created):
        """Link the chat's Contact to the bound Customers it lacks; undo removes exactly these links."""
        links = self.customer_links().setdefault(person, set())
        for customer in sorted(bound - links):
            idx = frappe.db.sql("""SELECT COALESCE(MAX(idx), 0) + 1 FROM `tabDynamic Link`
                WHERE parent = %s AND parenttype = 'Contact' AND parentfield = 'links'""", person)[0][0]
            link = direct_document('Dynamic Link', {'parent': person, 'parenttype': 'Contact', 'parentfield': 'links',
                                   'link_doctype': 'Customer', 'link_name': customer, 'idx': idx}, frappe.generate_hash(length=10))
            created.setdefault('links', []).append(link.name)
            links.add(customer)
            self.counts['customer_links_added'] += 1

    def bound_customers(self, conversation):
        """Customers that verified source party bindings name for this identity and that exist on this site."""
        if self.bindings is None:
            self.bindings = {}
            for row in self.source.sql("""SELECT identity, attributes FROM `tabWhatsApp Core Party Binding`
                    WHERE status = 'Verified'"""):
                customer = legacy.object_value(row.attributes).get('erpnext_customer')
                if customer:
                    self.bindings.setdefault(row.identity, set()).add(customer)
        names = self.bindings.get(conversation.identity, set())
        existing = set(frappe.get_all('Customer', filters={'name': ['in', list(names)]}, pluck='name')) if names else set()
        for customer in sorted(names - existing):
            self.unresolve(conversation, 'Bound Customer not on this site', customer=customer)
        return existing

    def check_identity(self, conversation, endpoint, is_phone, bound):
        """Count bound chats and list chats whose phone has several Contacts and no binding to choose by."""
        if bound:
            self.counts['customer_bound_conversations'] += 1
        candidates = self.candidates(endpoint) if is_phone else []
        if len(candidates) < 2:
            return
        if bound:
            self.counts['ambiguous_resolved_by_binding'] += 1
        else:
            self.unresolve(conversation, 'Phone on several Contacts and no Customer binding', phone=endpoint, candidates=candidates)

    def unresolve(self, conversation, reason, **detail):
        self.counts['identity_unresolved'] += 1
        self.pending_unresolved.append(dict(conversation=conversation.name, reason=reason, **detail))

    def new_contact(self, endpoint, is_phone, conversation, bound):
        number = '+' + endpoint if is_phone else None
        title = (conversation.display_value or '').strip()[:140] or number or endpoint
        person = frappe.get_doc({'doctype': 'Contact', 'first_name': title, 'full_name': title, 'mobile_no': number,
                                 'phone_nos': [{'phone': number, 'is_primary_mobile_no': 1}] if number else [],
                                 'links': [{'link_doctype': 'Customer', 'link_name': name} for name in sorted(bound)]})
        from frappe.model.naming import set_new_name
        set_new_name(person)
        insert_with_children(person)
        if number:
            self.phones[endpoint] = [person.name]
        self.customer_links()[person.name] = set(bound)
        return person.name


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


def merge_created(stored, created):
    """What earlier runs of one conversation created plus what this run created."""
    merged = dict(stored)
    for key, value in created.items():
        if isinstance(value, list):
            merged[key] = list(dict.fromkeys(merged.get(key, []) + value))
        elif key == 'reactions_after':
            merged[key] = {**merged.get(key, {}), **value}
        elif isinstance(value, dict):
            merged[key] = {**value, **merged.get(key, {})}
        else:
            merged.setdefault(key, value)
    return merged


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


def has_copy(item):
    """The File row of one copied attachment exists and, when its checksum is known, so do its bytes."""
    if not frappe.db.exists('File', item.get('attachment')):
        return False
    return not item.get('sha256') or copy_path(ARCHIVE + item['sha256']).is_file()


def copy_path(url):
    return Path(frappe.get_site_path(url.lstrip('/')))


def remove_unused_copies(file_urls):
    """Delete the media bytes the import copied (see legacy_media.attach) that no File row uses any more.
    Linked source files are never touched. Safe to repeat; returns how many files it deleted."""
    copies = {url for url in file_urls if url and url.startswith(ARCHIVE)}
    used = set(frappe.get_all('File', filters={'file_url': ['in', list(copies)]}, pluck='file_url')) if copies else set()
    deleted = 0
    for url in copies - used:
        path = copy_path(url)
        if path.is_file():
            path.unlink(missing_ok=True)
            deleted += 1
    return deleted


def assign_team(site_label, team):
    """Give a team every conversation of one import that has no assignment yet.
    A Relay Communication User sees only its own teams' conversations."""
    frappe.get_doc('Relay Team', team)
    markers = {}
    for job in frappe.get_all('Relay Legacy Import', filters={'source_site': site_label}, fields=['name', 'relay_contact'], order_by='name'):
        markers.setdefault(job.relay_contact, job.name)
    contacts = set(markers)
    assigned = set(frappe.get_all('Relay Conversation Assignment', filters={'relay_contact': ['in', list(contacts)]},
                                  pluck='relay_contact')) if contacts else set()
    for contact in sorted(contacts - assigned):
        assignment = frappe.get_doc({'doctype': 'Relay Conversation Assignment', 'relay_contact': contact, 'team': team}).insert()
        # The first marker of the chat records the assignment, so undo removes exactly it.
        metadata = legacy.object_value(frappe.db.get_value('Relay Legacy Import', markers[contact], 'source_metadata'))
        metadata['created'] = merge_created(metadata.get('created', {}), {'assignment': assignment.name})
        frappe.db.set_value('Relay Legacy Import', markers[contact], 'source_metadata', bundles.canonical(metadata), update_modified=False)
    from relay_core.queue_counts import invalidate
    invalidate()
    frappe.db.commit()
    return {'assigned': len(contacts - assigned), 'already_assigned': len(assigned)}
