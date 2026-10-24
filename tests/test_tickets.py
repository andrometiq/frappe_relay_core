"""Ticket service boundary tests; no site data is created."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class TicketTests(unittest.TestCase):
    def setUp(self):
        def throw(message, exception=ValueError): raise exception(message)
        self.f = types.SimpleNamespace(get_roles=lambda: ['Relay Communication User'], throw=throw, whitelist=lambda **kw: lambda fn: fn, get_doc=Mock())
        spec = importlib.util.spec_from_file_location('tested_tickets', Path('relay_core/tickets.py'))
        self.api = types.ModuleType('relay_core.api')
        def reference(value, prefix):
            import re
            if not isinstance(value, str) or not re.fullmatch('RELAY-'+prefix+'-[0-9]{10}', value):
                throw('Invalid reference')
        self.api.validate_reference = reference
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'frappe':self.f, 'relay_core.api':self.api}):
            spec.loader.exec_module(self.module)
        self.module.require_access = Mock()
        self.module.readable_contact = Mock()
        self.message = types.SimpleNamespace(name='RELAY-MSG-0000000001',relay_contact='RELAY-CON-0000000001',channel='RELAY-CH-0000000001',check_permission=Mock())
        self.contact = types.SimpleNamespace(check_permission=Mock())
        self.f.get_doc.side_effect = lambda doctype, name: self.message if doctype == 'Relay Message' else self.contact
        self.doc = types.SimpleNamespace(subject='Payment query', brief='Review attached evidence',category='Payment evidence',status='Open',messages=[types.SimpleNamespace(message=self.message.name)])

        self.doc.get_doc_before_save=lambda:None
        self.doc.get=lambda key:getattr(self.doc,key,None)
        self.f.PermissionError = PermissionError

    def test_each_link_requires_message_and_contact_read_permission(self):
        self.module.validate_ticket(self.doc)
        self.message.check_permission.assert_called_once_with('read')
        self.module.readable_contact.assert_called_once_with(self.message.relay_contact)
        self.message.check_permission.side_effect=PermissionError
        with self.assertRaises(PermissionError): self.module.validate_ticket(self.doc)

    def test_duplicate_and_oversize_message_lists_rejected(self):
        self.doc.messages *= 2
        with self.assertRaises(ValueError): self.module.validate_ticket(self.doc)
        self.doc.messages *= 26
        with self.assertRaises(ValueError): self.module.validate_ticket(self.doc)

    def test_invalid_status_or_category_rejected(self):
        self.doc.status='anything'
        with self.assertRaises(ValueError): self.module.validate_ticket(self.doc)
        self.doc.status='Open';self.doc.category='anything'
        with self.assertRaises(ValueError): self.module.validate_ticket(self.doc)

    def test_api_rejects_unbounded_or_malformed_create_before_insert(self):
        for messages in ([], ['x']*51, [{}], True):
            with self.assertRaises(ValueError): self.module.create('subject',messages)
        self.f.get_doc.assert_not_called()

    def test_read_rechecks_access_instead_of_exposing_stale_links(self):
        self.doc.name='RELAY-TKT-0000000001';self.doc.check_permission=Mock()
        self.f.get_doc.side_effect=lambda doctype,name: self.doc if doctype=='Relay Ticket' else self.message if doctype=='Relay Message' else self.contact
        self.doc.creation = '2026-10-24 09:00:00'
        result=self.module.read(self.doc.name)
        self.assertEqual(result['creation'], self.doc.creation)
        self.assertEqual(result['messages'][0]['message'],self.message.name)
        self.doc.check_permission.assert_called_once_with('read')
        self.doc.check_permission.side_effect=PermissionError
        with self.assertRaises(PermissionError):self.module.read(self.doc.name)


    def test_directory_applies_business_assignee_category_and_status_filters(self):
        self.f.get_list = Mock(return_value=[])
        self.module.directory(business_doctype='Supplier', business_name='SUP-A', assigned_to='agent', category='Support', status='Open')
        self.assertEqual(self.f.get_list.call_args.kwargs['filters'], dict(business_doctype='Supplier',
            business_name='SUP-A', assigned_to='agent', category='Support', status='Open'))

    def test_business_tag_cannot_differ_from_linked_conversation(self):
        self.doc.business_doctype = 'Supplier'; self.doc.business_name = 'SUP-B'
        access = types.SimpleNamespace(reference=lambda doc: ('Supplier', 'SUP-A'))
        with patch.dict(sys.modules, {'relay_core.business_access': access}):
            with self.assertRaises(ValueError): self.module.validate_ticket(self.doc)

    def test_episode_scope_cannot_be_cleared_or_forged_in_document_saves(self):
        original = Record(company='Sim Company', conversation_key='Sim Conversation',
            active_scope_key='Sim Scope', source_action_key='Sim Source', generation=7, ai_disabled=1)
        self.doc.get_doc_before_save = lambda: original
        for changes in ({'company': None}, {'conversation_key': ''}, {'active_scope_key': None},
                {'generation': 0}, {'ai_disabled': 0}, {'skill_version': 'Forged'},
                {'company': None, 'conversation_key': None, 'active_scope_key': None}):
            with self.subTest(changes=changes):
                for key, value in (original | changes).items(): setattr(self.doc, key, value)
                with self.assertRaises(PermissionError): self.module.validate_ticket(self.doc)
        self.doc.get_doc_before_save = lambda: None
        self.doc.company = 'Sim Company'
        with self.assertRaises(PermissionError): self.module.validate_ticket(self.doc)


class Record(dict):
    def __getattr__(self, key):
        return self.get(key)

    def __setattr__(self, key, value):
        self[key] = value


class EpisodeTests(unittest.TestCase):
    def setUp(self):
        TicketTests.setUp(self)
        self.message = Record(name='RELAY-MSG-0000000001', channel='Sim Channel',
            relay_contact='Sim Contact', sender_endpoint='sim@example.invalid',
            conversation_key='Sim Conversation', provider_message_key='Sim Provider Key')
        self.scope = dict(company='Sim Company', conversation_key='Sim Conversation',
                          business_doctype='Customer', business_name='Sim Customer')
        self.ticket = None
        self.module._episode_scope = Mock(return_value=(self.scope, 'scope-key'))
        self.module._lock_episode_routing = Mock()
        self.module.episode_owner_allowed = Mock(return_value=True)
        self.f.QueryDeadlockError = type("QueryDeadlockError", (Exception,), {})
        self.f.db = Mock()
        self.f.db.get_value.side_effect = self.lookup
        self.f.db.set_value.side_effect = self.set_value
        self.f.get_doc.side_effect = self.get_doc
        self.module.require_access = Mock()
        self.permissions = types.SimpleNamespace(require_administrator=Mock())
        self.patcher = patch.dict(sys.modules, {'relay_core.permissions': self.permissions})
        self.patcher.start(); self.addCleanup(self.patcher.stop)

    def lookup(self, doctype, filters, *args, **kwargs):
        if doctype == 'Relay Ticket' and self.ticket and all(self.ticket.get(k) == v for k,v in filters.items()):
            return self.ticket.name

    def set_value(self, doctype, name, key, value, **kwargs):
        if doctype == 'Relay Message': self.message[key] = value

    def get_doc(self, doctype, name=None, **kwargs):
        if isinstance(doctype, dict):
            self.ticket = Record(doctype, name='RELAY-TKT-0000000001')
            self.ticket.insert = Mock(return_value=self.ticket)
            self.ticket.save = Mock(return_value=self.ticket)
            return self.ticket
        return self.message if doctype == 'Relay Message' else self.ticket

    def test_same_source_replays_closed_released_ticket_without_reopening(self):
        ticket = self.module.ensure_episode(self.message, owner='Sim Agent')
        key = ticket.source_action_key
        ticket.status, ticket.active_scope_key = 'Closed', None
        self.module.ensure_episode(self.message, owner='Sim Agent')
        self.assertEqual(ticket.source_action_key, key)
        self.assertEqual(ticket.status, 'Closed')
        ticket.insert.assert_called_once()

    def test_replay_preserves_staff_assignment_even_if_automatic_owner_is_unavailable(self):
        ticket = self.module.ensure_episode(self.message, owner='Sim Agent')
        ticket.assigned_to, ticket.status = 'Sim Staff', 'Closed'
        self.module.episode_owner_allowed.side_effect = lambda user, message: user == 'Sim Staff'
        self.module.ensure_episode(self.message, owner='Unavailable automatic owner')
        self.assertEqual((ticket.assigned_to, ticket.status), ('Sim Staff', 'Closed'))
        self.module.episode_owner_allowed.return_value = False
        self.module.episode_owner_allowed.side_effect = None
        with self.assertRaisesRegex(ValueError, 'authorized assignment'):
            self.module.ensure_episode(self.message, owner='Sim Agent')
        self.assertEqual(ticket.assigned_to, 'Sim Staff')

    def test_failed_transition_cannot_authorize_a_later_document_save(self):
        ticket = self.module.ensure_episode(self.message, owner='Sim Agent')
        ticket.save.side_effect = ValueError('Local validation failure')
        with self.assertRaises(ValueError): self.module.ensure_episode(self.message, owner='Sim Agent')
        self.assertIsNone(self.module._episode_transition.get())

    def test_new_message_reopens_hold_and_reuses_active_scope_without_growing_evidence(self):
        ticket = self.module.ensure_episode(self.message, owner='Sim Agent')
        ticket.status, ticket.ai_disabled, ticket.generation = 'Closed', 1, 9
        self.message.update(name='RELAY-MSG-0000000002', ticket=None, provider_message_key='Second source')
        result = self.module.ensure_episode(self.message, owner='Sim Agent')
        self.assertIs(result, ticket)
        self.assertEqual((ticket.status, ticket.ai_disabled, ticket.generation), ('Open', 1, 9))
        self.assertEqual(len(ticket.messages), 1)

    def test_released_scope_creates_new_episode_only_for_new_source(self):
        first = self.module.ensure_episode(self.message, owner='Sim Agent')
        first.active_scope_key = None
        self.message.update(name='RELAY-MSG-0000000002', ticket=None, provider_message_key='Second source')
        second = self.module.ensure_episode(self.message, owner='Sim Agent')
        self.assertIsNot(first, second)
        self.assertNotEqual(first.source_action_key, second.source_action_key)

    def test_assignment_failure_rolls_back_without_link_or_ticket(self):
        self.module.episode_owner_allowed.return_value = False
        with self.assertRaisesRegex(ValueError, 'owner'):
            self.module.ensure_episode(self.message, owner='Disabled')
        self.assertIsNone(self.ticket)
        self.f.db.set_value.assert_not_called()
        self.f.db.rollback.assert_called_once_with(save_point='ensure_episode')

    def test_linked_ticket_scope_mismatch_fails_closed(self):
        ticket = self.module.ensure_episode(self.message, owner='Sim Agent')
        ticket.company = 'Other Company'
        with self.assertRaisesRegex(ValueError, 'scope'):
            self.module.ensure_episode(self.message, owner='Sim Agent')

    def test_changed_message_scope_is_rejected_before_assignment(self):
        self.module._episode_scope.side_effect = [(self.scope, 'scope'), (self.scope, 'changed')]
        with self.assertRaisesRegex(ValueError, 'scope changed'):
            self.module.ensure_episode(self.message, owner='Sim Agent')
        self.module.episode_owner_allowed.assert_not_called()

    def test_retryable_database_error_is_not_masked_by_missing_savepoint(self):
        self.module._lock_episode_routing.side_effect = self.f.QueryDeadlockError('retry transaction')
        with self.assertRaises(self.f.QueryDeadlockError):
            self.module.ensure_episode(self.message, owner='Sim Agent')
        self.f.db.rollback.assert_not_called()

    def test_legacy_linked_handoff_keeps_original_key_and_gains_episode_scope(self):
        ticket = self.module.ensure_episode(self.message, owner='Sim Agent')
        ticket.conversation_key = None
        ticket.active_scope_key = None
        ticket.messages = [Record(message=self.message.name)]
        key = ticket.source_action_key
        self.module.ensure_episode(self.message, owner='Sim Agent')
        self.assertEqual(ticket.source_action_key, key)
        self.assertEqual(ticket.conversation_key, self.scope['conversation_key'])
        self.assertEqual(ticket.active_scope_key, 'scope-key')

    def test_run_cannot_reassign_another_source(self):
        run = Record(name='Sim Run', message='Other source')
        with self.assertRaisesRegex(ValueError, 'another source'):
            self.module.ensure_episode(self.message, owner='Sim Agent', run=run)
        self.assertIsNone(self.ticket)

    def test_message_link_advances_version_and_replay_does_not_rewrite_it(self):
        ticket = self.module.ensure_episode(self.message, owner='Sim Agent')
        self.f.db.set_value.assert_called_once_with('Relay Message', self.message.name, 'ticket', ticket.name)
        self.module.ensure_episode(self.message, owner='Sim Agent')
        self.f.db.set_value.assert_called_once()


class TranscriptTests(unittest.TestCase):
    def setUp(self):
        TicketTests.setUp(self)
        self.ticket = Record(name='RELAY-TKT-0000000001', check_permission=Mock(),
            conversation_key='Sim Conversation', business_doctype='Customer', business_name='Sim Customer')
        self.rows = [Record(name=f'RELAY-MSG-{i:010d}', ticket=self.ticket.name,
            conversation_key=self.ticket.conversation_key, business_doctype='Customer', business_name='Sim Customer',
            relay_contact='Sim Contact', channel='Sim Channel', content='Quantity 25, amount 1250',
            check_permission=Mock(), apply_fieldlevel_read_permissions=Mock()) for i in range(1, 62)]
        self.f.get_doc.side_effect = lambda dt, name: self.ticket if dt == 'Relay Ticket' else (
            next(row for row in self.rows if row.name == name) if dt == 'Relay Message' else Record(check_permission=Mock()))
        self.f.get_list = Mock(side_effect=lambda dt, **kw: [r for r in self.rows if not kw['filters'].get('name')
            or r.name > kw['filters']['name'][1]][:kw['page_length']])

    def test_transcript_over_fifty_uses_bounded_keyset_pages(self):
        first = self.module.transcript(self.ticket.name)
        second = self.module.transcript(self.ticket.name, **first['next'])
        self.assertEqual((len(first['items']), len(second['items']), second['next']), (50, 11, None))
        self.assertEqual(len({row['name'] for row in first['items']+second['items']}), 61)
        self.assertEqual(set(first), {'items', 'next'})
        self.rows[0].apply_fieldlevel_read_permissions.assert_called_once()

    def test_transcript_checks_ticket_message_scope_and_cursor(self):
        self.ticket.check_permission.side_effect = PermissionError
        with self.assertRaises(PermissionError): self.module.transcript(self.ticket.name)
        self.ticket.check_permission.side_effect = None
        self.rows[0].check_permission.side_effect = PermissionError
        with self.assertRaises(PermissionError): self.module.transcript(self.ticket.name)
        self.rows[0].check_permission.side_effect = None
        self.f.PermissionError = PermissionError
        self.f.throw = lambda message, *args: (_ for _ in ()).throw(PermissionError(message))
        self.rows[0].ticket = 'Other'
        with self.assertRaises(PermissionError): self.module.transcript(self.ticket.name, after=self.rows[0].name)
        self.rows[0].ticket = self.ticket.name
        self.rows[0].business_name = 'Other Business'
        with self.assertRaises(PermissionError): self.module.transcript(self.ticket.name)

    def test_transcript_rejects_invalid_page_limits(self):
        for limit in (0, 101, True, 'bad', -1):
            with self.assertRaises(ValueError): self.module.transcript(self.ticket.name, limit=limit)


class CompanyPermissionTests(unittest.TestCase):
    def setUp(self):
        from relay_core import permissions
        self.module = permissions
        self.f = types.SimpleNamespace(session=Record(user='Sim Agent'), has_permission=Mock(return_value=True),
            qb=types.SimpleNamespace(get_query=Mock()), get_doc=Mock())
        self.f.qb.get_query.return_value.run.return_value = [('Sim Company',)]
        self.f.qb.get_query.return_value.get_sql.return_value = 'SELECT name FROM allowed_companies'
        self.f.get_doc.return_value.has_permission.return_value = True
        self.patcher = patch.dict(sys.modules, {'frappe': self.f})
        self.patcher.start(); self.addCleanup(self.patcher.stop)

    def test_company_requires_query_and_document_permission(self):
        self.assertTrue(self.module.company_allowed('Sim Company'))
        self.f.qb.get_query.return_value.run.return_value = []
        self.assertFalse(self.module.company_allowed('Other Company'))
        self.f.qb.get_query.return_value.run.return_value = [('Sim Company',)]
        self.f.get_doc.return_value.has_permission.return_value = False
        self.assertFalse(self.module.company_allowed('Sim Company'))
        self.assertFalse(self.module.company_allowed(None))

    def test_company_query_filters_before_pagination_and_preserves_manual_tickets(self):
        condition = self.module.company_condition('Relay Ticket')
        self.assertIn('company IN (SELECT name FROM allowed_companies)', condition)
        self.f.has_permission.return_value = False
        self.assertFalse(self.module.company_allowed('Sim Company'))
        self.assertEqual(self.module.company_condition('Relay Ticket'), "COALESCE(`tabRelay Ticket`.company,'')=''")
        self.assertEqual(self.module.company_condition('Relay Ticket', 'Administrator'), '1=1')


class EpisodeScopeTests(unittest.TestCase):
    def setUp(self):
        TicketTests.setUp(self)
        self.f.local = Record(site='yrp.site')
        self.f.db = Mock()
        self.f.db.get_value.return_value = 'Sim Company'
        self.message = Record(name='RELAY-MSG-0000000001', relay_contact='Sim Contact', channel='Sim Channel',
            conversation_key='Sim Conversation', sender_endpoint='sim@example.invalid')
        self.business = types.SimpleNamespace(reference=Mock(return_value=('Customer','Shared Party')))
        self.provenance = types.SimpleNamespace(context_of=lambda doc: {}, conversation_key=lambda *args:'Fallback conversation')
        self.patch = patch.dict(sys.modules, {'relay_core.business_access':self.business,
            'relay_core.automation.provenance':self.provenance})
        self.patch.start(); self.addCleanup(self.patch.stop)

    def test_scope_separates_site_company_business_type_and_contact(self):
        scope, original = self.module._episode_scope(self.message)
        self.assertEqual(scope['company'], 'Sim Company')
        self.message.generation = 20
        self.assertEqual(self.module._episode_scope(self.message)[1], original)
        self.business.reference.return_value = ('Supplier','Shared Party')
        self.assertNotEqual(self.module._episode_scope(self.message)[1], original)
        self.business.reference.return_value = ('Customer','Shared Party')
        self.f.db.get_value.return_value = 'Other Company'
        self.assertNotEqual(self.module._episode_scope(self.message)[1], original)
        self.f.db.get_value.return_value = 'Sim Company'
        self.f.local.site = 'other.local'
        self.assertNotEqual(self.module._episode_scope(self.message)[1], original)
        self.f.local.site = 'yrp.site'; self.message.relay_contact = 'Other Contact'
        self.assertNotEqual(self.module._episode_scope(self.message)[1], original)

    def test_incomplete_scope_cannot_create_an_episode(self):
        self.f.db.get_value.return_value = None
        with self.assertRaises(ValueError): self.module._episode_scope(self.message)
        self.f.db.get_value.return_value = 'Sim Company'
        self.business.reference.return_value = None
        with self.assertRaises(ValueError): self.module._episode_scope(self.message)

    def test_existing_routing_mutex_rejects_identity_changes(self):
        self.f.get_doc.side_effect = None
        self.f.get_doc.return_value = Record(relay_contact='Other Contact', channel='Sim Channel', endpoint='sim@example.invalid')
        automation = types.SimpleNamespace(internal_save=Mock())
        with patch.dict(sys.modules, {'relay_core.automation.service':automation}):
            with self.assertRaisesRegex(ValueError, 'routing identity'):
                self.module._lock_episode_routing(self.message, 'Sim Conversation')
        self.f.get_doc.assert_called_once_with('Relay Business Routing', 'Sim Company', for_update=True)
        automation.internal_save.assert_not_called()

    def test_concurrent_unique_routing_insert_reuses_the_winner(self):
        self.f.DuplicateEntryError = type('DuplicateEntryError', (Exception,), {})
        self.f.UniqueValidationError = type('UniqueValidationError', (Exception,), {})
        self.f.db.get_value.side_effect = [None, 'Sim Routing Winner']
        self.f.get_doc.side_effect = None
        self.f.get_doc.return_value = Record(relay_contact='Sim Contact', channel='Sim Channel', endpoint='sim@example.invalid')
        automation = types.SimpleNamespace(internal_save=Mock(side_effect=self.f.UniqueValidationError()))
        with patch.dict(sys.modules, {'relay_core.automation.service':automation}):
            self.module._lock_episode_routing(self.message, 'Sim Conversation')
        self.f.db.rollback.assert_called_once_with(save_point='episode_routing')
        self.f.get_doc.assert_called_with('Relay Business Routing', 'Sim Routing Winner', for_update=True)
