import json
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from frappe import _dict
from relay_core import business_access, business_routing as routing, business_routing_prompt as prompts


class RoutingFixtures:
    def setUp(self):
        self.now = datetime(2026, 10, 24, 12)
        self.links = [('Customer', 'customer-one'), ('Supplier', 'supplier-two')]
        self.states, self.actions, self.references = {}, {}, {}
        self.verified = True
        self.db = Mock()
        self.db.get_value.side_effect = self.get_value
        self.fake = SimpleNamespace(session=_dict(user='callback-service'), db=self.db, get_doc=self.get_doc, enqueue=Mock(), _dict=_dict,
            utils=SimpleNamespace(now_datetime=lambda: self.now,
                get_datetime=lambda value: value if isinstance(value, datetime) else datetime.fromisoformat(value),
                convert_utc_to_system_timezone=lambda value: value))
        self.fake.set_user = lambda user: setattr(self.fake.session, 'user', user)
        for module in (business_access, routing, prompts):
            self.enterContext(patch.object(module, 'frappe', self.fake))
        for module in (business_access, routing, prompts):
            self.enterContext(patch.object(module, 'candidates', side_effect=lambda contact: list(self.links)))
        for module in (routing, prompts):
            self.enterContext(patch.object(module, 'internal_save', side_effect=self.save))
        self.enterContext(patch.object(prompts, 'require_access'))
        self.enterContext(patch.object(prompts, 'connection_value', return_value='account'))

    def get_value(self, dt, filters, fields=None, **kwargs):
        if dt == 'Relay Contact Endpoint':
            if not self.verified:
                return None
            return _dict(name='binding', relay_contact='contact') if isinstance(fields, list) else 'contact'
        if dt == 'Relay Business Routing':
            return filters['conversation_key'] if filters['conversation_key'] in self.states else None
        if dt == 'Relay Message Action':
            return self.actions[filters].status
        if dt == 'Relay Message':
            return self.references.get(filters['provider_message_key'])
        raise AssertionError(dt)

    def get_doc(self, dt, name=None, **kwargs):
        if isinstance(dt, dict):
            return _dict(dt)
        if dt == 'Relay Business Routing':
            return self.states[name]
        if dt == 'Relay Channel':
            return _dict(name=name, channel='WhatsApp', enabled=1, account='account')
        if (dt, name) in self.links:
            return _dict(name=name, title=name, meta=_dict(title_field='title'))
        raise AssertionError((dt, name))

    def save(self, doc, new=False):
        if doc.doctype == 'Relay Business Routing':
            doc.name = doc.conversation_key
            self.states[doc.name] = doc
        else:
            doc.owner = self.fake.session.user
            doc.name = 'action-' + str(len(self.actions) + 1)
            self.actions[doc.name] = doc
        return doc

    def resolve(self, identifier='message', context=None, selection=None, creation=None, timestamp=None, override=None,
                event_name='event', position=0):
        context = {'provider': 'WhatsApp', **(context or {})}
        row = {'id': identifier, 'timestamp': str(int((timestamp or self.now).timestamp())),
               'message_data': {'selection_id': selection} if selection else {}}
        event = _dict(name=event_name, creation=creation or self.now)
        return routing.resolve('contact', 'channel', '15550000001', context, row, event, override, position)

    def state(self):
        return next(iter(self.states.values()))


