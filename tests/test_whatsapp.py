import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

class WhatsAppTests(unittest.TestCase):
    def setUp(self):
        def throw(message,*args):raise ValueError(message)
        self.f=types.SimpleNamespace(whitelist=lambda **kw:lambda fn:fn,throw=throw,get_doc=Mock(),get_list=Mock(return_value=[]),parse_json=__import__('json').loads,utils=types.SimpleNamespace(get_url=lambda:'http://yrp.site:8002'))
        spec=importlib.util.spec_from_file_location('wa_test',Path('relay_core/whatsapp.py'));self.api=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,frappe=self.f):spec.loader.exec_module(self.api)
        self.api.require_business_assignment=Mock();self.api.require_access=Mock();self.hub=Mock();self.hub.execute.return_value={'site':'http://yrp.site:8002'};self.api.client=lambda:self.hub
    def test_multiple_contacts_are_returned(self):
        self.f.get_list.return_value=[{'name':'Contact-A'},{'name':'Contact-B'}]
        result=self.api.business_contacts('Customer','CUST-1')
        self.assertEqual(len(result['contacts']),2)
        self.f.get_doc.return_value.check_permission.assert_called_with('read')
        self.assertIn(['Dynamic Link','link_name','=','CUST-1'],self.f.get_list.call_args.kwargs['filters'])
    def test_contact_must_belong_to_business_record(self):
        doc=types.SimpleNamespace(check_permission=Mock(),links=[types.SimpleNamespace(link_doctype='Supplier',link_name='SUP-1')],mobile_no='919999999999')
        self.f.get_doc.return_value=doc
        with self.assertRaises(ValueError):self.api.execute('templates.send',{'name':'hello'},contact='Contact-A',business_doctype='Customer',business_name='CUST-1')
        self.hub.execute.assert_not_called()
    def test_explicit_contact_resolves_number_server_side(self):
        doc=types.SimpleNamespace(check_permission=Mock(),links=[types.SimpleNamespace(link_doctype='Customer',link_name='CUST-1')],mobile_no='+91 99999 99999')
        self.f.get_doc.return_value=doc
        self.api.execute('templates.send',{'name':'hello','language':'en'},contact='Contact-B',business_doctype='Customer',business_name='CUST-1')
        self.assertEqual(self.hub.execute.call_args.args[0]['to'],'919999999999')
    def test_client_cannot_supply_an_arbitrary_number(self):
        with self.assertRaises(ValueError):self.api.execute('templates.send',{'to':'123'})
        self.hub.execute.assert_not_called()
    def test_wrong_site_account_rejected(self):
        self.hub.execute.return_value={'site':'https://another.site'}
        with self.assertRaises(ValueError):self.api.execute('templates.list')
        self.assertEqual(self.hub.execute.call_count,1)

    def test_batch_resolves_every_contact_and_retains_retry_key(self):
        doc=types.SimpleNamespace(check_permission=Mock(),links=[types.SimpleNamespace(link_doctype='Customer',link_name='CUST-1')],mobile_no='+91 99999 99999')
        self.f.get_doc.return_value=doc
        self.api.enqueue([{'key':'retry-1','operation':'messages.send','arguments':{'body':'Hello'},'contact':'Contact-B','business_doctype':'Customer','business_name':'CUST-1'}])
        tool,args=self.hub.call_tool.call_args.args
        self.assertEqual(tool,'whatsapp.enqueue')
        self.assertEqual(args['messages'][0]['key'],'retry-1')
        self.assertEqual(args['messages'][0]['message']['to'],'919999999999')

    def test_invalid_batch_never_submits_partial_messages(self):
        with self.assertRaises(ValueError):self.api.enqueue([{'key':'one','operation':'calls.action'}])
        self.hub.call_tool.assert_not_called()

    def test_account_delivery_list_requires_manager(self):
        self.api.deliveries()
        self.api.require_access.assert_called_with(manage=True)

    def test_template_sample_upload_is_manager_scoped(self):
        args={'media_type':'document','filename':'sample.pdf','mime_type':'application/pdf','content_base64':'JVBERi0xLjc='}
        self.api.execute('templates.media_upload',args)
        self.api.require_access.assert_called_once_with(manage=True)
        self.assertEqual(self.hub.execute.call_args.args[0],dict(args,operation='templates.media_upload'))
        self.api.require_access.side_effect=PermissionError('Denied')
        self.hub.reset_mock()
        with self.assertRaises(PermissionError):self.api.execute('templates.media_upload',args)
        self.hub.execute.assert_not_called()

    def test_template_sample_upload_rejects_oversized_bytes_and_wrong_site(self):
        with self.assertRaises(ValueError):self.api.execute('templates.media_upload',{'content_base64':'x'*(6*1024*1024)})
        self.hub.execute.assert_not_called()
        self.hub.execute.return_value={'site':'https://other.site'}
        with self.assertRaises(ValueError):self.api.execute('templates.media_upload',{'content_base64':'JVBERi0xLjc=','mime_type':'application/pdf'})
        self.assertEqual(self.hub.execute.call_count,1)
