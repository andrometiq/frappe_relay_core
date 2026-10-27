"""Event metadata and preview contract tests; no provider or database."""
import json
import sys
import types
import unittest
from unittest.mock import Mock, patch
from test_ai_skills import Doc, framework, module


class EventEditorTests(unittest.TestCase):
    def setUp(self):
        self.f = framework()
        self.f.parse_json = json.loads
        self.f.has_permission = Mock(return_value=True)
        self.access = Mock()
        self.config = module('relay_core/ai/configuration.py', self.f,
            {'relay_core.permissions': types.SimpleNamespace(require_access=self.access)})
        self.fields = [Doc(fieldname=name, label=label, fieldtype=kind, options=options) for name, label, kind, options in [
            ('alias', 'Email address', 'Data', None), ('company', 'Company', 'Link', 'Company'),
            ('party', 'Party', 'Dynamic Link', 'party_type'), ('party_type', 'Party type', 'Link', 'DocType'),
            ('remarks', 'Remarks', 'Text', None), ('api_secret', 'Secret', 'Data', None),
            ('items', 'Items', 'Table', 'Item'), ('salary', 'Salary', 'Currency', None)]]
        self.meta = Doc(fields=self.fields, get_field=lambda key: next((r for r in self.fields if r.fieldname == key), None))
        self.modules = patch.dict(sys.modules, {'frappe_tools.ai.tools': types.SimpleNamespace(
            get_readable_meta=lambda dt: self.meta, get_readable_columns=lambda meta: {'alias','company','party','remarks','api_secret','items'},
            is_sensitive_field=lambda key: 'secret' in key)})
        self.modules.start(); self.addCleanup(self.modules.stop)

    def values(self, kind):
        return {r['value'] for r in self.config.editor_options(kind, doctype='GL Entry', business_doctype='Supplier')['items']}

    def test_picker_constraints(self):
        self.assertEqual(self.values('identity'), {'alias'})
        self.assertEqual(self.values('company'), {'company'})
        self.assertEqual(self.values('scope'), {'party'})
        self.assertEqual(self.values('field'), {'name','alias','company','party','remarks'})
        self.assertEqual(self.config.editor_options('identity', query='Email', doctype='Supplier')['items'][0]['label'], 'Email address')
        self.assertEqual(self.config.editor_options('field', doctype='Supplier', selected='["salary"]'), {'items':[]})
        self.f.has_permission.return_value=False
        with self.assertRaises(PermissionError): self.values('field')

    def test_picker_denies_non_configurers_and_bad_input(self):
        for args in ({'kind':'sql'}, {'kind':'field','query':'x'*81}, {'kind':'field','selected':'{}'}):
            with self.assertRaises(ValueError): self.config.editor_options(**args)
        self.access.side_effect = PermissionError
        with self.assertRaises(PermissionError): self.config.editor_options('doctype')
        self.f.get_list.assert_not_called()

    def test_preview_ticket_only_and_matching_denial_never_call_decision(self):
        event=Doc(name='event', title='Receipt', execution_policy='Ticket only')
        self.f.get_doc.side_effect=[event,Doc()]
        self.f.db.get_value.return_value='Sim Owner'
        context=Mock(return_value=('operator',('Supplier','private'),{'provider':'Email','company':'Sim Company'}))
        decide=Mock(return_value={'reply':'', 'handoff':False, 'actions':[{'action':'reply','parameters':{'text':'Received'}}]})
        matching=types.SimpleNamespace(candidates=lambda source: [], MAX_CANDIDATES=20,
            select=Mock(return_value={'selected':'event','method':'exact','reason':'Exact event trigger'}))
        with patch.dict(sys.modules, {'relay_core.ai.service':types.SimpleNamespace(context=context,decide=decide)}), \
                patch('relay_core.ai.matching',matching, create=True):
            result=self.config.test_skill('event','source')
            self.assertEqual(result['mode'],'Shadow'); self.assertEqual(result['actions'],[])
            self.assertEqual(result['match']['selected'],'Receipt'); decide.assert_not_called()
            event.execution_policy='Execute'; self.f.get_doc.side_effect=[event,Doc()]
            with patch('relay_core.automation.service.reserve_attempt'):
                result=self.config.test_skill('event','source')
            self.assertEqual(result['actions'][0]['action'],'reply')
            context.side_effect=PermissionError
            self.f.get_doc.side_effect=[event,Doc()]
            self.assertIsNone(self.config.test_skill('event','source')['identity_scope'])
            self.assertEqual(decide.call_count,1)


def setUpModule():
    """These tests cover AI behavior, so the AI features switch is on."""
    from unittest import addModuleCleanup, mock
    switch = mock.patch('relay_core.ai_features.is_enabled', return_value=True)
    switch.start()
    addModuleCleanup(switch.stop)