class RoutingTests(RoutingFixtures, unittest.TestCase):
    def test_unverified_email_never_uses_single_link_or_reply_context(self):
        self.links = self.links[:1]
        for status in ('fail', 'unverified', None):
            self.assertEqual(self.resolve(context={'provider':'Email', 'authentication':{'status':status},
                'in_reply_to':'<known@example.invalid>'}), (None, 'triage_unverified_sender'))
        self.assertEqual(self.states, {})
        self.assertEqual(self.actions, {})

    def test_prompt_once_even_across_replay_and_message_burst(self):
        for index in range(100):
            self.assertEqual(self.resolve(str(index)), (None, 'triage_prompt_pending'))
        self.assertEqual(len(self.actions), 1)
        self.assertEqual(next(iter(self.actions.values())).owner, 'Administrator')
        self.assertEqual(self.fake.session.user, 'callback-service')
        self.fake.enqueue.assert_called_once()
        self.assertTrue(self.fake.enqueue.call_args.kwargs['enqueue_after_commit'])
        choices = json.loads(self.state().choices)
        self.assertEqual({(r['doctype'], r['name']) for r in choices}, set(self.links))
        payload = json.loads(next(iter(self.actions.values())).payload)
        rows = payload['arguments']['interactive']['action']['sections'][0]['rows']
        self.assertEqual({r['id'] for r in rows}, {r['id'] for r in choices})
        self.assertTrue(all('customer' not in r['id'] and 'supplier' not in r['id'] for r in rows))
        self.assertTrue(any(call.kwargs.get('for_update') for call in self.db.get_value.call_args_list))

    def test_rejected_prompt_stays_in_triage_without_another_send(self):
        self.resolve()
        next(iter(self.actions.values())).status = 'Rejected'
        self.assertEqual(self.resolve('next'), (None, 'triage_prompt_rejected'))
        self.assertEqual(len(self.actions), 1)

    def test_choice_persists_and_original_request_and_following_messages_use_it(self):
        self.resolve('original')
        selected = json.loads(self.state().choices)[1]
        self.now += timedelta(seconds=1)
        self.assertEqual(self.resolve('choice', selection=selected['id']), (self.links[1], 'sender_choice'))
        self.now += timedelta(seconds=1)
        self.assertEqual(self.resolve('next'), (self.links[1], 'conversation'))
        self.assertEqual(self.resolve('original', creation=self.now - timedelta(seconds=1)), (self.links[1], 'conversation'))
        self.assertEqual(self.resolve('older', creation=self.now - timedelta(days=1)), (None, 'triage_prompt_pending'))
        self.assertEqual(self.resolve('stale-choice', selection=selected['id']), (None, 'triage_invalid_choice'))

    def test_verified_reply_context_precedes_selected_business(self):
        from relay_core.message_updates import provider_key
        self.resolve(override=self.links[0])
        self.references[provider_key('channel', '15550000001', 'outgoing')] = _dict(
            business_doctype='Supplier', business_name='supplier-two')
        self.assertEqual(self.resolve(context={'reply_to_message_id': 'outgoing'}), (self.links[1], 'reply_context'))
        filters = next(call.args[1] for call in self.db.get_value.call_args_list if call.args[0] == 'Relay Message')
        self.assertEqual(filters['relay_contact'], 'contact')
        self.assertIn('conversation_key', filters)
        self.assertFalse(self.actions)

    def test_revoked_or_foreign_choices_never_select_a_business(self):
        self.resolve()
        choice = json.loads(self.state().choices)[1]
        self.assertEqual(self.resolve(selection='relay-business:forged'), (None, 'triage_invalid_choice'))
        self.links[1] = ('Supplier', 'replacement')
        self.assertEqual(self.resolve(selection=choice['id']), (None, 'triage_invalid_choice'))
        self.assertFalse(self.state().business_name)

    def test_other_conversation_cannot_consume_choice(self):
        self.resolve()
        choice = json.loads(self.state().choices)[0]
        self.assertEqual(self.resolve(context={'message_thread_id': 2}, selection=choice['id']),
                         (None, 'triage_invalid_choice'))

    def test_revoked_choice_cannot_fall_through_to_the_remaining_business(self):
        self.resolve()
        choice = json.loads(self.state().choices)[1]
        self.links = self.links[:1]
        self.assertEqual(self.resolve(selection=choice['id']), (None, 'triage_invalid_choice'))
        self.assertEqual(self.resolve(selection='relay-business:forged'), (None, 'triage_invalid_choice'))
        self.assertFalse(self.state().selected_at)
        self.assertEqual(self.resolve('ordinary-message'), (self.links[0], 'single_link'))

    def test_following_messages_in_the_same_batch_use_the_choice(self):
        self.resolve('original', event_name='prompt-event')
        choice = json.loads(self.state().choices)[1]
        self.now += timedelta(seconds=1)
        self.assertEqual(self.resolve('before', position=0), (None, 'triage_prompt_pending'))
        self.assertEqual(self.resolve('choice', selection=choice['id'], position=1), (self.links[1], 'sender_choice'))
        self.assertEqual(self.resolve('after', position=2), (self.links[1], 'conversation'))
        self.assertEqual(self.resolve('before', position=0), (None, 'triage_prompt_pending'))
        self.assertEqual(self.resolve('other-batch', event_name='other-event', position=2),
                         (None, 'triage_prompt_pending'))

    def test_waiting_transaction_reads_the_committed_selection(self):
        self.resolve()
        stale = _dict(self.state())
        self.resolve(override=self.links[1])
        self.now += timedelta(seconds=1)
        def read(dt, filters, fields=None, **kwargs):
            if dt == 'Relay Business Routing' and not kwargs.get('for_update'):
                return None
            return self.get_value(dt, filters, fields, **kwargs)
        def document(dt, name=None, **kwargs):
            if dt == 'Relay Business Routing' and not kwargs.get('for_update'):
                return stale
            return self.get_doc(dt, name, **kwargs)
        self.db.get_value.side_effect = read
        with patch.object(self.fake, 'get_doc', side_effect=document):
            self.assertEqual(self.resolve('waiting-message'), (self.links[1], 'conversation'))
        self.assertEqual(len(self.actions), 1)

    def test_closed_window_future_clock_and_limit(self):
        self.assertEqual(self.resolve(timestamp=self.now - timedelta(hours=24)), (None, 'triage_window_closed'))
        self.assertEqual(self.resolve(timestamp=self.now + timedelta(days=1), creation=self.now - timedelta(days=2)),
                         (None, 'triage_window_closed'))
        self.links = [('Customer', str(i)) for i in range(11)]
        self.assertEqual(self.resolve(), (None, 'triage_no_prompt'))
        self.assertFalse(self.actions)

    def test_unsupported_channel_and_groups_stay_in_triage(self):
        for context in ({'provider': 'Email', 'authentication': {'status': 'pass'}}, {'provider': 'Telegram'}, {'group_id': 'group'}):
            self.assertEqual(self.resolve(context=context), (None, 'triage_no_prompt'))
        self.assertFalse(self.actions)

    def test_manager_selection_is_channel_neutral_and_rejects_unlinked_business(self):
        with self.assertRaises(ValueError):
            self.resolve(override=('Customer', 'stranger'))
        self.assertEqual(self.resolve(context={'provider': 'Email', 'authentication': {'status': 'pass'}}, override=self.links[1]), (self.links[1], 'manager'))
        self.now += timedelta(seconds=1)
        self.assertEqual(self.resolve(context={'provider': 'Email', 'authentication': {'status': 'pass'}}), (self.links[1], 'conversation'))
        self.assertFalse(self.actions)

    def test_single_link_and_revoked_endpoint(self):
        self.links = self.links[:1]
        self.assertEqual(self.resolve(), (self.links[0], 'single_link'))
        self.verified = False
        self.assertEqual(self.resolve(), (None, 'triage_unverified'))
        self.assertFalse(self.actions)

    def test_dispatch_revalidates_links_binding_and_window(self):
        self.resolve()
        action = next(iter(self.actions.values()))
        self.assertEqual(prompts.target(action)[0].sender_endpoint, '15550000001')
        self.assertEqual(prompts.prepared(action)[0], 'whatsapp.execute')
        self.verified = False
        with self.assertRaises(ValueError): prompts.target(action)
        self.verified = True
        self.links = self.links[:1]
        with self.assertRaises(ValueError): prompts.prepared(action)
        self.links.append(('Supplier', 'supplier-two'))
        self.now += timedelta(hours=24)
        with self.assertRaises(ValueError): prompts.prepared(action)
        # Receipt reconciliation remains possible after the send window closes.
        self.assertEqual(prompts.target(action)[1].name, 'channel')


