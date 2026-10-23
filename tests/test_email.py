import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class EmailPermissionsTests(unittest.TestCase):
    def setUp(self):
        self.f = types.SimpleNamespace(whitelist=lambda **kw: lambda f: f, PermissionError=PermissionError,
            db=types.SimpleNamespace(get_value=Mock(return_value='RELAY-CON-0000000001')),
            get_list=Mock(return_value=[types.SimpleNamespace(name='RELAY-CH-0000000001')]), get_doc=Mock())
        def reject(message, exception): raise exception(message)
        self.f.throw = reject
        self.wa = types.ModuleType('relay_core.whatsapp'); self.wa.client=Mock()
        settings=types.ModuleType('relay_core.settings'); settings.value=Mock(return_value='test-account')
        spec=importlib.util.spec_from_file_location('tested_email',Path('relay_core/email.py'))
        self.service=importlib.util.module_from_spec(spec)
        import relay_core
        with patch.dict(sys.modules,{'frappe':self.f,'relay_core.settings':settings,'relay_core.whatsapp':self.wa}), patch.object(relay_core,'whatsapp',self.wa,create=True):
            spec.loader.exec_module(self.service)
        self.service.require_access=Mock(); self.service.readable_contact=Mock()

    def test_every_to_cc_bcc_recipient_is_checked_before_submission(self):
        self.service.prepare(['a@example.test'],'Subject','Body',cc=['b@example.test'],bcc=['c@example.test'])
        self.assertEqual(self.service.readable_contact.call_count,3)
        self.wa.client.assert_not_called()

    def test_missing_or_revoked_endpoint_cannot_send(self):
        self.f.db.get_value.return_value=None
        with self.assertRaises(PermissionError):self.service.prepare(['a@example.test'],'Subject','Body')
        self.wa.client.assert_not_called()

    def test_unreadable_business_record_cannot_send(self):
        self.service.readable_contact.side_effect=PermissionError
        with self.assertRaises(PermissionError):self.service.prepare(['a@example.test'],'Subject','Body')
        self.wa.client.assert_not_called()

    def test_injection_and_unbounded_recipients_are_rejected(self):
        for value in [['a@example.test\r\nBcc:evil@example.test'],['Person <a@example.test>'],['a@example.test']*51, 'a@example.test']:
            with self.assertRaises(ValueError):self.service.prepare(value,'Subject','Body')
        self.wa.client.assert_not_called()

    def test_invalid_recipient_structure_never_creates_an_action(self):
        for values in ({'to':[]}, {'to':'a@example.test'}, {'to':['a@example.test'],'cc':'b@example.test'},
                       {'to':['a@example.test'],'bcc':['invalid']},
                       {'to':[f'a{i}@example.test' for i in range(50)],'cc':['b@example.test']}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.service.send(**values,subject='Subject',body='Body',message='source',request_key='invalid')
        self.f.get_doc.assert_not_called()
        self.f.db.get_value.assert_not_called()
        self.wa.client.assert_not_called()
