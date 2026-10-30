"""Business type access against representative local-only SQL rows, without a site or provider."""
import json
import sqlite3
import sys
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
from frappe import _dict
from relay_core import business_access as access, business_inbox, business_groups, permissions, api


class BusinessTypeAccessTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript('''
            CREATE TABLE `tabContact` (name TEXT PRIMARY KEY);
            CREATE TABLE `tabRelay Contact Type` (name TEXT, business_doctype TEXT, enabled INTEGER, label TEXT);
            CREATE TABLE `tabRelay Contact Type User` (parent TEXT, parenttype TEXT, parentfield TEXT, user TEXT);
            CREATE TABLE `tabDynamic Link` (parent TEXT, parenttype TEXT, parentfield TEXT, link_doctype TEXT, link_name TEXT);
            CREATE TABLE `tabCustomer` (name TEXT, customer_name TEXT);
            CREATE TABLE `tabSupplier` (name TEXT);
            INSERT INTO `tabRelay Contact Type` VALUES
                ('Customer','Customer',1,'Clients'), ('Supplier','Supplier',1,''), ('Lead','Lead',0,'Prospects');
            INSERT INTO `tabRelay Contact Type User` VALUES ('Customer','Relay Contact Type','users','listed');
            INSERT INTO `tabContact` VALUES ('customer'), ('supplier'), ('shared'), ('unlinked'), ('disabled');
            INSERT INTO `tabCustomer` VALUES ('LOCAL-C1', 'Local test customer');
            INSERT INTO `tabSupplier` VALUES ('LOCAL-S1');
            INSERT INTO `tabDynamic Link` VALUES
                ('customer','Contact','links','Customer','LOCAL-C1'),
                ('supplier','Contact','links','Supplier','LOCAL-S1'),
                ('shared','Contact','links','Customer','LOCAL-C1'),
                ('shared','Contact','links','Supplier','LOCAL-S1'),
                ('disabled','Contact','links','Lead','LOCAL-L1');
        ''')
        self.roles = {'listed': [permissions.USER], 'unlisted': [permissions.USER],
                      'manager': [permissions.MANAGER], 'system': ['System Manager'], 'outsider': [],
                      'old-team': [permissions.TEAM_USER]}
        self.fake = SimpleNamespace(session=_dict(user='listed'), get_roles=lambda user=None: self.roles.get(user or self.fake.session.user, []),
            PermissionError=frappe.PermissionError, DoesNotExistError=frappe.DoesNotExistError, _dict=_dict,
            throw=lambda msg, exc=ValueError: (_ for _ in ()).throw(exc(msg)),
            has_permission=Mock(side_effect=lambda dt, *a, **kw: dt.startswith('Relay ')), get_doc=Mock(),
            get_all=self.get_all, db=SimpleNamespace(escape=lambda value: "'" + value.replace("'", "''") + "'",
                                                   sql=self.sql, exists=lambda *a: True))
        self.fake.parse_json = lambda value: json.loads(value) if isinstance(value, str) else value
        self.fake._ = lambda value: value
        self.fake.get_meta = Mock(return_value=_dict(title_field='customer_name', issingle=0, istable=0, module='Selling',
            get_field=lambda field: _dict(hidden=0, permlevel=0, fieldtype='Data')))
        self.enterContext(patch.object(business_groups, 'frappe', self.fake))
        self.enterContext(patch.object(access, 'frappe', self.fake))
        self.enterContext(patch.object(business_inbox, 'frappe', self.fake))
        self.enterContext(patch.object(business_inbox, 'require_access'))

    def get_all(self, doctype, filters, pluck=None, fields=None, order_by=None):
        columns = ' AND '.join(f'`{key}`=?' for key in filters)
        selected = ', '.join(f'`{key}`' for key in ([pluck] if pluck else fields))
        order = f' ORDER BY {order_by}' if order_by else ''
        rows = self.db.execute(f'SELECT {selected} FROM `tab{doctype}` WHERE {columns}{order}', tuple(filters.values()))
        return [row[0] if pluck else _dict(zip(fields, row)) for row in rows]

    def sql(self, sql, values=()):
        return self.db.execute(sql.replace('%s', '?'), (values,) if isinstance(values, str) else values).fetchall()

    def test_listed_unlisted_manager_system_disabled_and_legacy_roles(self):
        for user, expected in [('listed', {'Customer'}), ('unlisted', set()), ('manager', {'Customer', 'Supplier'}),
                               ('system', {'Customer', 'Supplier'}), ('outsider', set()), ('old-team', set())]:
            with self.subTest(user=user): self.assertEqual(access.allowed_types(user), expected)
        self.fake.has_permission.assert_not_called()

    @contextmanager
    def business_pickers(self, user):
        from relay_core import ai_features, business_event_options, business_types
        from relay_core.ai import configuration
        self.fake.session.user = user
        self.fake.has_permission.side_effect = lambda dt, mode, **kw: (
            dt == 'Relay Contact' and mode == 'read' and user in ('listed', 'unlisted', 'manager')
            or user == 'manager' and dt in ('Relay AI Skill', 'Relay Business Event Rule'))
        self.fake.get_list = Mock(side_effect=frappe.PermissionError('Insufficient Permission for DocType'))
        with patch.dict(sys.modules, {'frappe': self.fake}), \
                patch.object(configuration, 'frappe', self.fake), \
                patch.object(business_event_options, 'frappe', self.fake), \
                patch.object(business_types, 'frappe', self.fake), \
                patch.object(ai_features, 'is_enabled', return_value=True):
            yield (configuration.editor_options, business_event_options.search)
        self.fake.get_list.assert_not_called()
        self.fake.get_meta.assert_not_called()

    def test_business_pickers_manager_without_doctype_read_gets_enabled_types_and_labels(self):
        with self.business_pickers('manager') as pickers:
            self.assertFalse(self.fake.has_permission('DocType', 'read'))
            for picker in pickers:
                with self.subTest(picker=picker.__name__):
                    self.assertEqual(picker('business_doctype', doctype='Sales Invoice'), {'items': [
                        {'value': 'Customer', 'label': 'Clients'}, {'value': 'Supplier', 'label': 'Supplier'}]})
                    self.assertEqual(picker('business_doctype', query='cLiEn'), {
                        'items': [{'value': 'Customer', 'label': 'Clients'}]})
                    self.assertEqual(picker('business_doctype', query='SUPP'), {
                        'items': [{'value': 'Supplier', 'label': 'Supplier'}]})

    def test_business_pickers_user_gets_only_assigned_types(self):
        for user, expected in [('listed', [{'value': 'Customer', 'label': 'Clients'}]), ('unlisted', [])]:
            with self.business_pickers(user) as pickers:
                for picker in pickers:
                    with self.subTest(user=user, picker=picker.__name__):
                        self.assertEqual(picker('business_doctype'), {'items': expected})
                        self.assertEqual(picker('business_doctype', query='Supplier'), {'items': []})

    def test_business_pickers_selected_never_discloses_unassigned_disabled_or_unknown_types(self):
        for user, expected in [('manager', ['Customer', 'Supplier']), ('listed', ['Customer'])]:
            with self.business_pickers(user) as pickers:
                for picker in pickers:
                    for selected in (['Customer', 'Supplier', 'Lead', 'Unknown'],
                                     '["Customer","Supplier","Lead","Unknown"]'):
                        with self.subTest(user=user, picker=picker.__name__, selected=selected):
                            result = picker('business_doctype', selected=selected, query='no match')
                            self.assertEqual([row['value'] for row in result['items']], expected)
                    self.assertEqual(picker('business_doctype', selected=[]), {'items': []})
                    self.assertEqual(picker('business_doctype', selected=['Lead', 'Unknown']), {'items': []})

    def test_business_pickers_validate_input_and_keep_other_kinds_restricted(self):
        with self.business_pickers('listed') as pickers:
            for picker in pickers:
                for args in ({'query': 'x' * 81}, {'query': None}, {'selected': '{}'},
                             {'selected': ['x'] * 21}, {'selected': [1]}, {'selected': ['x' * 141]}):
                    with self.subTest(picker=picker.__name__, args=args), self.assertRaises(ValueError):
                        picker('business_doctype', **args)
                with self.assertRaises(frappe.PermissionError):
                    picker('doctype')
        with self.business_pickers('outsider') as pickers:
            for picker in pickers:
                with self.assertRaises(frappe.PermissionError):
                    picker('business_doctype')

    def test_contact_lists_and_document_checks_share_scope_and_nonzero_counts(self):
        expected = {'listed': ['customer', 'shared', 'unlinked'], 'unlisted': ['unlinked'],
                    'manager': ['customer', 'shared', 'supplier', 'unlinked'], 'outsider': []}
        for user, names in expected.items():
            with self.subTest(user=user):
                condition = access.person_condition('`tabContact`.name', user)
                rows = self.sql(f'SELECT name FROM `tabContact` WHERE {condition} ORDER BY name')
                self.assertEqual([row[0] for row in rows], names)
                self.assertEqual(self.sql(f'SELECT COUNT(*) FROM `tabContact` WHERE {condition}')[0][0], len(names))
                for name in ['customer', 'supplier', 'shared', 'unlinked', 'disabled']:
                    self.assertEqual(access.person_allowed(name, user), name in names)

    def test_denied_endpoints_have_frappe_403_and_no_business_data(self):
        # Frappe serializes this exception as exc_type=PermissionError and HTTP 403.
        for call in [lambda: business_inbox.context('Supplier', 'LOCAL-S1'),
                     lambda: business_inbox.messages('Supplier', 'LOCAL-S1'),
                     lambda: business_inbox.contacts('Supplier', 'LOCAL-S1'),
                     lambda: business_inbox.records('Supplier')]:
            with self.assertRaises(frappe.PermissionError) as caught: call()
            self.assertEqual(caught.exception.http_status_code, 403)
            self.assertEqual(type(caught.exception).__name__, 'PermissionError')
            self.assertEqual(str(caught.exception), 'Business type is not accessible')
        self.fake.get_doc.assert_not_called()

    def test_manager_opens_customer_context_without_desk_read(self):
        self.fake.session.user = 'manager'
        self.fake._ = lambda value: value
        self.fake.get_doc.return_value = _dict(name='LOCAL-C1', customer_name='Local test customer')
        with patch.object(business_inbox, '_linked_contacts', return_value=[_dict(name='customer')]), \
                patch.object(business_groups, 'configuration', return_value=[]):
            result = business_inbox.context('Customer', 'LOCAL-C1')
        self.assertEqual((result['title'], result['contact_count']), ('Local test customer', 1))
        self.fake.has_permission.assert_not_called()

    def test_shared_contact_does_not_grant_unassigned_message_history(self):
        message = _dict(doctype='Relay Message', relay_contact='shared', business_doctype='Supplier', business_name='LOCAL-S1')
        with patch.object(access, 'candidates', return_value=[('Customer', 'LOCAL-C1'), ('Supplier', 'LOCAL-S1')]):
            self.assertFalse(access.message_allowed(message, 'listed'))
            self.assertTrue(access.message_allowed(message, 'manager'))
            message.business_doctype, message.business_name = 'Customer', 'LOCAL-C1'
            self.assertTrue(access.message_allowed(message, 'listed'))

    def test_revocation_is_effective_on_the_next_check(self):
        self.assertTrue(access.person_allowed('customer', 'listed'))
        self.db.execute('DELETE FROM `tabRelay Contact Type User`')
        self.assertFalse(access.person_allowed('customer', 'listed'))
        self.assertTrue(access.person_allowed('unlinked', 'listed'))

    def test_type_tiles_never_aggregate_unassigned_types(self):
        with patch.object(api, 'require_access'), patch.object(business_groups, 'require_access'), \
                patch('relay_core.business_types.list_types', side_effect=lambda: [_dict(business_doctype=dt, enabled=1, label=dt) for dt in api.business_types()]), \
                patch.object(business_groups, 'configuration', return_value=[]), \
                patch.object(business_groups, 'aggregate', return_value=[{'record_count': 3, 'unread': 2}]) as aggregate, \
                patch('relay_core.inbox_filters.channel_names', return_value=None), \
                patch('relay_core.inbox_filters.business_filter'):
            page = business_groups.browse()
        self.assertEqual(page['items'], [{'kind': 'type', 'doctype': 'Customer', 'label': 'Customer', 'record_count': 3, 'unread': 2}])
        self.assertEqual(aggregate.call_args.args[0], 'Customer')
        self.assertEqual(aggregate.call_count, 1)

    def test_manager_send_reaches_hub_with_no_customer_or_contact_desk_read(self):
        from contextlib import nullcontext
        import sys
        from relay_core import conversation_start as start, messaging, whatsapp, tickets, business_events
        self.fake.session.user = 'manager'
        number = '919876543210'
        person = _dict(name='customer', mobile_no=number, links=[_dict(link_doctype='Customer', link_name='LOCAL-C1')])
        customer = _dict(name='LOCAL-C1', customer_name='Local test customer')
        denied = Mock(side_effect=frappe.PermissionError('No Desk read'))
        person.check_permission = customer.check_permission = denied
        relay = _dict(name='R1', contact='customer')
        relay.check_permission = lambda ptype: self.assertTrue(permissions.assignment_allowed('R1'))
        binding = _dict(name='E1', relay_contact='R1', channel='WA', endpoint=number, verified=1)
        channel = _dict(name='WA', channel='WhatsApp', account='local-test', enabled=1, check_permission=Mock())
        docs = {('Contact','customer'): person, ('Customer','LOCAL-C1'): customer,
                ('Relay Contact','R1'): relay, ('Relay Contact Endpoint','E1'): binding, ('Relay Channel','WA'): channel}
        self.fake.get_doc.side_effect = lambda dt, name=None: _dict(dt, name='LOCAL-ACTION') if isinstance(dt, dict) else docs[dt, name]
        self.fake.db.get_value = lambda dt, name, field, **kw: (
            ('R1' if isinstance(name, dict) else 'customer') if dt == 'Relay Contact' else
            'WhatsApp' if dt == 'Relay Channel' else 'WA' if dt == 'Relay Contact Endpoint' else None)
        self.fake.db.commit = Mock()
        self.fake.cache = SimpleNamespace(lock=lambda *a, **kw: nullcontext())
        self.fake.ValidationError = frappe.ValidationError
        self.fake.get_all = lambda dt, **kw: [_dict(name='E1')] if dt == 'Relay Contact Endpoint' else self.get_all(dt, **kw)
        hub = Mock()
        hub.call_tool.return_value = {'message_id': 'local-provider-id'}
        with patch.dict(sys.modules, {'frappe': self.fake}), \
                patch.object(start, 'frappe', self.fake), patch.object(start, 'connection_value', return_value='local-test'), \
                patch.object(start, 'enroll_business_contact'), patch.object(start, 'internal_save'), \
                patch.object(access, 'candidates', return_value=[('Customer', 'LOCAL-C1')]), \
                patch('relay_core.hub_channels.is_current', return_value=True), \
                patch('relay_core.hub_channels.hub_arguments', side_effect=lambda channel,args: args), \
                patch.object(start.service_window, 'status', return_value={'open': True}), \
                patch.object(start.service_window, 'require_open'), \
                patch('relay_core.tickets.manual_takeover'), patch.object(messaging, 'delivery_snapshot'), \
                patch.object(messaging, 'delivery_fence'), patch.object(messaging, 'automation_scope'), \
                patch.object(messaging, 'finish', return_value={'action':'LOCAL-ACTION','status':'Submitted'}) as finish, \
                patch.object(whatsapp, 'client', return_value=hub):
            result = start.send_business('customer', 'WA', 'text', {'text':'Local test order 42 is ready'},
                                         'local-access-test', 'Customer', 'LOCAL-C1', endpoint='E1')
        self.assertEqual(result['status'], 'Submitted')
        denied.assert_not_called()
        hub.call_tool.assert_called_once()
        tool, payload = hub.call_tool.call_args.args
        self.assertEqual(tool, 'whatsapp.execute')
        self.assertEqual((payload['to'], payload['body']), (number, 'Local test order 42 is ready'))
        self.assertEqual(finish.call_args.args[-1], {'message_id':'local-provider-id'})

    def test_campaign_gate_checks_roles_even_with_custom_docperm(self):
        import sys
        for user, permitted in [('listed', False), ('unlisted', False), ('manager', True), ('system', True)]:
            self.fake.session.user = user
            with self.subTest(user=user), patch.dict(sys.modules, {'frappe': self.fake}):
                if permitted:
                    permissions.require_access('Relay Campaign', 'write')
                else:
                    with self.assertRaises(frappe.PermissionError): permissions.require_access('Relay Campaign', 'write')

    def test_message_list_scope_hides_unassigned_stamped_and_primary_history(self):
        import sys
        self.db.executescript('''
            CREATE TABLE `tabRelay Contact` (name TEXT, contact TEXT, primary_doctype TEXT, primary_name TEXT);
            INSERT INTO `tabRelay Contact` VALUES ('R1','shared','Supplier','LOCAL-S1'), ('R2','unlinked',NULL,NULL);
            CREATE TABLE `tabRelay Message` (name TEXT, relay_contact TEXT, business_doctype TEXT,
                business_name TEXT, legacy_triage INTEGER, ticket_notification TEXT);
            INSERT INTO `tabRelay Message` VALUES ('customer','R1','Customer','LOCAL-C1',0,NULL),
                ('supplier','R1','Supplier','LOCAL-S1',0,NULL), ('primary','R1',NULL,NULL,0,NULL),
                ('unlinked','R2',NULL,NULL,0,NULL), ('triage','R2',NULL,NULL,1,NULL);
        ''')
        self.fake.qb = SimpleNamespace(get_query=lambda dt, **kw: SimpleNamespace(get_sql=lambda: f'SELECT name FROM `tab{dt}`'))
        for user, expected in [('listed',['customer','unlinked']), ('unlisted',['unlinked']),
                               ('manager',['customer','primary','supplier','unlinked'])]:
            with self.subTest(user=user), patch.dict(sys.modules, {'frappe': self.fake}):
                condition = permissions.message_query(user)
                self.assertEqual([row[0] for row in self.sql(f'SELECT name FROM `tabRelay Message` WHERE {condition} ORDER BY name')], expected)
        self.db.execute("DELETE FROM `tabDynamic Link` WHERE parent='shared' AND link_doctype='Customer'")
        with patch.dict(sys.modules, {'frappe': self.fake}):
            condition = permissions.message_query('listed')
        self.assertEqual([row[0] for row in self.sql(f'SELECT name FROM `tabRelay Message` WHERE {condition}')], ['unlinked'])

    def test_user_assignments_must_be_unique_per_type(self):
        from relay_core.relay_core.doctype.relay_contact_type import relay_contact_type as controller
        self.fake.session.user = 'system'
        def config(users):
            return _dict(business_doctype='Customer', users=[_dict(user=user) for user in users])
        with patch.object(controller, 'require_access'), patch.object(controller, 'frappe', self.fake):
            controller.RelayContactType.validate(config(['listed', 'unlisted']))
            with self.assertRaisesRegex(ValueError, 'only once'):
                controller.RelayContactType.validate(config(['listed', 'listed']))

    def test_controller_limits_managers_to_users_and_rejects_security_types(self):
        from relay_core.relay_core.doctype.relay_contact_type import relay_contact_type as controller
        def config(**changes):
            doc = _dict(business_doctype='Customer', enabled=1, label='Customers', grouping_field='',
                        grouping_fields=[], users=[_dict(user='listed')])
            previous = _dict(doc)
            doc.update(is_new=lambda: False, get_doc_before_save=lambda: previous)
            doc.update(changes)
            return doc
        with patch.object(controller, 'frappe', self.fake), patch.object(controller, 'require_access'):
            self.fake.session.user = 'manager'
            controller.RelayContactType.validate(config(users=[_dict(user='unlisted')]))
            for changes in [dict(is_new=lambda: True), dict(business_doctype='Supplier'), dict(enabled=0),
                            dict(label='Changed'), dict(grouping_field='region'),
                            dict(grouping_fields=[_dict(fieldname='region', priority=1)])]:
                with self.subTest(changes=changes), self.assertRaises(frappe.PermissionError):
                    controller.RelayContactType.validate(config(**changes))
            self.fake.session.user = 'system'
            controller.RelayContactType.validate(config(is_new=lambda: True))
            controller.RelayContactType.validate(config(enabled=0, label='Changed',
                grouping_fields=[_dict(fieldname='region', priority=1)]))
            for dt in ('OAuth Bearer Token', 'API Key', 'Password Store', 'Secret Store', 'User', 'DocPerm'):
                with self.subTest(doctype=dt), self.assertRaises(ValueError):
                    controller.RelayContactType.validate(config(business_doctype=dt))
            meta = self.fake.get_meta.return_value
            for field, value in [('issingle', 1), ('istable', 1), ('module', 'Core'),
                                 ('module', 'Integrations'), ('module', 'Email')]:
                old = meta[field]
                meta[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    controller.RelayContactType.validate(config())
                meta[field] = old
            meta.is_submittable = 1
            controller.RelayContactType.validate(config(business_doctype='Sales Invoice'))

    def test_shared_notes_topics_and_recipients_require_the_stored_business(self):
        from relay_core import collaboration
        links = [('Customer', 'LOCAL-C1'), ('Supplier', 'LOCAL-S1')]
        with patch.object(collaboration, 'frappe', self.fake), patch.object(collaboration, 'conversation_reader'), \
                patch.object(access, 'candidates', return_value=links), \
                patch.object(access, 'unlinked_contact', return_value=False), \
                patch.object(permissions, 'can_read_contact_as', return_value=True):
            for kind in ('Relay Internal Comment', 'Relay Topic'):
                note = _dict(doctype=kind, relay_contact='shared', messages=[],
                             business_doctype='Supplier', business_name='LOCAL-S1')
                with self.subTest(kind=kind):
                    with self.assertRaises(frappe.PermissionError): collaboration.authorize(note)
                    self.assertIs(collaboration.authorize(note, 'manager'), note)
                    with self.assertRaises(frappe.PermissionError): collaboration.recipients('shared', ['listed'], note)
                    self.assertEqual(collaboration.recipients('shared', ['manager'], note), ['manager'])
                    note.business_doctype, note.business_name = links[0]
                    self.assertIs(collaboration.authorize(note), note)
            with self.assertRaises(frappe.PermissionError):
                collaboration.business_scope('shared', [], 'Supplier', 'LOCAL-S1')
            self.assertEqual(collaboration.business_scope('shared', [], 'Customer', 'LOCAL-C1'), links[0])
            self.fake.session.user = 'manager'
            self.assertEqual(collaboration.business_scope('shared', [], 'Supplier', 'LOCAL-S1'), links[1])
            with patch.object(access, 'reference', return_value=None):
                note = _dict(relay_contact='shared', messages=[])
                with self.assertRaises(frappe.PermissionError): collaboration.authorize(note)
                with patch.object(access, 'unlinked_contact', return_value=True):
                    self.assertIs(collaboration.authorize(note), note)
                    self.assertEqual(collaboration.business_scope('unlinked', []), (None, None))

    def test_record_selectors_never_reach_document_loading(self):
        selectors = [{'name': 'LOCAL-C1', 'private_field': ['like', 's%']}, ['LOCAL-C1'], 1, None,
                     '', '  ', 'x' * 141, 'LOCAL-C1\n']
        for value in selectors:
            with self.subTest(value=value), self.assertRaises(ValueError):
                business_inbox.view_state('Customer', value)
        self.fake.get_doc.assert_not_called()
        with patch.object(business_inbox, '_state', return_value={}) as state:
            self.assertEqual(business_inbox.view_state('Customer', 'LOCAL-C1'), {})
        self.fake.get_doc.assert_called_once_with('Customer', 'LOCAL-C1')
        state.assert_called_once()

    def test_removed_or_unconfigured_types_never_make_contacts_unlinked(self):
        self.db.execute("DELETE FROM `tabRelay Contact Type` WHERE business_doctype='Supplier'")
        for user in ('listed', 'unlisted', 'manager', 'system'):
            with self.subTest(user=user):
                self.assertFalse(access.person_allowed('supplier', user))
                self.assertTrue(access.person_allowed('unlinked', user))
        self.assertTrue(access.person_allowed('shared', 'listed'))
        self.db.execute("DELETE FROM `tabRelay Contact Type` WHERE business_doctype='Customer'")
        self.assertFalse(access.person_allowed('shared', 'listed'))
        self.assertFalse(access.person_allowed('shared', 'manager'))
        self.fake.db.get_value = lambda *args: 'supplier'
        self.fake.db.exists = lambda dt, filters: bool(self.sql(
            'SELECT 1 FROM `tabDynamic Link` WHERE parent=%s', filters['parent']))
        self.assertFalse(access.unlinked_contact('R1'))
        self.fake.db.get_value = lambda *args: 'unlinked'
        self.assertTrue(access.unlinked_contact('R2'))

    def test_read_and_unread_check_resolved_business_before_writes_or_counts(self):
        from relay_core import message_reads, relay_chats, conversation_state
        self.fake.db.get_value = Mock(return_value=7)
        self.fake.db.commit = Mock()
        with patch.object(message_reads, 'frappe', self.fake), patch.object(message_reads, 'require_access'), \
                patch.object(message_reads, 'readable_contact'), \
                patch.object(access, 'primary', return_value=('Supplier', 'LOCAL-S1')) as primary, \
                patch.object(conversation_state, 'fresh_write', side_effect=lambda write: write()) as fresh, \
                patch.object(message_reads, 'set_chat_read') as write, \
                patch.object(relay_chats, 'mark_read') as read_chat, patch.object(relay_chats, 'mark_unread') as unread_chat:
            for read in (0, 1):
                with self.subTest(read=read), self.assertRaises(frappe.PermissionError):
                    message_reads.mark_chat('shared', read)
            fresh.assert_not_called()
            write.assert_not_called()
            self.fake.db.get_value.assert_not_called()
            primary.return_value = ('Customer', 'LOCAL-C1')
            for read in (0, 1):
                self.assertEqual(message_reads.mark_chat('shared', read), {'contact': 'shared', 'unread': 7})
            read_chat.assert_called_once_with(('Customer', 'LOCAL-C1'))
            unread_chat.assert_called_once_with(('Customer', 'LOCAL-C1'))
            self.fake.session.user = 'manager'
            primary.return_value = ('Supplier', 'LOCAL-S1')
            self.assertEqual(message_reads.mark_chat('shared', 1)['unread'], 7)

    def test_all_title_readers_reject_hidden_and_privileged_fields(self):
        from relay_core import display, conversation_start, relay_chats, inbox_records
        doc = _dict(name='LOCAL-C1', customer_name='Private value')
        self.fake.get_doc.return_value = doc
        self.fake.db.get_value = lambda dt, name, field: doc.get(field)
        self.fake.get_list = Mock(return_value=[])
        row = _dict(name='CHAT1', business_doctype='Customer', business_name='LOCAL-C1', title='Old private cache',
                    last_channel='WA', last_message_at='', unread_count=1)
        with patch.object(display, 'frappe', self.fake), patch.object(display, 'require_access'), \
                patch.object(conversation_start, 'frappe', self.fake), patch.object(conversation_start, 'start_contact'), \
                patch.object(relay_chats, 'frappe', self.fake), patch.object(inbox_records, 'frappe', self.fake), \
                patch.object(access, 'primary', return_value=('Customer', 'LOCAL-C1')) as primary, \
                patch.object(access, 'candidates', return_value=[('Customer', 'LOCAL-C1')]), \
                patch.object(business_inbox, '_linked_contacts', return_value=[]), \
                patch.object(business_groups, 'configuration', return_value=[]):
            for hidden, permlevel, expected in [(1, 0, 'LOCAL-C1'), (0, 1, 'LOCAL-C1'), (0, 0, 'Private value')]:
                self.fake.get_meta.return_value.get_field = lambda field: _dict(hidden=hidden, permlevel=permlevel)
                with self.subTest(hidden=hidden, permlevel=permlevel):
                    self.assertEqual(business_inbox.context('Customer', 'LOCAL-C1')['title'], expected)
                    primary.return_value = ('Customer', 'LOCAL-C1')
                    self.assertEqual(access.primary_record('R1')['title'], expected)
                    primary.return_value = None
                    self.assertEqual(conversation_start.records('R1')[0]['title'], expected)
                    self.assertEqual(relay_chats.title(('Customer', 'LOCAL-C1')), expected)
                    self.assertEqual(inbox_records.items([row])[0]['title'], expected)
                    original = self.fake.get_all
                    self.fake.get_all = lambda dt, **kw: [doc] if dt == 'Customer' else original(dt, **kw)
                    try:
                        result = display.titles([{'doctype': 'Customer', 'name': 'LOCAL-C1'}])
                        self.assertEqual(result['items'][0]['title'], expected)
                    finally:
                        self.fake.get_all = original

    def test_document_preview_checks_assignment_even_with_native_read(self):
        from relay_core import document_actions, document_sends, whatsapp_templates, identity
        action = _dict(name='LOCAL-ACTION', enabled=1, document_type='Supplier', business_field='name',
                       business_doctype='Supplier', roles=[], label='Local supplier action', channel='WA')
        supplier = _dict(name='LOCAL-S1', check_permission=Mock())
        person = _dict(name='supplier', full_name='Local supplier contact', has_permission=Mock(return_value=True))
        self.fake.get_doc.side_effect = lambda dt, name: action if dt == 'Relay Document Action' else person if dt == 'Contact' else supplier
        with patch.object(document_actions, 'frappe', self.fake), patch.object(document_actions, 'require_access'), \
                patch.object(document_actions, 'template_data', return_value={'name': 'Local template'}) as template, \
                patch.object(document_sends, 'contacts', return_value=['supplier']), \
                patch.object(identity, 'contact_identities', return_value={'WhatsApp': {'919876543210'}}), \
                patch.object(whatsapp_templates, 'message_content', return_value={'text': 'Balance 4500'}):
            with self.assertRaises(frappe.PermissionError): document_actions.preview('Supplier', 'LOCAL-S1', 'LOCAL-ACTION')
            template.assert_not_called()
            self.fake.session.user = 'manager'
            result = document_actions.preview('Supplier', 'LOCAL-S1', 'LOCAL-ACTION')
            self.assertEqual(result['text'], 'Balance 4500')
            self.assertEqual(result['recipients'][0]['numbers'], ['919876543210'])
            supplier.check_permission.assert_called_with('read')

    def test_enrollment_and_preferences_use_central_scope_without_desk_read(self):
        from relay_core import enrollment, channel_preferences
        self.db.executescript('''
            CREATE TABLE `tabRelay Channel Preference` (name TEXT, business_doctype TEXT, business_name TEXT);
            INSERT INTO `tabRelay Channel Preference` VALUES ('C', 'Customer', 'LOCAL-C1'), ('S', 'Supplier', 'LOCAL-S1');
        ''')
        self.fake.qb = SimpleNamespace(get_query=lambda dt, **kw: SimpleNamespace(get_sql=lambda: f'SELECT name FROM `tab{dt}`'))
        with patch.object(enrollment, 'require_access'), patch.object(enrollment, 'readable_contact'), \
                patch.object(channel_preferences, 'frappe', self.fake), \
                patch.object(access, 'candidates', return_value=[('Customer', 'LOCAL-C1'), ('Supplier', 'LOCAL-S1')]):
            for user, expected in [('listed', ['Customer']), ('unlisted', []), ('manager', ['Customer', 'Supplier'])]:
                self.fake.session.user = user
                with self.subTest(user=user):
                    self.assertEqual([row['doctype'] for row in enrollment.businesses('shared')], expected)
                    condition = channel_preferences.query()
                    self.assertEqual([row[0] for row in self.sql(f'SELECT business_doctype FROM `tabRelay Channel Preference` WHERE {condition} ORDER BY name')], expected)
                    for dt in ('Customer', 'Supplier'):
                        self.assertEqual(channel_preferences.permission(_dict(business_doctype=dt, business_name='LOCAL-1')), dt in expected)
        self.fake.has_permission.assert_not_called()

    def test_title_search_never_matches_a_private_cached_title(self):
        from frappe.query_builder.utils import get_query_builder
        from relay_core import inbox_records
        self.db.executescript('''
            CREATE TABLE `tabRelay Chat` (name TEXT, business_doctype TEXT, business_name TEXT, title TEXT);
            INSERT INTO `tabRelay Chat` VALUES ('CHAT1', 'Customer', 'LOCAL-C1', 'Secret cached title');
        ''')
        self.fake.qb = get_query_builder('mariadb')
        chat = self.fake.qb.DocType('Relay Chat')
        with patch.object(inbox_records, 'frappe', self.fake):
            for permlevel in (0, 1):
                self.fake.get_meta.return_value.get_field = lambda field: _dict(hidden=0, permlevel=permlevel)
                condition = inbox_records.search_filters('Secret')[0]
                query = self.fake.qb.from_(chat).select(chat.name).where(condition).get_sql()
                self.assertEqual(self.sql(query), [])
                condition = inbox_records.search_filters('Local test')[0]
                query = self.fake.qb.from_(chat).select(chat.name).where(condition).get_sql()
                self.assertEqual(self.sql(query), [] if permlevel else [('CHAT1',)])