class RoutingBoundaryTests(unittest.TestCase):
    def test_deleted_business_links_are_not_choices(self):
        db = Mock()
        db.get_value.return_value = 'person'
        db.exists.side_effect = lambda dt, name: name == 'live'
        fake = SimpleNamespace(db=db, get_all=Mock(side_effect=[['Customer'], [
            _dict(link_doctype='Customer', link_name='live'),
            _dict(link_doctype='Customer', link_name='deleted'),
            _dict(link_doctype='Supplier', link_name='disabled'),
        ]]))
        with patch.object(business_access, 'frappe', fake):
            self.assertEqual(business_access.candidates('contact'), [('Customer', 'live')])
        self.assertEqual(db.exists.call_count, 2)

    def test_internal_dispatch_restores_callback_identity_even_on_failure(self):
        from relay_core import messaging
        action = _dict(operation='business_prompt', owner='Administrator')
        fake = SimpleNamespace(get_doc=Mock(return_value=action), set_user=Mock(),
                               session=SimpleNamespace(user='hub-service'))
        with patch.object(prompts, 'frappe', fake), patch.object(messaging, 'reconcile', side_effect=ValueError):
            with self.assertRaises(ValueError): prompts.dispatch('action')
        self.assertEqual([call.args[0] for call in fake.set_user.call_args_list], ['Administrator', 'hub-service'])
        action.operation = 'text'
        fake.set_user.reset_mock()
        with patch.object(prompts, 'frappe', fake):
            with self.assertRaises(ValueError): prompts.dispatch('action')
        fake.set_user.assert_not_called()

    def test_projection_records_the_rule_in_message_and_event(self):
        from relay_core.automation import projection
        from relay_core import whatsapp_templates
        payload = {'entry': [{'changes': [{'value': {'messages': [
            {'id': 'incoming', 'from': '15550000001', 'type': 'interactive',
             'interactive': {'list_reply': {'id': 'relay-business:choice', 'title': 'Supplier'}}},
            {'id': 'following', 'from': '15550000001', 'type': 'text', 'text': {'body': 'Order amount 125'}}
        ]}}]}]}
        event = _dict(name='event', account='account', projection_status='Pending', payload=json.dumps(payload))
        created = []
        def get_doc(dt, name=None):
            if isinstance(dt, str): return event
            doc = _dict(dt)
            doc.insert = Mock(return_value=doc)
            created.append(doc)
            return doc
        db = Mock()
        db.exists.return_value = False
        db.get_value.side_effect = lambda dt, *args, **kwargs: None if dt == 'Relay Ticket' else 'contact'
        fake = SimpleNamespace(db=db, get_doc=get_doc, get_all=Mock(return_value=['channel']))
        with patch.object(projection, 'frappe', fake), patch.object(projection, 'apply_updates', return_value='Ignored'), \
                patch('relay_core.bulk_updates.link_reply'), \
             patch('relay_core.tickets.source_episode', return_value=('provider-key', 'source-action')), \
             patch.object(whatsapp_templates, 'project', return_value=False), \
             patch.object(routing, 'resolve', side_effect=[(('Supplier', 'supplier'), 'sender_choice'),
                                                          (('Supplier', 'supplier'), 'conversation')]) as decide, \
             patch('relay_core.call_records.ingest', return_value=False), patch('relay_core.realtime.changed'):
            projection.project('event', business_overrides={'incoming': ('Supplier', 'supplier')})
        self.assertEqual(decide.call_args_list[0].args[-1], ('Supplier', 'supplier'))
        self.assertEqual([call.kwargs['position'] for call in decide.call_args_list], [0, 1])
        self.assertEqual(len(created), 2)
        self.assertEqual(created[0].business_doctype, 'Supplier')
        self.assertEqual(created[0].message_type, 'interactive')
        self.assertEqual(json.loads(created[0].provider_context)['business_rule'], 'sender_choice')
        self.assertEqual(json.loads(created[1].provider_context)['business_rule'], 'conversation')
        self.assertTrue(any(call.args[2:] == ('routing_decisions', '{"following": "conversation", "incoming": "sender_choice"}')
                            for call in db.set_value.call_args_list))

    def test_prompt_receipt_is_journaled_without_guessing_a_message_business(self):
        from relay_core import messaging
        action = _dict(name='action', operation='business_prompt', status='Queued', reload=Mock())
        fake = SimpleNamespace(db=Mock(), get_doc=Mock())
        with patch.object(messaging, 'frappe', fake), patch.object(messaging, 'internal_save') as save:
            result = messaging.finish(action, _dict(), _dict(channel='WhatsApp'), {},
                {'kind': 'text', 'text': 'Choose business'}, {'messages': [{'id': 'prompt'}]}, commit=False)
        self.assertEqual(result['status'], 'Submitted')
        self.assertEqual(json.loads(action.result)['messages'][0]['id'], 'prompt')
        fake.get_doc.assert_not_called()
        fake.db.commit.assert_not_called()
        save.assert_called_once_with(action)

    def test_prompt_cannot_be_manually_retried(self):
        from relay_core import messaging
        fake = SimpleNamespace(get_doc=Mock(return_value=_dict(operation='business_prompt', check_permission=Mock())),
                               throw=Mock(side_effect=ValueError('once')))
        with patch.object(messaging, 'frappe', fake), patch.object(messaging, 'require_access'):
            with self.assertRaisesRegex(ValueError, 'once'):
                messaging.retry('action')


