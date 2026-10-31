"""Capability loader, approval, sender identity, rendering and model filter rules."""
import copy
import importlib
import json
import sys
import types
import unittest
from unittest.mock import Mock, patch
from test_ai_skills import Doc, capability, framework, module
import relay_core.ai.configuration  # noqa: F401 - loaded before frappe is replaced in sys.modules
import relay_core.automation.channel  # noqa: F401
from relay_core.ai.builtin_capabilities import CAPABILITIES
from relay_core.automation.contracts import validate_filters, validate_search

FIELDS = {'party': Doc(fieldtype='Dynamic Link', options='party_type'), 'party_type': Doc(fieldtype='Link', options='DocType'),
    'company': Doc(fieldtype='Link', options='Company'), 'is_cancelled': Doc(fieldtype='Check'),
    'posting_date': Doc(fieldtype='Date'), 'voucher_type': Doc(fieldtype='Link', options='DocType'),
    'voucher_no': Doc(fieldtype='Dynamic Link', options='voucher_type'), 'debit': Doc(fieldtype='Currency'),
    'credit': Doc(fieldtype='Currency'), 'remarks': Doc(fieldtype='Text'), 'api_secret': Doc(fieldtype='Data'),
    'items': Doc(fieldtype='Table')}
READ = copy.deepcopy(CAPABILITIES['erpnext.supplier_ledger'])


class CapabilityCase(unittest.TestCase):
    def setUp(self):
        self.f = framework()
        self.hooks = {'relay_core': {'relay_ai_capabilities': ['relay_core.ai.builtin_capabilities.CAPABILITIES'],
                                     'relay_ai_capability_prefix': ['erpnext']}}
        self.declared = {'relay_core.ai.builtin_capabilities.CAPABILITIES': CAPABILITIES}
        self.f.get_installed_apps = lambda: list(self.hooks)
        self.f.get_hooks = lambda hook, app_name=None: self.hooks[app_name].get(hook, [])
        self.f.get_attr = lambda path: self.declared[path]
        self.access = Mock()
        meta = Doc(get_field=lambda key: FIELDS.get(key))
        shared = types.SimpleNamespace(get_readable_meta=lambda doctype: meta,
            is_sensitive_field=lambda name: 'secret' in name)
        self.enterContext(patch.dict(sys.modules, {'frappe_tools.ai.tools': shared}))
        self.capabilities = module('relay_core/ai/capabilities.py', self.f, {
            'relay_core.business_access': types.SimpleNamespace(document_name=lambda name: name),
            'relay_core.permissions': types.SimpleNamespace(require_access=self.access)})

    def declare(self, app, prefix, packs):
        path = app + '.capabilities.CAPABILITIES'
        self.hooks[app] = {'relay_ai_capabilities': [path], 'relay_ai_capability_prefix': [prefix]}
        self.declared[path] = packs


