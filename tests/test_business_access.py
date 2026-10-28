"""Action ownership compatibility and scoped email prompt ancestry."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from frappe import _dict
from relay_core import business_access as access
from relay_core.automation.provenance import conversation_key


class ActionPermissionTests(unittest.TestCase):
    def setUp(self):
        self.source = _dict(has_permission=Mock(return_value=True))
        self.fake = SimpleNamespace(session=SimpleNamespace(user='sender'), get_doc=Mock(return_value=self.source),
                                    DoesNotExistError=LookupError, permissions=SimpleNamespace(has_permission=Mock(
                                        side_effect=lambda doctype, ptype, doc, user=None, print_logs=True: doc.has_permission(ptype, user=user))))
        self.enterContext(patch.object(access, 'frappe', self.fake))
        self.reference = self.enterContext(patch.object(access, 'reference', return_value=('Customer', 'C1')))
        self.action = _dict(owner='sender', payload='{}', source_message='source')

    def test_legacy_reads_require_source_permissions_for_the_requested_user(self):
        self.assertTrue(access.action_permission(self.action))
        self.source.has_permission.assert_called_with('read', user='sender')
        self.source.has_permission.return_value = False
        self.assertFalse(access.action_permission(self.action))
        self.assertFalse(access.action_permission(self.action, user='other'))

    def test_ticket_access_uses_its_business_without_a_contact(self):
        ticket = _dict(doctype='Relay Ticket', business_doctype='Customer', business_name='C1')
        with patch.object(access, 'candidates', side_effect=AssertionError('a ticket has no contact')):
            self.assertTrue(access.allowed(ticket, user='sender'))
            self.assertFalse(self.fake.permissions.has_permission.call_args.kwargs['print_logs'], 'A probe must not add denial text')
            self.source.has_permission.return_value = False
            self.assertFalse(access.allowed(ticket, user='sender'))
        message = _dict(doctype='Relay Message', relay_contact='contact', business_doctype='Customer', business_name='C1')
        with patch.object(access, 'candidates', return_value=[]):
            self.source.has_permission.return_value = True
            self.assertFalse(access.allowed(message, user='sender'), 'A message still needs the Contact link')

    def test_legacy_ambiguity_missing_source_and_partial_snapshots_fail_closed(self):
        self.reference.return_value = None
        self.assertFalse(access.action_permission(self.action))
        self.fake.get_doc.side_effect = LookupError
        self.assertFalse(access.action_permission(self.action))
        self.action.source_message = None
        self.assertFalse(access.action_permission(self.action))
        self.action.source_message = 'source'
        self.action.payload = json.dumps({'business': ['Customer', None]})
        self.fake.get_doc.reset_mock()
        self.assertFalse(access.action_permission(self.action))
        self.fake.get_doc.assert_not_called()

    def test_explicit_snapshot_never_falls_back_to_readable_shared_contact(self):
        self.action.payload = json.dumps({'business': ['Supplier', 'S1']})
        self.source.has_permission.return_value = False
        self.assertFalse(access.action_permission(self.action))
        self.fake.get_doc.assert_called_once_with('Supplier', 'S1')
        self.reference.assert_not_called()


    def test_unlinked_start_belongs_to_its_sender_while_the_contact_has_no_records(self):
        self.action.update(payload=json.dumps({'start': {'contact': 'RC1'}}), start_contact='RC1', source_message=None)
        with patch.object(access, 'candidates', return_value=[]):
            self.assertTrue(access.action_permission(self.action))
            self.fake.get_doc.assert_called_with('Relay Contact', 'RC1')
            self.assertFalse(access.action_permission(self.action, user='other'))
            self.source.has_permission.return_value = False
            self.assertFalse(access.action_permission(self.action))
        self.source.has_permission.return_value = True
        with patch.object(access, 'candidates', return_value=[('Customer', 'C1')]):
            self.assertFalse(access.action_permission(self.action), 'A contact linked later needs the record')

class EmailPromptScopeTests(unittest.TestCase):
    def test_prompt_context_must_match_routing_and_its_original_thread(self):
        context = {'provider': 'Email', 'message_id': '<root@example.invalid>', 'email_thread_id': '<root@example.invalid>'}
        key = conversation_key('channel', 'person@example.invalid', context)
        payload = {'routing': key, 'context': context}
        row = _dict(payload=json.dumps(payload), conversation_key=key)
        db = Mock(); db.sql.return_value = [row]
        with patch.object(access, 'frappe', SimpleNamespace(db=db)):
            self.assertEqual(list(access.email_prompt_contexts('contact', 'channel', 'person@example.invalid', '<prompt@example.invalid>')), [context])
            self.assertEqual(db.sql.call_args.args[1], ('contact', 'channel', 'contact', 'channel', 'person@example.invalid', '<prompt@example.invalid>'))
            self.assertEqual(list(access.email_prompt_contexts('contact', 'other-channel', 'person@example.invalid', '<prompt@example.invalid>')), [])
            payload['routing'] = 'another-thread'; row.payload = json.dumps(payload)
            self.assertEqual(list(access.email_prompt_contexts('contact', 'channel', 'person@example.invalid', '<prompt@example.invalid>')), [])


class LegacyAdmissionTests(unittest.TestCase):
    def test_empty_snapshots_recover_but_partial_or_changed_ownership_cannot(self):
        from relay_core import messaging, ticket_notifications
        source = _dict(business_doctype='Customer', business_name='C1')
        with patch.object(messaging, 'action_target', return_value=(source, None, {})), \
                patch.object(ticket_notifications, 'authorize_action'):
            for snapshot in (None, [None, None], ['', '']):
                self.assertIs(messaging.admission_scope(_dict(payload={'business': snapshot}))[0], source)
            for snapshot in (['Customer', None], [None, 'C1'], ['Supplier', 'S1']):
                with self.assertRaises(ValueError):
                    messaging.admission_scope(_dict(payload={'business': snapshot}))


class LegacyEmailAncestryTests(unittest.TestCase):
    def setUp(self):
        from relay_core.message_updates import provider_key
        self.docs = {}
        self.fake = SimpleNamespace(db=Mock(), get_doc=lambda dt, name: self.docs[name])
        self.fake.db.get_value.side_effect = lambda dt, filters, field: next((name for name in self.docs
            if filters['provider_message_key'] == provider_key('channel', 'sender', name)), None)
        self.enterContext(patch.object(access, 'frappe', self.fake))
        self.enterContext(patch.object(access, 'email_prompt_contexts', return_value=[]))

    def add(self, name, refs=(), business='C1'):
        self.docs[name] = _dict(business_doctype='Customer', business_name=business,
            provider_context={'provider': 'Email', 'message_id': name, 'references': list(refs)})

    def resolve(self, refs):
        context = {'references': refs, 'reply_to_message_id': refs[-1]}
        business = access.email_reference('contact', 'channel', 'sender', context, [('Customer', 'C1'), ('Customer', 'C2')])
        return business, context

    def test_multiple_legacy_messages_resolve_one_validated_root(self):
        self.add('root'); self.add('reply', ['root']); self.add('next', ['root', 'reply'])
        business, context = self.resolve(['root', 'reply', 'next'])
        self.assertEqual(business, ('Customer', 'C1'))
        self.assertEqual(context['email_thread_id'], 'root')

    def test_different_threads_businesses_cycles_and_unlinked_ancestry_fail_closed(self):
        self.add('root'); self.add('other'); self.add('reply', ['root'])
        self.assertEqual(self.resolve(['reply', 'other'])[1]['business_rule'], 'triage_conflicting_references')
        self.add('reply', ['root'], business='C2')
        self.assertEqual(self.resolve(['reply'])[1]['business_rule'], 'triage_conflicting_references')
        self.add('root', ['reply']); self.add('reply', ['root'])
        self.assertEqual(self.resolve(['reply'])[1]['business_rule'], 'triage_conflicting_references')
        self.add('root', business='unlinked')
        self.assertEqual(self.resolve(['root'])[1]['business_rule'], 'triage_unlinked_reference')

    def test_legacy_ancestry_is_bounded_and_fails_closed(self):
        for index in range(101):
            self.add(str(index), [str(index - 1)] if index else [])
        business, context = self.resolve(['100'])
        self.assertIsNone(business)
        self.assertEqual(context['business_rule'], 'triage_conflicting_references')
        self.assertLessEqual(self.fake.db.get_value.call_count, 100)