class PromptRecoveryTests(unittest.TestCase):
    def setUp(self):
        from relay_core import messaging, conversation_start
        self.api = messaging
        self.payload = {'routing': 'conversation', 'tool': 'whatsapp.execute',
                        'arguments': {'operation': 'messages.interactive', 'to': '15550000001'},
                        'content': {'kind': 'text', 'text': 'Choose business'}}
        self.action = _dict(name='action', status='Dispatching', operation='business_prompt',
            request_key='stable-key', start_contact='contact', payload=json.dumps(self.payload),
            check_permission=Mock(), reload=Mock())
        self.fake = SimpleNamespace(get_doc=Mock(return_value=self.action), db=Mock())
        self.hub = Mock()
        self.enterContext(patch.object(messaging, 'frappe', self.fake))
        self.enterContext(patch.object(messaging, 'internal_save'))
        self.enterContext(patch.object(messaging, 'delivery_episodes', return_value=[]))
        self.enterContext(patch.object(conversation_start, 'action_target', return_value=(
            _dict(), _dict(channel='WhatsApp'), {})))
        self.enterContext(patch.object(messaging.whatsapp, 'client', return_value=self.hub))

    def test_crash_recovery_sends_same_prompt_identity_once(self):
        self.hub.call_tool.side_effect = [{'deliveries': []}, {'delivery': {'state': 'queued'}}]
        with patch.object(prompts, 'prepared', return_value=(self.payload['tool'], self.payload['arguments'])):
            result = self.api.reconcile('action')
        self.assertEqual(result['status'], 'Queued')
        self.assertEqual(self.hub.call_tool.call_args.args, (
            'whatsapp.execute', dict(self.payload['arguments'], request_key='stable-key')))
        self.hub.reset_mock()
        self.hub.call_tool.side_effect = None
        self.hub.call_tool.return_value = {'deliveries': [{'key': 'stable-key', 'state': 'submitted',
                                                          'result': {'messages': [{'id': 'prompt'}]}}]}
        self.assertEqual(self.api.reconcile('action')['status'], 'Submitted')
        self.hub.call_tool.assert_called_once_with('whatsapp.deliveries', {'request_key': 'stable-key'})

    def test_expired_prompt_is_rejected_without_sending(self):
        self.hub.call_tool.return_value = {'deliveries': []}
        with patch.object(prompts, 'prepared', side_effect=ValueError('expired')):
            self.assertEqual(self.api.reconcile('action')['status'], 'Rejected')
        self.hub.call_tool.assert_called_once_with('whatsapp.deliveries', {'request_key': 'stable-key'})

    def test_uncertain_prompt_is_never_blindly_resent(self):
        self.action.status = 'Uncertain'
        self.hub.call_tool.return_value = {'deliveries': []}
        with patch.object(prompts, 'prepared') as prepare:
            with self.assertRaises(ValueError): self.api.reconcile('action')
        prepare.assert_not_called()
        self.hub.call_tool.assert_called_once_with('whatsapp.deliveries', {'request_key': 'stable-key'})