class LoaderTests(CapabilityCase):
    def test_core_packs_load_with_app_key_and_field_flags(self):
        loaded = self.capabilities.manifests()
        self.assertEqual(set(loaded), {'erpnext.customer_ledger', 'erpnext.supplier_ledger', 'erpnext.payment_entry_draft'})
        ledger = loaded['erpnext.supplier_ledger']
        self.assertEqual((ledger['key'], ledger['app']), ('erpnext.supplier_ledger', 'relay_core'))
        self.assertNotIn('remarks', [row['name'] for row in ledger['fields']])
        self.assertEqual(loaded['erpnext.payment_entry_draft']['approval_policy'], 'Required')

    def test_key_must_use_the_declaring_app_prefix(self):
        self.hooks['relay_yrp'] = {'relay_ai_capability_prefix': ['distributor']}
        for key in ('yrp.Orders', 'distributor', 'erpnext.orders', 'relay_yrp.orders', 'yrp.orders.extra', 3):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.capabilities.validate_manifest('relay_yrp', key, READ)
        self.assertEqual(self.capabilities.validate_manifest('relay_yrp', 'yrp.orders', READ)['app'], 'relay_yrp')

    def test_identity_render_and_method_must_belong_to_the_declaring_app(self):
        self.hooks['relay_yrp'] = {'relay_ai_capability_prefix': ['distributor']}
        for changes in ({'identity': 'relay_sihma.identity.validate'}, {'identity': 'relay_core.ai.identity.validate'},
                        {'render': 'frappe.client.get_list'}, {'render': 42}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.capabilities.validate_manifest('relay_yrp', 'yrp.ledger', dict(READ, **changes))
        checked = self.capabilities.validate_manifest('relay_yrp', 'yrp.ledger', dict(READ, identity='relay_yrp.identity.check'))
        self.assertEqual(checked['identity'], 'relay_yrp.identity.check')
        with self.assertRaises(ValueError):
            self.capabilities.validate_manifest('relay_core', 'erpnext.draft',
                dict(CAPABILITIES['erpnext.payment_entry_draft'], method='frappe.client.insert'))

    def test_hook_path_from_another_app_is_rejected(self):
        self.hooks['relay_yrp'] = {'relay_ai_capabilities': ['relay_core.ai.builtin_capabilities.CAPABILITIES']}
        with self.assertRaisesRegex(ValueError, 'own module'):
            self.capabilities.manifests()

    def test_duplicate_key_in_two_apps_fails_the_load(self):
        self.declare('relay_shadow', 'erpnext', {'erpnext.customer_ledger': dict(READ, render='relay_shadow.render.ledger')})
        with self.assertRaisesRegex(ValueError, 'declared by'):
            self.capabilities.manifests()

    def test_text_fields_never_reach_the_model(self):
        validate = lambda fields: self.capabilities.validate_manifest('relay_core', 'erpnext.ledger', dict(READ, fields=fields))
        with self.assertRaisesRegex(ValueError, 'cannot be shown to the model'):
            validate([*READ['fields'], {'name': 'remarks', 'model': True, 'customer': True}])
        checked = validate([*READ['fields'], {'name': 'remarks', 'customer': True}])
        self.assertEqual(checked['fields'][-1], {'name': 'remarks', 'model': False, 'customer': True})
        for row in ({'name': 'remarks'}, {'name': 'api_secret', 'model': True}, {'name': 'items', 'customer': True},
                    {'name': 'missing', 'model': True}, {'name': 'debit', 'model': 'yes'}, READ['fields'][0]):
            with self.subTest(row=row), self.assertRaises(ValueError):
                validate([*READ['fields'], row])

    def test_scope_filters_limits_and_order_are_closed(self):
        scope = READ['scope']
        for changes in ({'limit': 21}, {'limit': 0}, {'operation': 'run_report'}, {'empty_result': 'zero'},
                {'confirmation': 'Never'}, {'order_by': 'remarks desc'}, {'order_by': 'name; drop'},
                {'filters': {'remarks': {'type': 'string', 'operators': ['=']}}},
                {'filters': {'debit': {'type': 'string', 'operators': ['like']}}},
                {'filters': {'debit': {'type': 'sql', 'operators': ['=']}}},
                {'scope': dict(scope, business_field='company')},
                {'scope': dict(scope, fixed={'is_cancelled': 0})},
                {'scope': dict(scope, company={'kind': 'company_field', 'field': 'party'})},
                {'scope': dict(scope, company={'kind': 'via_parent', 'field': 'party'})},
                {'url': 'https://example.invalid'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.capabilities.validate_manifest('relay_core', 'erpnext.ledger', dict(READ, **changes))

    def test_draft_actions_require_staff_approval(self):
        draft = CAPABILITIES['erpnext.payment_entry_draft']
        with self.assertRaisesRegex(ValueError, 'staff approval'):
            self.capabilities.validate_manifest('relay_core', 'erpnext.draft', dict(draft, approval_policy='None'))
        with self.assertRaises(ValueError):
            self.capabilities.validate_manifest('relay_core', 'erpnext.draft', dict(draft, link_checks={'Payment Entry': ['missing']}))

    def test_hash_is_stable_and_changes_with_the_manifest(self):
        loaded = self.capabilities.manifests()['erpnext.supplier_ledger']
        digest = self.capabilities.manifest_hash(loaded)
        self.assertEqual(digest, self.capabilities.manifest_hash(json.loads(json.dumps(loaded))))
        self.assertNotEqual(digest, self.capabilities.manifest_hash(dict(loaded, limit=10)))


class SyncTests(CapabilityCase):
    def setUp(self):
        super().setUp()
        self.rows = {}
        def insert(doc, **kw):
            self.rows[doc.capability_key] = doc
            return doc
        self.enterContext(patch.object(Doc, 'insert', insert))
        self.f.new_doc = lambda doctype: Doc(doctype=doctype, flags=Doc())
        self.f.db.exists.side_effect = lambda doctype, name: name in self.rows
        self.f.get_doc.side_effect = lambda doctype, name: self.rows[name]
        self.f.get_all.side_effect = lambda doctype, filters, pluck: [name for name in self.rows
            if name not in filters['name'][1] and self.rows[name].status != 'Missing']
        self.f.db.set_value.side_effect = lambda doctype, name, field, value: self.rows[name].update({field: value})
        self.enterContext(patch.dict(sys.modules, {'frappe.utils': types.SimpleNamespace(now_datetime=lambda: 'now')}))
        self.adapter_pack = {'yrp.ledger': dict(READ, render='relay_yrp.render.ledger')}
        self.declare('relay_yrp', 'distributor', self.adapter_pack)

    def test_new_core_packs_approve_and_adapter_packs_wait(self):
        self.capabilities.sync()
        self.assertEqual(self.rows['erpnext.supplier_ledger'].status, 'Approved')
        self.assertEqual(self.rows['erpnext.supplier_ledger'].approved_by, 'Administrator')
        self.assertEqual(self.rows['yrp.ledger'].status, 'Pending approval')
        self.assertEqual((self.rows['yrp.ledger'].kind, self.rows['yrp.ledger'].app), ('Read', 'relay_yrp'))

    def test_changed_hash_marks_changed_and_absent_key_marks_missing(self):
        self.capabilities.sync()
        row = self.rows['yrp.ledger']
        self.capabilities.mark_approved(row, 'manager')
        self.capabilities.sync()
        self.assertEqual(row.status, 'Approved')
        self.adapter_pack['yrp.ledger'] = dict(self.adapter_pack['yrp.ledger'], limit=5)
        self.capabilities.sync()
        self.assertEqual(row.status, 'Changed')
        self.assertNotEqual(row.approved_hash, row.current_hash)
        del self.adapter_pack['yrp.ledger']
        self.capabilities.sync()
        self.assertEqual(row.status, 'Missing')


class ActiveTests(CapabilityCase):
    def setUp(self):
        super().setUp()
        self.row = Doc(app='relay_yrp', enabled=1, status='Approved', approved_hash='h1', current_hash='h1',
                       manifest=json.dumps(capability()))
        self.trusted = 'relay_yrp\n'
        self.f.db.get_value.side_effect = lambda doctype, key, fields, as_dict: self.row if key == 'yrp.ledger' else None
        self.f.db.get_single_value = lambda doctype, field: self.trusted

    def test_only_enabled_approved_unchanged_trusted_packs_are_active(self):
        self.assertEqual(self.capabilities.active('yrp.ledger')['key'], 'erpnext.ledger')
        for changes in ({'enabled': 0}, {'status': 'Pending approval'}, {'status': 'Changed'}, {'status': 'Missing'},
                        {'current_hash': 'h2'}):
            original = dict(self.row); self.row.update(changes)
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'not approved'):
                self.capabilities.active('yrp.ledger')
            self.row.update(original)
        self.trusted = 'relay_sihma'
        with self.assertRaisesRegex(ValueError, 'not approved'): self.capabilities.active('yrp.ledger')
        self.row.app = 'relay_core'
        self.capabilities.active('yrp.ledger')
        for key in ('unknown.key', None):
            with self.assertRaises(ValueError): self.capabilities.active(key)

    def test_approve_needs_a_manager_and_an_installed_pack(self):
        doc = Doc(name='yrp.ledger', status='Pending approval', current_hash='h2', manifest=json.dumps({'version': 3}), flags=Doc())
        self.f.get_doc.side_effect = lambda doctype, name: doc
        self.enterContext(patch.dict(sys.modules, {'frappe.utils': types.SimpleNamespace(now_datetime=lambda: 'now')}))
        self.enterContext(patch('relay_core.ai_features.is_enabled', return_value=True))
        result = self.capabilities.approve('yrp.ledger')
        self.assertEqual(result, {'name': 'yrp.ledger', 'status': 'Approved', 'approved_hash': 'h2'})
        self.assertEqual((doc.approved_version, doc.approved_by), (3, 'operator'))
        self.assertIn(unittest.mock.call(manage=True), self.access.call_args_list)
        doc.status = 'Missing'
        with self.assertRaises(ValueError): self.capabilities.approve('yrp.ledger')
        self.access.side_effect = PermissionError('Not permitted')
        with self.assertRaises(PermissionError): self.capabilities.approve('yrp.ledger')


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.f = framework()
        self.binding = Doc(relay_contact='CONTACT-1', verified=1)
        self.f.db.get_value.side_effect = lambda *args, **kwargs: self.binding
        self.links = [('Customer', 'CUST-A')]
        self.validator = Mock(return_value=True)
        self.f.get_attr = lambda path: self.validator
        self.tools = types.SimpleNamespace(PrivacyDenied=type('PrivacyDenied', (ValueError,), {}))
        self.identity = module('relay_core/ai/identity.py', self.f, {'relay_core.ai.tools': self.tools})
        self.enterContext(patch.dict(sys.modules, {
            'relay_core.business_access': types.SimpleNamespace(candidates=lambda contact: self.links)}))
        self.scope = dict(channel='CH-1', endpoint='919800000001', contact='CONTACT-1', user='partner@example.invalid')
        self.manifest = capability(identity='relay_yrp.identity.validate_customer')

    def validate(self, business=('Customer', 'CUST-A')):
        self.identity.validate(self.manifest, self.scope, business)

    def test_linked_sender_and_adapter_validator_allow(self):
        self.validate()
        self.validator.assert_called_once_with(self.scope, ('Customer', 'CUST-A'))

    def test_other_party_unverified_or_rebound_endpoint_is_denied(self):
        for attribute, value in (('links', []), ('binding', Doc(relay_contact='CONTACT-1', verified=0)),
                                 ('binding', Doc(relay_contact='CONTACT-2', verified=1)), ('binding', None)):
            original = getattr(self, attribute); setattr(self, attribute, value)
            with self.subTest(attribute=attribute, value=value), self.assertRaises(self.tools.PrivacyDenied): self.validate()
            setattr(self, attribute, original)
        with self.assertRaises(self.tools.PrivacyDenied): self.validate(('Customer', 'CUST-B'))
        self.validator.assert_not_called()

    def test_adapter_validator_must_return_true(self):
        for result in (False, None, 1, 'yes', ValueError('Disabled user')):
            self.validator.reset_mock(return_value=True, side_effect=True)
            if isinstance(result, Exception): self.validator.side_effect = result
            else: self.validator.return_value = result
            with self.subTest(result=result), self.assertRaises(self.tools.PrivacyDenied): self.validate()

    def test_core_packs_without_a_validator_use_the_contact_link_only(self):
        self.manifest.pop('identity')
        self.f.get_attr = Mock(side_effect=AssertionError('No validator'))
        self.validate()


class RenderTests(unittest.TestCase):
    def setUp(self):
        from relay_core.ai import render
        self.render = render
        self.renderer = Mock(return_value='Order SO-1 is ready.')
        self.enterContext(patch.object(render, 'frappe', types.SimpleNamespace(get_attr=lambda path: self.renderer)))
        self.manifest = capability(fields=('name', 'status'))
        self.manifest['fields'] += [dict(name='internal_note', model=False, customer=False),
                                    dict(name='delivery_note', model=False, customer=True)]

    def test_renderer_receives_only_customer_fields(self):
        rows = [dict(name='SO-1', status='Ready', internal_note='hidden', delivery_note='Gate 2')]
        self.assertEqual(self.render.render(self.manifest, rows, 'English', False), 'Order SO-1 is ready.')
        self.renderer.assert_called_once_with([dict(name='SO-1', status='Ready', delivery_note='Gate 2')], 'English', False)
        self.assertEqual(self.render.visible_rows(self.manifest, rows, 'model'), [dict(name='SO-1', status='Ready')])

    def test_long_empty_or_failing_renderer_fails_closed(self):
        for result in ('x' * 1851, '', '   ', None, ValueError('broken')):
            self.renderer.reset_mock(return_value=True, side_effect=True)
            if isinstance(result, Exception): self.renderer.side_effect = result
            else: self.renderer.return_value = result
            with self.subTest(result=result), self.assertRaisesRegex(ValueError, 'Renderer failed'):
                self.render.render(self.manifest, [], 'English', False)
        self.renderer.side_effect, self.renderer.return_value = None, 'x' * 1850
        self.render.render(self.manifest, [], 'English', False)

    def test_empty_text_in_four_languages(self):
        texts = {language: self.render.empty_text(language) for language in ('English', 'Malayalam', 'Hindi', 'Tamil', 'undetermined')}
        self.assertEqual(texts['English'], self.render.EMPTY_RESULT)
        self.assertEqual(texts['undetermined'], self.render.EMPTY_RESULT)
        self.assertEqual(len({texts[language] for language in ('English', 'Malayalam', 'Hindi', 'Tamil')}), 4)


class FilterTests(unittest.TestCase):
    def setUp(self):
        self.manifest = capability(fields=('name', 'status', 'posting_date', 'debit'), filters={
            'posting_date': {'type': 'date', 'operators': ['between', '>='], 'required': True},
            'status': {'type': 'string', 'operators': ['='], 'enum': ['Open', 'Closed']},
            'debit': {'type': 'number', 'operators': ['>=']}})
        self.date = {'posting_date': ['between', ['2026-10-01', '2026-10-31']]}

    def test_declared_filters_pass(self):
        for filters in (self.date, dict(self.date, status='Open'), dict(self.date, status=['=', 'Closed']),
                        dict(self.date, debit=['>=', 10.5]), {'posting_date': ['>=', '2026-10-01']}):
            with self.subTest(filters=filters):
                self.assertEqual(validate_filters(self.manifest, filters), filters)

    def test_undeclared_operator_type_range_or_missing_required_filter_is_rejected(self):
        for filters in ({}, {'status': 'Open'}, dict(self.date, party='OTHER'), dict(self.date, status='Draft'),
                {'posting_date': ['between', ['2026-10-31', '2026-10-01']]}, {'posting_date': ['between', ['2026-02-30', '2026-03-01']]},
                {'posting_date': ['between', '2026-10-01']}, {'posting_date': ['<=', '2026-10-01']},
                {'posting_date': '2026-10-01'}, {'posting_date': ['between', ['20261001', '20261031']]},
                dict(self.date, debit=['>=', '10']), dict(self.date, debit=['>=', float('nan')]),
                dict(self.date, status=['sql', 'select 1']), dict(self.date, status=['=', 'Open', 'x']), []):
            with self.subTest(filters=filters), self.assertRaises(ValueError):
                validate_filters(self.manifest, filters)

    def test_search_fields_are_the_model_fields_and_limit_is_bounded(self):
        self.manifest['fields'][0]['model'] = False
        plan = dict(purpose='Show my ledger', reference='erpnext.ledger', fields=['status', 'posting_date', 'debit'],
                    arguments={'filters': self.date, 'limit': 20})
        self.assertEqual(validate_search(plan, [self.manifest]), plan)
        for changes in ({'fields': ['name', 'status', 'posting_date', 'debit']}, {'arguments': {'filters': self.date, 'limit': 21}},
                        {'reference': 'erpnext.other'}, {'fields': 'status'}, {'fields': [{'name': 'status'}]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_search(dict(plan, **changes), [self.manifest])

    def test_core_fills_search_fields_from_the_approved_pack(self):
        self.manifest['fields'][0]['model'] = False
        plan = dict(purpose='Show my ledger', reference='erpnext.ledger', arguments={'filters': self.date})
        full = dict(plan, fields=['status', 'posting_date', 'debit'])
        for fields in ([], ['debit', 'status'], ['status', 'posting_date', 'debit']):
            with self.subTest(fields=fields):
                self.assertEqual(validate_search(dict(plan, fields=fields), [self.manifest]), full)
        self.assertEqual(validate_search(plan, [self.manifest]), full)

    def test_field_list_nested_in_arguments_gets_the_same_check(self):
        self.manifest['fields'][0]['model'] = False
        plan = dict(purpose='Show my ledger', reference='erpnext.ledger', arguments={'filters': self.date})
        nested = dict(plan, arguments=dict(plan['arguments'], fields=['debit']))
        self.assertEqual(validate_search(nested, [self.manifest]), dict(plan, fields=['status', 'posting_date', 'debit']))
        for fields in (['name'], 'status', None):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                validate_search(dict(plan, arguments=dict(plan['arguments'], fields=fields)), [self.manifest])


class PatchTests(unittest.TestCase):
    def test_skill_rows_become_capability_rows(self):
        skills = [Doc(name='Ledger', allowed_tools=json.dumps([dict(name='ledger', method='get_list', doctype='GL Entry',
                      report='customer_ledger'), dict(name='orders', method='get_list', doctype='Sales Order')])),
                  Doc(name='Supplier', allowed_tools=json.dumps([dict(name='ledger', report='supplier_ledger')])),
                  Doc(name='Done', allowed_tools=json.dumps([{'capability': 'erpnext.customer_ledger'}])),
                  Doc(name='Empty', allowed_tools=None)]
        f = types.SimpleNamespace(get_all=lambda doctype, fields: skills, db=Mock())
        with patch.dict(sys.modules, frappe=f):
            sys.modules.pop('relay_core.patches.v1_0.capability_contracts', None)
            importlib.import_module('relay_core.patches.v1_0.capability_contracts').execute()
        self.assertEqual(f.db.set_value.call_args_list, [
            unittest.mock.call('Relay AI Skill', 'Ledger', 'allowed_tools', '[{"capability": "erpnext.customer_ledger"}]', update_modified=False),
            unittest.mock.call('Relay AI Skill', 'Supplier', 'allowed_tools', '[{"capability": "erpnext.supplier_ledger"}]', update_modified=False)])



class DraftPackPatchTests(unittest.TestCase):
    def test_saved_create_draft_rows_name_the_payment_entry_pack(self):
        rows = [{'action': 'create_draft', 'doctype': 'Payment Entry', 'fields': ['paid_amount']}, {'action': 'reply'}]
        skills = [Doc(name='Draft', allowed_actions=json.dumps(rows))]
        f = types.SimpleNamespace(get_all=Mock(return_value=skills), db=Mock())
        with patch.dict(sys.modules, frappe=f):
            sys.modules.pop('relay_core.patches.v1_0.use_payment_entry_draft_pack', None)
            importlib.import_module('relay_core.patches.v1_0.use_payment_entry_draft_pack').execute()
        rows[0]['action'] = 'erpnext.payment_entry_draft'
        f.db.set_value.assert_called_once_with('Relay AI Skill', 'Draft', 'allowed_actions', json.dumps(rows),
                                               update_modified=False)

    def test_core_registers_no_second_draft_hook(self):
        from relay_core import hooks
        self.assertNotIn('create_draft', hooks.relay_flow_actions)
        self.assertEqual(CAPABILITIES['erpnext.payment_entry_draft']['method'], 'relay_core.ai.actions.create_draft')


class RunCapabilityTests(unittest.TestCase):
    from test_ai_skills import ConversationIdentityTests
    setUp = ConversationIdentityTests.setUp

    def bind(self):
        self.packs = [capability()]
        self.tools.contracts = lambda skill: self.packs
        self.service.lock_contact = Mock(return_value=Doc(automation_paused=0, automation_generation=1))
        self.service.message_hash = Mock(return_value='hash')
        self.skill.update(enabled=1, modified='v1')
        self.enterContext(patch.dict(sys.modules, {'relay_core.tickets': types.SimpleNamespace(check_episode=Mock()),
                                                   'relay_core.ai.tools': self.tools}))
        scope = self.service.context(self.skill, self.message)[2]
        return Doc(skill_version='v1', generation=1, message_hash='hash', capability_hashes=json.dumps(scope['capabilities']))

    def test_context_records_the_hash_of_each_active_pack(self):
        from relay_core.ai.capabilities import manifest_hash
        run = self.bind()
        self.assertEqual(json.loads(run.capability_hashes), {'erpnext.ledger': manifest_hash(capability())})
        self.assertEqual(self.service.current(run, self.skill, self.message)[2]['capabilities'], json.loads(run.capability_hashes))

    def test_capability_changed_or_disabled_between_decision_and_send_supersedes_the_run(self):
        run = self.bind()
        self.packs = [capability(limit=5)]
        with self.assertRaisesRegex(self.service.Superseded, 'Capability changed'):
            self.service.current(run, self.skill, self.message)
        self.tools.contracts = Mock(side_effect=ValueError('Capability is not approved'))
        with self.assertRaisesRegex(self.service.Superseded, 'Capability changed'):
            self.service.current(run, self.skill, self.message)

    def test_capability_action_packs_join_the_run_hashes(self):
        self.skill.allowed_actions = '[{"action": "erpnext.payment_entry_draft"}]'
        registered = {'erpnext.payment_entry_draft': {'capability_hash': 'h-action'}, 'reply': {}}
        with patch('relay_core.ai.configuration.action_contracts', return_value=[{'action': 'erpnext.payment_entry_draft'}]), \
                patch('relay_core.flows.actions.definitions', return_value=registered) as definitions:
            run = self.bind()
        self.assertEqual(json.loads(run.capability_hashes)['erpnext.payment_entry_draft'], 'h-action')
        definitions.assert_called_with(context='ai')


class CompanyNeutralTests(unittest.TestCase):
    from test_ai_skills import ConversationIdentityTests
    setUp = ConversationIdentityTests.setUp

    def neutral(self, channel_company=None, packs=None):
        neutral = capability(scope={'business_field': 'name', 'company': {'kind': 'company_neutral'}})
        self.tools.contracts = lambda skill: [neutral] if packs is None else packs
        self.enterContext(patch.dict(sys.modules, {'relay_core.ai.tools': self.tools}))
        original = self.f.get_doc.side_effect
        channel = Doc(channel='WhatsApp', enabled=1, company=channel_company)
        self.f.get_doc.side_effect = lambda dt, name: channel if dt == 'Relay Channel' else original(dt, name)

    def test_company_neutral_reads_run_on_a_channel_without_company(self):
        self.neutral()
        scope = self.service.context(self.skill, self.message)[2]
        self.assertIsNone(scope['company'])
        self.company_allowed.assert_not_called()

    def test_company_scoped_reads_and_drafts_still_need_the_channel_company(self):
        for packs, actions in (([capability()], '[]'), (None, '[{"action": "erpnext.payment_entry_draft"}]'), ([], '[]')):
            with self.subTest(packs=packs, actions=actions):
                self.neutral(packs=packs)
                self.skill.allowed_actions = actions
                with self.assertRaisesRegex(ValueError, 'company scope is missing'):
                    self.service.context(self.skill, self.message)

    def test_company_neutral_type_needs_no_company_doctype_or_exactly_one_company(self):
        self.f.db.get_single_value = Mock(return_value='Member\n')
        for has_companies, count, allowed in ((False, None, True), (True, 1, True), (True, 2, False), (True, 0, False)):
            self.f.db.count = Mock(return_value=count)
            with self.subTest(has_companies=has_companies, count=count), \
                    patch('relay_core.permissions.has_companies', return_value=has_companies):
                if allowed:
                    self.tools.company_neutral('Member')
                else:
                    with self.assertRaisesRegex(ValueError, 'not company neutral'): self.tools.company_neutral('Member')
                with self.assertRaisesRegex(ValueError, 'not company neutral'): self.tools.company_neutral('Customer')
            if not has_companies:
                self.f.db.count.assert_not_called()


class AIDefinitionTests(unittest.TestCase):
    def setUp(self):
        from relay_core.ai.actions import REPLY
        from relay_core.flows import actions
        self.actions = actions
        self.hooks = {'reply': REPLY}
        self.enterContext(patch.object(actions.frappe, 'get_hooks', side_effect=lambda hook, app_name=None: self.hooks))
        self.draft = dict(CAPABILITIES['erpnext.payment_entry_draft'], key='erpnext.payment_entry_draft', app='relay_core')
        self.packs = self.enterContext(patch('relay_core.ai.capabilities.packs', return_value=[self.draft]))

    def test_ai_actions_merge_core_built_ins_and_approved_action_packs(self):
        from relay_core.ai.capabilities import manifest_hash
        registered = self.actions.definitions(context='ai')
        self.assertEqual(set(registered), {'reply', 'erpnext.payment_entry_draft'})
        pack = registered['erpnext.payment_entry_draft']
        self.assertEqual(pack['capability_hash'], manifest_hash(self.draft))
        self.assertEqual((pack['contexts'], pack['ai_safe'], pack['replay_safe']), (['ai'], True, True))
        self.actions.frappe.get_hooks.assert_called_with('relay_flow_actions', app_name='relay_core')
        self.packs.assert_called_once_with('Action')

    def test_a_key_declared_by_core_and_a_pack_fails_the_registry(self):
        self.hooks['erpnext.payment_entry_draft'] = self.hooks['reply']
        with self.assertRaisesRegex(ValueError, 'declared twice'):
            self.actions.definitions(context='ai')


if __name__ == '__main__':
    unittest.main()
