"""Standalone regression tests: no Frappe installation, site or provider network needed."""
import hashlib
import importlib.util
import json
import sqlite3
import sys
import types
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
NUMBER = '917976376832'


class Row(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__


def denied(message, exception=ValueError):
    raise exception(message)


class BoundaryTests(unittest.TestCase):
    def module(self, name, **attributes):
        module = types.ModuleType(name)
        module.__dict__.update(attributes)
        self.enterContext(patch.dict(sys.modules, {name: module}))
        parent, _, child = name.rpartition('.')
        if parent in sys.modules:
            self.enterContext(patch.object(sys.modules[parent], child, module, create=True))
        return module

    def load(self, name, path=None):
        path = path or str(ROOT / (name.replace('.', '/') + '.py'))
        spec = importlib.util.spec_from_file_location(name, path)
        module = self.module(name)
        spec.loader.exec_module(module)
        return module

    def setUp(self):
        self.frappe = self.module('frappe', whitelist=lambda **kw: lambda fn: fn, _dict=Row,
            PermissionError=PermissionError, ValidationError=ValueError, DoesNotExistError=LookupError,
            DuplicateEntryError=ValueError, throw=denied, flags=Row(), session=Row(user='Administrator'),
            cache=Mock(lock=lambda *a, **kw: nullcontext()), db=Mock(), get_all=Mock(return_value=[]),
            get_list=Mock(return_value=[]), get_doc=Mock(), utils=Mock(get_datetime=lambda value: value),
            parse_json=json.loads)
        self.frappe.__path__ = []  # A package, so business_access can import frappe.permissions.
        self.module('frappe.permissions', has_permission=Mock(return_value=True))
        self.frappe.db.get_value.return_value = None
        self.frappe.db.exists.return_value = False
        self.identity = self.load('relay_core.identity')
        self.contacts = self.load('relay_core.contacts')
        self.lifecycle = self.load('relay_core.contact_lifecycle')
        self.access = self.load('relay_core.business_access')
        self.realtime = self.module('relay_core.realtime', changed=Mock(), contact_changed=Mock(),
            incoming_changed=Mock(), one_incoming_change=nullcontext)


class EnrollmentTests(BoundaryTests):
    def setUp(self):
        super().setUp()
        self.rows = []
        def bindings(channel, provider, number):
            return [row for row in self.rows if row.channel == channel and row.endpoint == number]
        self.lifecycle.bindings = bindings
        self.created = []
        self.person = Row(name='Person', full_name='Existing name', phone_nos=[], email_ids=[])
        self.frappe.get_doc.side_effect = self.get_doc
        self.identity.phone_number = lambda value: value.lstrip('+') if value.lstrip('+') == NUMBER else None
        self.identity.contacts_by_phone = Mock(return_value={})
        self.frappe.db.get_value.side_effect = lambda dt, key, fields, **kw: (
            ('WhatsApp', 'account') if dt == 'Relay Channel' else None)
        self.lifecycle.set_verified = self.save_endpoint

    def get_doc(self, values, name=None):
        if isinstance(values, dict):
            doc = Row(values, name=values['doctype'] + '-new')
            doc.insert = lambda **kw: self.created.append(doc) or doc
            return doc
        return self.person

    def save_endpoint(self, doc, verified):
        doc.verified = verified
        self.rows.append(doc)

    def test_new_number_creates_person_and_relay_and_verified_endpoint_once(self):
        for _ in range(2):
            self.assertEqual(self.lifecycle.whatsapp_contact('WA', NUMBER, 'Local Test Sender'), 'Relay Contact-new')
        self.assertEqual(len(self.created), 2)
        person, relay = self.created
        self.assertEqual(person.first_name, 'Local Test Sender')
        self.assertEqual(person.phone_nos, [{'phone': '+' + NUMBER, 'is_primary_mobile_no': 1}])
        self.assertEqual(person.links, [])
        self.assertEqual(relay.contact, person.name)
        self.assertEqual(len(self.rows), 1)
        self.assertEqual(self.rows[0].verified, 1)

    def test_unique_phone_reuses_person_and_existing_relay(self):
        self.identity.contacts_by_phone.return_value = {NUMBER: ['Person']}
        self.frappe.db.get_value.side_effect = lambda dt, key, fields, **kw: (
            ('WhatsApp', 'account') if dt == 'Relay Channel' else 'Existing Relay')
        self.assertEqual(self.lifecycle.whatsapp_contact('WA', NUMBER), 'Existing Relay')
        self.assertEqual(self.created, [])
        self.assertEqual(self.rows[0].relay_contact, 'Existing Relay')

    def test_unique_phone_without_relay_creates_only_relay(self):
        self.identity.contacts_by_phone.return_value = {NUMBER: ['Person']}
        self.lifecycle.whatsapp_contact('WA', NUMBER)
        self.assertEqual([row.doctype for row in self.created], ['Relay Contact'])
        self.assertEqual(self.created[0].contact, 'Person')

    def test_multiple_phone_matches_create_separate_unlinked_person(self):
        self.identity.contacts_by_phone.return_value = {NUMBER: ['Person', 'Other']}
        self.lifecycle.whatsapp_contact('WA', NUMBER)
        self.assertEqual(self.created[0].first_name, NUMBER)
        self.assertEqual(self.created[0].links, [])

    def test_revoked_or_ambiguous_bindings_and_siblings_are_not_overwritten(self):
        for existing in ([Row(channel='WA', endpoint=NUMBER, relay_contact='Other', verified=0)],
                         [Row(channel='WA', endpoint=NUMBER, relay_contact=owner, verified=1) for owner in ('A', 'B')]):
            self.rows[:] = existing
            self.assertIsNone(self.lifecycle.whatsapp_contact('WA', NUMBER))
        self.rows.clear()
        self.frappe.get_all.side_effect = [['WA', 'Other WA'], ['A', 'B']]
        self.assertIsNone(self.lifecycle.whatsapp_contact('WA', NUMBER))
        self.assertEqual(self.created, [])

    def test_enroll_refuses_other_owner_or_revocation_and_returns_same_owner(self):
        self.rows.append(Row(channel='WA', endpoint=NUMBER, relay_contact='A', verified=1))
        self.assertIsNone(self.lifecycle.enroll('B', 'WA', 'WhatsApp', NUMBER))
        self.assertEqual(self.lifecycle.enroll('A', 'WA', 'WhatsApp', NUMBER), self.rows[0])
        self.rows[0].verified = 0
        self.assertIsNone(self.lifecycle.enroll('A', 'WA', 'WhatsApp', NUMBER))
        self.assertEqual(len(self.rows), 1)

    def test_non_numeric_whatsapp_identity_is_not_auto_enrolled(self):
        for value in ('group-id', 'US.business-scoped', '123'):
            self.assertIsNone(self.lifecycle.whatsapp_contact('WA', value))
        self.assertEqual(self.created, [])

    def test_legacy_phone_matching_deduplicates_child_rows_and_checks_primary_fields(self):
        # Use the actual shared mapping function, with normalization isolated at its dependency.
        identity = self.load('relay_core.identity')
        identity.phone_number = lambda value: ''.join(c for c in value if c.isdigit()).removeprefix('00')
        self.frappe.db.sql.return_value = [
            Row(name='P1', creation=1, relay='R1', customer=1, phone='+' + NUMBER, mobile_no=NUMBER),
            Row(name='P1', creation=1, relay='R1', customer=1, contact_phone='00' + NUMBER),
            Row(name='P2', creation=2, customer=0, mobile_no=NUMBER)]
        self.assertEqual(identity.contacts_by_phone(), {NUMBER: ['P1', 'P2']})


class ProjectionTests(BoundaryTests):
    def setUp(self):
        super().setUp()
        self.module('relay_core.automation.queue', BATCH_SIZE=100, TURN_SECONDS=5, Drain=Mock())
        self.module('relay_core.inbound', retry_callback=lambda fn: fn)
        self.module('relay_core.whatsapp_templates', project=Mock(return_value=False), template_event=Mock(return_value=False))
        self.module('relay_core.hub_channels', event_channel=Mock(return_value='WA'))
        self.module('relay_core.call_records', ingest=Mock(return_value=False))
        self.module('relay_core.bulk_updates', link_reply=Mock())
        self.module('relay_core.timeline', provider_time=lambda *a: '2026-10-28 10:00:00')
        self.module('relay_core.telegram_topics', observe=Mock())
        self.module('relay_core.email', recipients=lambda values: values or [])
        self.tickets = self.module('relay_core.tickets', ensure_episode=Mock(return_value=None),
            source_episode=lambda *a: ('provider-key', 'action-key'), triage_owner=Mock(return_value=None))
        self.routing = self.module('relay_core.business_routing', resolve=Mock(return_value=(None, 'triage_no_business')))
        self.module('relay_core.ai_features', is_enabled=Mock(return_value=True))
        self.projection = self.load('relay_core.automation.projection')
        self.projection.apply_updates = Mock(return_value='Ignored')
        self.lifecycle.sibling_contact = Mock(return_value=None)
        self.lifecycle.whatsapp_contact = Mock(return_value='Relay-new')
        self.messages = []
        self.event = Row(name='Event', account='account', projection_status='Pending', routing_decisions='{}')
        self.frappe.get_doc.side_effect = self.get_doc
        self.frappe.db.set_value.side_effect = lambda dt, name, key, value: self.event.update({key: value})
        self.frappe.db.exists.side_effect = lambda dt, filters: any(
            all(message.get(key) == value for key, value in filters.items()) for message in self.messages)

    def get_doc(self, value, name=None):
        if isinstance(value, dict):
            doc = Row(value)
            doc.insert = lambda **kw: self.messages.append(doc) or doc
            return doc
        return self.event

    def project(self, medium='WhatsApp', group=False, previous=None, known=False, rule='triage_no_business'):
        message = dict(id='m1', **{'from': NUMBER}, type='text', text={'body': 'Local test: quantity 12'})
        if group:
            message['group_id'] = 'group-id'
        payload = {'entry': [{'changes': [{'value': {'messages': [message],
            'contacts': [{'wa_id': NUMBER, 'profile': {'name': 'Test sender'}}]}}]}]}
        if medium != 'WhatsApp':
            payload = dict(channel=medium, direction='inbound', provider_id='m1', sender=NUMBER if medium == 'Telegram'
                else 'local@example.invalid', body='Local test: quantity 12')
        self.event.payload = json.dumps(payload)
        self.event.routing_decisions = json.dumps({'m1': previous} if previous else {})
        self.routing.resolve.return_value = (('Customer', 'C1') if rule == 'single_link' else None, rule)
        self.frappe.db.get_value.side_effect = lambda dt, *a, **kw: 'Known' if known and dt == 'Relay Contact Endpoint' else None
        self.projection.project('Event')

    def test_unknown_private_message_is_visible_unowned_and_deduplicated(self):
        self.project()
        self.assertEqual(self.event.projection_status, 'Projected')
        self.assertEqual(len(self.messages), 1)
        message = self.messages[0]
        self.assertEqual((message.relay_contact, message.business_doctype, message.business_name), ('Relay-new', None, None))
        self.assertEqual((message.direction, message.status, message.content), ('Incoming', 'Delivered', 'Local test: quantity 12'))
        self.lifecycle.whatsapp_contact.assert_called_once_with('WA', NUMBER, 'Test sender')
        self.tickets.ensure_episode.assert_not_called()
        self.event.projection_status = 'Uncategorized'
        self.projection.project('Event')
        self.assertEqual(len(self.messages), 1)

    def test_known_no_business_projects_without_triage_ticket(self):
        self.project(known=True)
        self.assertEqual(self.messages[0].relay_contact, 'Known')
        self.tickets.ensure_episode.assert_not_called()
        self.lifecycle.whatsapp_contact.assert_not_called()

    def test_recovery_retries_both_old_decisions_without_requiring_ticket(self):
        for previous in ('triage_unverified', 'triage_no_business'):
            for rule in ('triage_no_business', 'single_link'):
                with self.subTest(previous=previous, rule=rule):
                    self.messages.clear()
                    self.event.projection_status = 'Uncategorized'
                    self.project(previous=previous, rule=rule)
                    self.assertEqual(self.event.projection_status, 'Projected')
                    self.assertEqual(len(self.messages), 1)
        self.frappe.get_all.return_value = ['Event']
        with patch.object(self.projection, 'project_names') as retry:
            self.projection.recover()
        retry.assert_called_once_with(['Event'])
        self.assertEqual(self.frappe.get_all.call_args.kwargs['filters'], {'projection_status': 'Uncategorized'})
        self.tickets.ensure_episode.assert_not_called()

    def test_groups_telegram_and_email_keep_no_business_triage(self):
        for medium, group in [('WhatsApp', True), ('Telegram', False), ('Email', False)]:
            with self.subTest(medium=medium):
                self.event.projection_status = 'Pending'
                self.project(medium, group, known=True)
                self.assertEqual(self.event.projection_status, 'Uncategorized')
                self.assertEqual(self.messages, [])
        self.lifecycle.whatsapp_contact.assert_not_called()
        self.assertEqual(self.tickets.ensure_episode.call_count, 3)

    def test_reference_and_binding_failures_remain_triage(self):
        for rule in ('triage_conflicting_references', 'triage_unresolved_reference', 'triage_binding_changed',
                     'triage_unverified', 'triage_prompt_pending'):
            self.event.projection_status = 'Pending'
            self.project(rule=rule, known=True)
            self.assertEqual(self.event.projection_status, 'Uncategorized')
            self.assertEqual(self.messages, [])

    def test_other_stored_triage_decisions_still_require_ticket(self):
        self.project(previous='triage_conflicting_references', rule='single_link')
        self.assertEqual(self.event.projection_status, 'Uncategorized')
        self.assertEqual(self.messages, [])
        self.assertEqual(json.loads(self.event.routing_decisions)['m1'], 'triage_owner_unavailable')

    def test_sibling_is_used_before_creating_contact(self):
        self.lifecycle.sibling_contact.return_value = 'Sibling'
        self.project()
        self.assertEqual(self.messages[0].relay_contact, 'Sibling')
        self.lifecycle.whatsapp_contact.assert_not_called()


class StartDestinationTests(BoundaryTests):
    def setUp(self):
        super().setUp()
        self.module('relay_core.messaging')
        self.module('relay_core.whatsapp')
        self.module('relay_core.service_window')
        self.module('relay_core.whatsapp_templates')
        self.module('relay_core.automation.service', internal_save=Mock())
        self.module('relay_core.settings', value=lambda key: 'account')
        self.module('relay_core.business_inbox', check_type=Mock())
        self.start = self.load('relay_core.conversation_start')
        self.start.require_access = Mock()
        self.person = Row(name='Person', links=[Row(link_doctype='Sales Partner', link_name='Partner')],
            phone_nos=[Row(phone='7976376832')], email_ids=[Row(email_id='LOCAL@EXAMPLE.INVALID')],
            check_permission=Mock())
        self.business = Row(check_permission=Mock())
        self.frappe.get_doc.side_effect = lambda dt, name: self.person if dt == 'Contact' else self.business
        self.frappe.get_list.return_value = [Row(name='WA', channel='WhatsApp'), Row(name='Mail', channel='Email')]
        self.contacts.ensure_relay = Mock(return_value='Relay')
        self.enrolled = []
        self.lifecycle.enroll = Mock(side_effect=lambda *args: self.enrolled.append(args) or Row(name='Endpoint'))
        # The phone parser is an existing dependency unavailable in standalone Python. Exercise
        # phone_number/contact_identities and default-region selection against its library boundary.
        self.phone = self.module('phonenumbers', NumberParseException=ValueError,
            PhoneNumberFormat=Row(E164=1), parse=Mock(side_effect=lambda text, region: Row(text=text, region=region)),
            is_valid_number=lambda number: number.region == 'IN' and len(number.text) == 10,
            is_possible_number=lambda number: len(number.text.lstrip('+')) == 12,
            format_number=lambda number, fmt: '+91' + number.text if len(number.text) == 10 else number.text)
        self.frappe.db.get_single_value.return_value = 'India'
        self.module('frappe.geo.country_info', get_country_info=lambda country: {'code': 'in'})

    def enroll(self):
        return self.start.enroll_business_contact('Person', 'Sales Partner', 'Partner', 'WA')

    def test_ten_digit_number_uses_system_country_and_email_is_normalized(self):
        self.assertEqual(self.enroll(), 'Relay')
        self.assertEqual(self.enrolled, [('Relay', 'WA', 'WhatsApp', NUMBER),
                                       ('Relay', 'Mail', 'Email', 'local@example.invalid')])
        self.phone.parse.assert_called_with('7976376832', 'IN')
        self.frappe.db.get_single_value.assert_called_with('System Settings', 'country')
        self.person.check_permission.assert_called_once_with('read')
        self.business.check_permission.assert_called_once_with('read')
        self.assertEqual(self.frappe.get_list.call_args.kwargs['filters']['name'], 'WA')

    def test_bound_number_stays_with_its_contact_and_start_continues(self):
        self.lifecycle.enroll.return_value = None
        self.lifecycle.enroll.side_effect = None
        self.assertEqual(self.enroll(), 'Relay')
        self.frappe.db.set_value.assert_not_called()

    def test_unreadable_contact_business_or_channel_refused_before_enrollment(self):
        for doc in (self.person, self.business):
            doc.check_permission.side_effect = PermissionError
            with self.assertRaises(PermissionError):
                self.enroll()
            doc.check_permission.side_effect = None
        self.frappe.get_list.return_value = []
        with self.assertRaises(PermissionError):
            self.enroll()
        self.lifecycle.enroll.assert_not_called()
        self.contacts.ensure_relay.assert_not_called()

    def test_contact_must_belong_to_the_selected_business(self):
        self.person.links = [Row(link_doctype='Sales Partner', link_name='Other')]
        with self.assertRaises(PermissionError):
            self.enroll()
        self.lifecycle.enroll.assert_not_called()

    def test_business_picker_enrolls_before_reading_destinations(self):
        self.start.business_channels = Mock(side_effect=lambda *a: list(self.enrolled))
        result = self.start.business_options('Person', 'Sales Partner', 'Partner', channel='WA')
        self.assertEqual(len(result), 2)

    def test_start_binding_enrolls_on_the_selected_channel_without_sending(self):
        self.frappe.db.get_value.return_value = 'WhatsApp'
        original = self.frappe.get_doc.side_effect
        self.frappe.get_doc.side_effect = lambda dt, name: (Row(name='Endpoint', relay_contact='Relay')
            if dt == 'Relay Contact Endpoint' else original(dt, name))
        self.start.business_channels = Mock(return_value=[{'value': 'WA', 'endpoint': 'Endpoint'}])
        self.assertEqual(self.start.ensure_business_binding('Person', 'WA', 'Sales Partner', 'Partner'),
                         ('Relay', 'Endpoint'))
        self.assertEqual(self.enrolled[0], ('Relay', 'WA', 'WhatsApp', NUMBER))

    def test_business_permission_does_not_require_existing_conversation_assignment(self):
        self.frappe.db.get_value.return_value = 'Person'
        self.start.readable_contact = Mock(side_effect=PermissionError)
        self.start.start_contact('Relay', 'Sales Partner', 'Partner')
        self.start.readable_contact.assert_called_once_with('Relay')
        with self.assertRaises(PermissionError):
            self.start.start_contact('Relay')


    def business_access(self, links, marked=None):
        return self.module('relay_core.business_access', candidates=Mock(return_value=links),
            primary=Mock(return_value=marked), choose_business=Mock(return_value=('Customer', 'C1')))

    def test_contact_without_records_starts_an_unlinked_chat(self):
        access = self.business_access([])
        self.assertEqual(self.start.start_business('Relay'), (None, None))
        access.choose_business.assert_not_called()

    def test_contact_with_records_still_needs_one_record(self):
        access = self.business_access([('Customer', 'C1'), ('Customer', 'C2')])
        self.assertEqual(self.start.start_business('Relay'), ('Customer', 'C1'))
        access.choose_business.assert_called_once_with('Relay', None, None)

    def test_records_lists_readable_choices_only_without_a_primary(self):
        self.start.readable_contact = Mock()
        docs = {'C1': Row(meta=Row(title_field='customer_name'), customer_name='Shop One', has_permission=lambda p: True),
                'C2': Row(meta=Row(title_field=None), has_permission=lambda p: False)}
        self.frappe.get_doc.side_effect = lambda dt, name: docs[name]
        self.business_access([('Customer', 'C1'), ('Customer', 'C2')])
        self.assertEqual(self.start.records('Relay'), [{'doctype': 'Customer', 'name': 'C1', 'title': 'Shop One'}])
        self.business_access([('Customer', 'C1')], marked=('Customer', 'C1'))
        self.assertEqual(self.start.records('Relay'), [])


class ContactQueueTests(BoundaryTests):
    def setUp(self):
        super().setUp()
        self.contacts.require_access = Mock()
        self.module('relay_core.api', validate_reference=Mock())
        self.module('relay_core.inbox', directory_items=lambda rows: rows)
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE `tabRelay Contact` (name TEXT, contact TEXT, display_name TEXT, last_message_at TEXT, creation TEXT);
            CREATE TABLE `tabContact` (name TEXT, full_name TEXT, mobile_no TEXT, phone TEXT);
            CREATE TABLE `tabContact Phone` (parent TEXT, parenttype TEXT, phone TEXT);
            CREATE TABLE `tabDynamic Link` (parent TEXT, parenttype TEXT, parentfield TEXT, link_doctype TEXT, link_name TEXT);
            CREATE TABLE `tabRelay Contact Type` (business_doctype TEXT, enabled INTEGER);
            CREATE TABLE `tabRelay Contact Endpoint` (relay_contact TEXT, endpoint TEXT);
            CREATE TABLE `tabRelay Message` (name TEXT, relay_contact TEXT, business_doctype TEXT, business_name TEXT,
                legacy_source TEXT, legacy_triage INTEGER);
        ''')
        self.frappe.db.sql.side_effect = self.sql

    def sql(self, query, values=(), as_dict=False):
        import re
        if isinstance(values, dict):
            query = re.sub(r'%\((\w+)\)s', r':\1', query)
        else:
            query = query.replace('%s', '?')
        cursor = self.db.execute(query, values)
        return [Row(row) if as_dict else tuple(row) for row in cursor.fetchall()]

    def add_person(self, index, business=None):
        name, person = f'RELAY-CON-{index:010}', f'P{index}'
        self.db.execute('INSERT INTO `tabRelay Contact` VALUES (?,?,?,?,?)',
            (name, person, f'Local Test {index}', '2026-10-28 10:00:00', '2026-10-01'))
        self.db.execute('INSERT INTO `tabContact` VALUES (?,?,?,?)', (person, f'Local Test {index}', NUMBER, ''))
        if business:
            self.db.execute('INSERT INTO `tabDynamic Link` VALUES (?,?,?,?,?)',
                (person, 'Contact', 'links', business, 'Record'))
        return name

    def test_contact_queue_pages_all_rows_with_tied_dates_without_duplicates(self):
        for index in range(65):
            self.add_person(index)
        names, cursor = [], {}
        while True:
            page = self.contacts.unlinked(**cursor)
            names += [row.name for row in page['items']]
            if not page['next']:
                break
            cursor = page['next']
        self.assertEqual(len(names), 65)
        self.assertEqual(len(set(names)), 65)
        self.assertEqual(names, sorted(names, reverse=True))
        self.contacts.require_access.assert_called_with(manage=True)

    def test_queue_excludes_enabled_links_keeps_disabled_and_searches_names_numbers(self):
        self.db.executemany('INSERT INTO `tabRelay Contact Type` VALUES (?,?)', [('Customer', 1), ('Supplier', 0)])
        enabled = self.add_person(1, 'Customer')
        disabled = self.add_person(2, 'Supplier')
        unlinked = self.add_person(3)
        self.assertEqual([row.name for row in self.contacts.unlinked()['items']], [unlinked, disabled])
        self.assertEqual([row.name for row in self.contacts.unlinked(query='Test 2')['items']], [disabled])
        self.assertEqual(len(self.contacts.unlinked(query='797637')['items']), 2)
        self.assertEqual(self.contacts.unlinked(query="' OR 1=1 --")['items'], [])
        self.assertNotIn(enabled, [row.name for row in self.contacts.unlinked()['items']])

    def test_queue_is_manager_only(self):
        self.contacts.require_access.side_effect = PermissionError
        with self.assertRaises(PermissionError):
            self.contacts.unlinked()
        self.frappe.db.sql.assert_not_called()

    def test_one_link_backfills_only_unowned_live_messages(self):
        fixtures = [
            ('live', 'R', None, None, None, 0), ('live-empty', 'R', '', '', '', 0),
            ('legacy', 'R', None, None, 'old-message', 0), ('owned', 'R', 'Supplier', 'S1', '', 0),
            ('triage', 'R', None, None, '', 1), ('other-person', 'Other', None, None, '', 0)]
        self.db.executemany('INSERT INTO `tabRelay Message` VALUES (?,?,?,?,?,?)', fixtures)
        with patch.object(self.access, 'candidates', return_value=[('Customer', 'C1')]), patch('relay_core.relay_chats.merge') as merge:
            self.lifecycle.associate_unlinked_messages('R')
            self.lifecycle.associate_unlinked_messages('R')
        merge.assert_called_with('R', ('Customer', 'C1'))
        rows = {row[0]: tuple(row) for row in self.db.execute('SELECT * FROM `tabRelay Message`')}
        for row in fixtures:
            expected = (*row[:2], 'Customer', 'C1', *row[4:]) if row[0] in ('live', 'live-empty') else row
            self.assertEqual(rows[row[0]], expected)

    def test_zero_or_multiple_links_do_not_backfill(self):
        for links in ([], [('Customer', 'C1'), ('Supplier', 'S1')]):
            with patch.object(self.access, 'candidates', return_value=links):
                self.lifecycle.associate_unlinked_messages('R')
        self.frappe.db.sql.assert_not_called()


class Expression:
    def __init__(self, sql):
        self.sql = sql

    def __eq__(self, other):
        return Expression(self.sql + '=' + literal(other))

    def __gt__(self, other):
        return Expression(self.sql + '>' + literal(other))

    def __and__(self, other):
        return Expression('(' + self.sql + ' AND ' + other.sql + ')')

    def isnull(self):
        return Expression(self.sql + ' IS NULL')

    def isin(self, values):
        return Expression(self.sql + ' IN (' + ','.join(literal(value) for value in values) + ')')


def literal(value):
    if isinstance(value, Expression):
        return value.sql
    return "'" + str(value).replace("'", "''") + "'"


class Table(Expression):
    def __getattr__(self, field):
        return Expression(self.sql + '.`' + field + '`')


class Query:
    """Tiny SQL builder boundary, executing the production unread filters in SQLite."""
    def __init__(self, db, source):
        self.db, self.source, self.fields, self.joins, self.conditions = db, source, '*', '', []

    @property
    def sql(self):
        return f'SELECT {self.fields} FROM {self.source.sql}{self.joins}' + (
            ' WHERE ' + ' AND '.join(self.conditions) if self.conditions else '')

    def select(self, *fields):
        self.fields = ','.join(field.sql if isinstance(field, Expression) else str(field) for field in fields)
        return self

    def left_join(self, table):
        self.joins += ' LEFT JOIN ' + table.sql
        return self

    def on(self, condition):
        self.joins += ' ON ' + condition.sql
        return self

    def where(self, condition):
        self.conditions.append(condition.sql)
        return self

    def as_(self, name):
        return Expression('(' + self.sql + ') AS ' + name)

    def run(self):
        return self.db.execute(self.sql).fetchall()


class BusinesslessAccessTests(BoundaryTests):
    def setUp(self):
        super().setUp()
        from relay_core import permissions
        self.permissions = permissions
        self.module('relay_core.api', validate_reference=Mock())
        self.module('relay_core.business_groups', responsible=lambda *a: False, responsibility_condition=lambda *a: '1=0')
        self.module('pypika.functions', Count=lambda field: Expression('COUNT(*)'))
        self.inbox = self.load('relay_core.inbox')
        self.frappe.session.user = 'agent'
        self.role = permissions.USER
        self.frappe.get_roles = lambda user=None: [self.role]
        self.frappe.has_permission = lambda dt, *a, **kw: dt in ('Relay Contact', 'Relay Message', 'Relay Channel')
        self.access.candidates = lambda contact: []
        self.frappe.db.get_value.side_effect = lambda dt, *a, **kw: (
            Row(team='Sales', assigned_to='someone') if dt == 'Relay Conversation Assignment' else None)
        self.frappe.db.exists.side_effect = lambda dt, filters: filters.get('parent') == 'Sales'
        self.frappe.db.escape = lambda value: literal(value)
        self.frappe.get_doc.side_effect = lambda dt, name: Row(name=name, has_permission=lambda *a, **kw:
            permissions.contact_permission(Row(name=name), user=kw.get('user')))
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript('''
            CREATE TABLE `tabRelay Message` (name TEXT, relay_contact TEXT, channel TEXT, direction TEXT,
                legacy_source TEXT, legacy_triage INTEGER);
            CREATE TABLE `tabRelay Message Read` (name TEXT, message TEXT, user TEXT);
            CREATE TABLE `tabRelay Conversation Assignment` (relay_contact TEXT, team TEXT, assigned_to TEXT);
            CREATE TABLE `tabRelay Team Member` (parent TEXT, parenttype TEXT, user TEXT);
            INSERT INTO `tabRelay Conversation Assignment` VALUES ('R','Sales','someone'),('Other','Private','someone');
            INSERT INTO `tabRelay Team Member` VALUES ('Sales','Relay Team','agent');
            INSERT INTO `tabRelay Message` VALUES
                ('M1','R','WA','Incoming','',0), ('M2','R','WA','Incoming',NULL,0),
                ('M3','R','WA','Incoming','',0), ('M4','R','Mail','Incoming','',0),
                ('M5','R','WA','Incoming','legacy-import',0), ('M6','R','WA','Outgoing','',0),
                ('M7','R','WA','Incoming','',1), ('M8','Other','WA','Incoming','',0);
            INSERT INTO `tabRelay Message Read` VALUES ('Read','M3','agent');
        ''')
        self.frappe.qb = types.SimpleNamespace(DocType=lambda dt: Table('`tab' + dt + '`'),
            from_=lambda source: Query(self.db, source), get_query=self.query)

    def query(self, doctype, fields, filters, ignore_permissions, order_by):
        self.assertFalse(ignore_permissions)
        table = self.frappe.qb.DocType(doctype)
        query = Query(self.db, table).select(*(getattr(table, field) for field in fields))
        for field, value in filters.items():
            if value == ['is', 'not set']:
                query.where(Expression(f"COALESCE({getattr(table, field).sql},'')=''"))
            else:
                query.where(getattr(table, field) == value)
        return query.where(Expression(self.permissions.message_query()))

    def test_team_and_communication_users_read_live_and_imported_businessless_messages(self):
        for role in (self.permissions.USER, self.permissions.TEAM_USER):
            self.role = role
            for legacy in ('', 'imported'):
                message = Row(relay_contact='R', business_doctype=None, business_name=None, legacy_source=legacy)
                self.assertTrue(self.permissions.message_permission(message, 'agent'), (role, legacy))
            self.assertFalse(self.permissions.message_permission(Row(relay_contact='R', legacy_triage=1), 'agent'))
        self.role = self.permissions.USER
        self.frappe.db.exists.return_value = False
        self.frappe.db.exists.side_effect = None
        self.assertFalse(self.permissions.message_permission(Row(relay_contact='R'), 'agent'))

    def test_live_unowned_messages_count_unread_with_team_channel_and_read_filters(self):
        for role in (self.permissions.USER, self.permissions.TEAM_USER):
            self.role = role
            self.assertEqual(self.inbox.unread_count('R', channels=['WA']), 2)
            self.assertEqual(self.inbox.unread_count('R', channels=['WA', 'Mail']), 3)
            self.assertEqual(self.inbox.unread_count('R', channels=[]), 0)
        self.role = self.permissions.USER
        self.assertEqual(self.inbox.unread_count('Other', channels=['WA']), 0)
        self.role = self.permissions.TEAM_USER
        self.assertEqual(self.inbox.unread_count('Other', channels=['WA']), 1)
        self.db.execute("INSERT INTO `tabRelay Message Read` VALUES ('Read1','M1','agent'),('Read2','M2','agent')")
        self.assertEqual(self.inbox.unread_count('R', channels=['WA']), 0)


class ManagerLinkTests(BoundaryTests):
    def setUp(self):
        super().setUp()
        self.contacts.require_access = Mock()
        self.contacts.can_manage = Mock(return_value=True)
        self.contacts.linked_contacts = Mock(return_value=set())
        self.frappe.db.get_value.return_value = 'Relay'
        self.frappe.db.exists.return_value = True
        self.person = Row(name='Person', links=[], check_permission=Mock(side_effect=PermissionError),
                          set=Mock(), save=Mock())
        self.business = Row(check_permission=Mock())
        self.frappe.get_doc.side_effect = lambda dt, name: self.person if dt == 'Contact' else self.business
        self.frappe.get_all.return_value = ['Customer']
        self.contacts.summary = Mock(return_value={'contact': 'Person'})

    def test_manager_links_unlinked_contact_without_general_contact_write(self):
        self.contacts.set_links('Person', [{'doctype': 'Customer', 'name': 'Local Customer'}])
        self.person.check_permission.assert_not_called()
        self.person.save.assert_called_once_with(ignore_permissions=True)
        self.business.check_permission.assert_called_once_with('read')
        self.person.set.assert_called_once_with('links', [{'link_doctype': 'Customer', 'link_name': 'Local Customer'}])

    def test_manager_removes_a_link_of_a_linked_contact_and_keeps_unreadable_links(self):
        self.person.links = [Row(link_doctype='Customer', link_name='Old'), Row(link_doctype='Customer', link_name='Private')]
        self.frappe.get_doc.side_effect = lambda dt, name: self.person if dt == 'Contact' else Row(
            check_permission=Mock(), has_permission=Mock(return_value=name != 'Private'))
        self.contacts.set_links('Person', [])
        self.person.check_permission.assert_not_called()
        self.person.set.assert_called_once_with('links', [{'link_doctype': 'Customer', 'link_name': 'Private'}])
        self.person.save.assert_called_once_with(ignore_permissions=True)

    def test_manager_exception_needs_a_relay_conversation(self):
        self.frappe.db.get_value.return_value = None
        with self.assertRaises(PermissionError):
            self.contacts.set_links('Person', [{'doctype': 'Customer', 'name': 'Local Customer'}])
        self.person.save.assert_not_called()

    def test_staff_and_unreadable_business_cannot_use_manager_exception(self):
        self.contacts.can_manage.return_value = False
        with self.assertRaises(PermissionError):
            self.contacts.set_links('Person', [{'doctype': 'Customer', 'name': 'Local Customer'}])
        self.contacts.can_manage.return_value = True
        self.business.check_permission.side_effect = PermissionError
        with self.assertRaises(PermissionError):
            self.contacts.set_links('Person', [{'doctype': 'Customer', 'name': 'Local Customer'}])
        self.person.save.assert_not_called()