class ChannelRoutingTests(RoutingFixtures, unittest.TestCase):
    def test_unlinked_reply_does_not_fall_back_to_remaining_business(self):
        from relay_core.message_updates import provider_key
        self.references[provider_key('channel', '15550000001', 'old')] = _dict(
            business_doctype='Supplier', business_name='supplier-two')
        self.links = self.links[:1]
        self.assertEqual(self.resolve(context={'reply_to_message_id': 'old'}), (None, 'triage_unlinked_reference'))

    def telegram(self, **extra):
        return {'provider': 'Telegram', 'chat_id': 15550000001, 'chat_type': 'private',
                'participant_id': 15550000001, 'message_id': 12, **extra}

    def email(self, thread='thread-one', **extra):
        return {'provider': 'Email', 'message_id': '<' + thread + '@example.invalid>',
                'email_thread_id': thread, 'authentication': {'status': 'pass'}, **extra}

    def test_text_prompt_expiry_and_scope(self):
        for context in (self.telegram(), self.email()):
            with self.subTest(provider=context['provider']):
                self.states.clear(); self.actions.clear()
                self.assertEqual(self.resolve(context=context), (None, 'triage_prompt_pending'))
                action = next(iter(self.actions.values()))
                payload = json.loads(action.payload)
                self.assertIn(payload['tool'], ('telegram.message', 'email.send'))
                token = json.loads(self.state().choices)[0]['id']
                row = {'id': 'selection', 'text': {'body': token}, 'message_data': {}}
                foreign = dict(context, email_thread_id='another', message_thread_id=3)
                self.assertEqual(routing.resolve('contact', 'channel', '15550000001', foreign, row,
                    _dict(name='selection', creation=self.now)), (None, 'triage_invalid_choice'))
                self.now += timedelta(hours=24)
                self.assertEqual(routing.resolve('contact', 'channel', '15550000001', context, row,
                    _dict(name='selection', creation=self.now)), (None, 'triage_invalid_choice'))

    def test_automatic_or_unauthenticated_email_does_not_prompt(self):
        for context in (self.email(auto_submitted=True), self.email(authentication={'status': 'unverified'})):
            expected = 'triage_no_prompt' if context.get('auto_submitted') else 'triage_unverified_sender'
            self.assertEqual(self.resolve(context=context), (None, expected))
        self.assertFalse(self.actions)

    def test_another_telegram_participant_cannot_select(self):
        context = self.telegram()
        self.resolve(context=context)
        token = json.loads(self.state().choices)[0]['id']
        row = {'id': 'selection', 'text': {'body': token}}
        self.assertEqual(routing.resolve('contact', 'channel', '15550000001', self.telegram(participant_id=22), row,
            _dict(name='selection', creation=self.now)), (None, 'triage_invalid_choice'))


class TriageEpisodeTests(unittest.TestCase):
    def setUp(self):
        from relay_core import tickets
        self.tickets = tickets
        self.channel = _dict(name='channel', account='account', enabled=1, company='Company North', triage_owner='primary')
        self.event = _dict(name='event', account='account')
        self.row = {'id':'provider-one', 'from':'sender@example.invalid', 'provider_context':{},
                    'text':{'body':'Private amount 1250, never copy to triage'}}
        self.created = []
        self.insert_error = None
        self.existing = None
        self.db = Mock()
        self.db.get_value.side_effect = lambda dt, *a, **kw: self.existing if dt == 'Relay Ticket' else True
        def get_doc(dt, name=None, **kwargs):
            if dt == 'Relay Channel': return self.channel
            if dt == 'Relay Ticket': return self.created[0]
            doc = _dict(dt); doc.name = 'ticket'; doc.insert = Mock(return_value=doc, side_effect=self.insert_error)
            self.created.append(doc)
            return doc
        self.fake = SimpleNamespace(db=self.db, get_doc=get_doc, local=_dict(site='local.site'),
            session=_dict(user='callback'), set_user=Mock(),
            get_single=Mock(return_value=_dict(ai_handoff_owner='backup')),
            PermissionError=PermissionError, DoesNotExistError=LookupError, ValidationError=ValueError)
        self.enterContext(patch.object(tickets, 'frappe', self.fake))
        self.enterContext(patch('frappe.utils.now_datetime', return_value='Sim time'))
        self.enterContext(patch('relay_core.permissions.require_administrator'))
        from contextlib import nullcontext
        self.enterContext(patch('relay_core.ai.tools.as_user', side_effect=lambda user:nullcontext()))

    def test_unknown_source_deduplicates_and_never_copies_payload(self):
        with patch.object(self.tickets, 'triage_owner', return_value='primary'):
            first = self.tickets.ensure_episode(event=self.event, channel='channel', row=self.row)
            self.existing = first.name
            self.event.name = 'duplicate-hub-event'
            again = self.tickets.ensure_episode(event=self.event, channel='channel', row=self.row)
        self.assertIs(again, first)
        self.assertEqual(first.company, 'Company North')
        self.assertEqual(first.assigned_to, 'primary')
        self.assertEqual((first.ai_disabled, first.generation), (1, 1))
        self.assertIsNone(first.ownership_actor)
        self.assertEqual(first.source_hub_event, 'event')
        self.assertNotIn('1250', json.dumps({k:v for k,v in first.items() if k != 'insert'}))
        self.assertEqual(len(self.created), 1)
        self.assertTrue(any(c.kwargs.get('for_update') for c in self.db.get_value.call_args_list))

    def test_missing_company_or_owner_retains_source_without_ticket(self):
        with patch.object(self.tickets, 'triage_owner', return_value=None):
            self.assertIsNone(self.tickets.ensure_episode(event=self.event, channel='channel', row=self.row))
        self.channel.company = None
        with patch.object(self.tickets, 'triage_owner') as owner:
            self.assertIsNone(self.tickets.ensure_episode(event=self.event, channel='channel', row=self.row))
        owner.assert_not_called()
        self.assertEqual(self.created, [])

    def test_owner_revoked_during_insert_rolls_back_ticket_not_source(self):
        self.insert_error = PermissionError('Owner lost company access')
        with patch.object(self.tickets, 'triage_owner', return_value='primary'):
            self.assertIsNone(self.tickets.ensure_episode(event=self.event, channel='channel', row=self.row))
        self.db.rollback.assert_called_once_with(save_point='triage_episode')
        self.assertEqual(self.fake.set_user.call_args.args, ('callback',))

    def test_company_and_business_denial_selects_backup_or_stops(self):
        with patch.object(self.tickets, 'require_access'), \
                patch('relay_core.permissions.company_allowed', side_effect=[False, True]):
            self.assertEqual(self.tickets.triage_owner(self.channel), 'backup')
        with patch.object(self.tickets, 'require_access'), \
                patch('relay_core.permissions.company_allowed', return_value=True), \
                patch.object(self.tickets, 'episode_owner_allowed', side_effect=[False, True]):
            self.assertEqual(self.tickets.triage_owner(self.channel, _dict(name='message')), 'backup')
        self.db.get_value.side_effect = lambda *a, **kw: False
        self.assertIsNone(self.tickets.triage_owner(self.channel))

    def test_provider_identity_not_body_controls_replay(self):
        first = self.tickets.source_episode('channel', self.row)
        self.row['text']['body'] = 'Different untrusted instructions'
        self.assertEqual(self.tickets.source_episode('channel', self.row), first)
        self.row['id'] = 'provider-two'
        self.assertNotEqual(self.tickets.source_episode('channel', self.row), first)
        self.assertNotEqual(self.tickets.source_episode('other-channel', self.row), first)

    def test_empty_evidence_requires_a_complete_source_and_company(self):
        doc = _dict(subject='Triage', brief='', category='Support', status='Open', messages=[],
                    get_doc_before_save=lambda:None)
        self.fake.throw = Mock(side_effect=ValueError('Invalid ticket'))
        self.fake.session = _dict(user='Administrator')
        with patch.object(self.tickets, 'require_access'):
            with self.assertRaises(ValueError): self.tickets.validate_ticket(doc, check_assignment=False)
            doc.update(source_hub_event='event', source_provider_message_key='provider',
                       company='Company North', conversation_key='conversation')
            token = self.tickets._episode_transition.set(doc)
            try:
                self.tickets.validate_ticket(doc, check_assignment=False)
            finally:
                self.tickets._episode_transition.reset(token)
            with self.assertRaises(ValueError): self.tickets.validate_ticket(doc, check_assignment=False)


class TriageEnrollmentTests(unittest.TestCase):
    def setUp(self):
        from relay_core import enrollment
        self.api = enrollment
        self.event = _dict(name='event', account='account', creation='today', payload=json.dumps({
            'channel':'Email', 'direction':'inbound', 'provider_id':'provider', 'sender':'sender@example.invalid',
            'body':'Private 1250'}))
        self.channel = _dict(name='channel', company='Company North', check_permission=Mock())
        self.db = Mock()
        self.db.get_value.return_value = None
        self.db.exists.return_value = False
        self.fake = SimpleNamespace(get_doc=lambda dt, name: self.event if dt == 'Relay Hub Event' else self.channel,
            get_all=Mock(return_value=['channel']), db=self.db, PermissionError=PermissionError,
            ValidationError=ValueError, throw=lambda *a: (_ for _ in ()).throw(PermissionError()))
        self.enterContext(patch.object(enrollment, 'frappe', self.fake))
        self.enterContext(patch.object(enrollment, 'require_access'))
        self.enterContext(patch.object(enrollment, 'connection_value', return_value='account'))

    def test_event_rows_require_company_and_account_scope(self):
        with patch('relay_core.permissions.company_allowed', return_value=True):
            event, channel, medium, rows = self.api.event_rows('event')
            self.assertEqual((event.name, channel, medium), ('event', 'channel', 'Email'))
            self.assertEqual(rows[0]['id'], 'provider')
        with patch('relay_core.permissions.company_allowed', return_value=False):
            with self.assertRaises(PermissionError): self.api.event_rows('event')
        self.event.account = 'other'
        with self.assertRaises(PermissionError): self.api.event_rows('event')

    def test_pending_sanitizes_body_and_omits_other_company(self):
        rows = self.api.extract_messages(json.loads(self.event.payload))
        self.fake.get_all.return_value = [_dict(name='event')]
        with patch.object(self.api, 'event_rows', return_value=(self.event,'channel','Email',rows)), \
                patch('relay_core.tickets.source_episode', return_value=('provider-key','action-key')):
            result = self.api.pending()
        self.assertEqual(set(result), {'items','next'})
        self.assertEqual(result['items'][0]['preview'], 'Incoming conversation needs triage')
        self.assertNotIn('1250', json.dumps(result))
        with patch.object(self.api, 'event_rows', side_effect=PermissionError):
            self.assertEqual(self.api.pending(), {'items':[], 'next':None})

    def test_reassigned_channel_cannot_expose_or_bind_saved_source_company(self):
        rows = self.api.extract_messages(json.loads(self.event.payload))
        self.fake.get_all.return_value = [_dict(name='event')]
        self.channel.company = 'Company South'
        self.db.get_value.return_value = _dict(name='ticket', company='Company North')
        with patch('relay_core.permissions.company_allowed', side_effect=lambda company: company == 'Company South'), \
                patch('relay_core.tickets.source_episode', return_value=('provider-key','action-key')), \
                patch.object(self.api, 'readable_contact'):
            self.assertEqual(self.api.pending(), {'items':[], 'next':None})
            with self.assertRaises(PermissionError):
                self.api.bind('event', 'provider', 'contact', 'Customer', 'Sim Customer')

    def test_ticket_permission_requires_company_for_source_only_records(self):
        from relay_core import tickets
        doc = _dict(owner='Administrator', assigned_to='staff', company='Company North', messages=[],
            source_hub_event='event', source_provider_message_key='provider', conversation_key='conversation')
        fake = SimpleNamespace(get_roles=lambda user:[], session=_dict(user='staff'))
        with patch.object(tickets, 'frappe', fake), patch('relay_core.permissions.company_allowed', return_value=True):
            self.assertTrue(tickets.permission(doc))
            doc.source_hub_event = None
            self.assertFalse(tickets.permission(doc))
            doc.source_hub_event = 'event'
            doc.business_doctype = 'Customer'
            self.assertFalse(tickets.permission(doc), 'Partial business scope must deny before contact fallback')
            doc.business_doctype = None
        with patch.object(tickets, 'frappe', fake), patch('relay_core.permissions.company_allowed', return_value=False):
            self.assertFalse(tickets.permission(doc))
