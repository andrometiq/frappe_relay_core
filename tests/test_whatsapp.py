import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch
from relay_core import file_limits
from site_file_limit import use_relay_file_limit


def setUpModule():
    use_relay_file_limit()

class WhatsAppTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('relay_core.business_access.require_type'))
        def throw(message,*args):raise ValueError(message)
        self.f=types.SimpleNamespace(whitelist=lambda **kw:lambda fn:fn,throw=throw,get_doc=Mock(),db=Mock(),get_roles=Mock(return_value=['Relay Communication Manager']),get_list=Mock(return_value=[]),parse_json=__import__('json').loads,utils=types.SimpleNamespace(get_url=lambda:'http://yrp.site:8002'),cache=types.SimpleNamespace(get_value=lambda key:None,set_value=Mock()))
        spec=importlib.util.spec_from_file_location('wa_test',Path('relay_core/whatsapp.py'));self.api=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,frappe=self.f):spec.loader.exec_module(self.api)
        self.api.business_document=lambda dt,name: self.f.get_doc(dt,name)
        self.f.get_all=self.f.get_list
        self.api.require_business_assignment=Mock();self.api.connection_value=lambda key:'';self.api.require_access=Mock();self.api.can_manage=lambda:'Relay Communication Manager' in self.f.get_roles();self.hub=Mock();self.hub.execute.return_value={'site':'http://yrp.site:8002'};self.api.client=lambda:self.hub
        self.audit=patch.multiple('relay_core.whatsapp_templates',record_request=Mock(),apply_request=Mock(),overlay=Mock(side_effect=lambda page:page))
        self.audit.start();self.addCleanup(self.audit.stop)
        self.channels=patch.multiple('relay_core.hub_channels',hub_arguments=Mock(side_effect=lambda channel,args:args),
            choose=Mock(side_effect=lambda medium,names=None,contact=None,requested=None:requested or (names[0] if names else 'WA')))
        self.channels.start();self.addCleanup(self.channels.stop)
    def test_multiple_contacts_are_returned(self):
        self.f.get_list.return_value=[{'name':'Contact-A'},{'name':'Contact-B'}]
        result=self.api.business_contacts('Customer','CUST-1')
        self.assertEqual(len(result['contacts']),2)
        self.f.get_doc.return_value.check_permission.assert_not_called()
        self.assertIn(['Dynamic Link','link_name','=','CUST-1'],self.f.get_list.call_args.kwargs['filters'])
    def test_contact_must_belong_to_business_record(self):
        doc=types.SimpleNamespace(check_permission=Mock(),links=[types.SimpleNamespace(link_doctype='Supplier',link_name='SUP-1')],mobile_no='919999999999')
        self.f.get_doc.return_value=doc
        with self.assertRaises(ValueError):self.api.execute('templates.send',{'name':'hello'},contact='Contact-A',business_doctype='Customer',business_name='CUST-1')
        self.hub.execute.assert_not_called()
    def test_explicit_contact_resolves_number_server_side(self):
        doc=types.SimpleNamespace(check_permission=Mock(),links=[types.SimpleNamespace(link_doctype='Customer',link_name='CUST-1')],mobile_no='+91 99999 99999')
        self.f.get_doc.return_value=doc
        result=self.api.prepare('templates.send',{'name':'hello','language':'en'},contact='Contact-B',business_doctype='Customer',business_name='CUST-1')
        self.assertEqual(result['to'],'919999999999')
    def test_client_cannot_supply_an_arbitrary_number(self):
        with self.assertRaises(ValueError):self.api.execute('templates.send',{'to':'123'})
        self.hub.execute.assert_not_called()
    def test_wrong_site_account_rejected(self):
        self.hub.execute.return_value={'site':'https://another.site'}
        with self.assertRaises(ValueError):self.api.execute('templates.list')
        self.assertEqual(self.hub.execute.call_count,1)

    def test_public_send_uses_durable_action_and_stable_key(self):
        doc=types.SimpleNamespace(check_permission=Mock(),links=[types.SimpleNamespace(link_doctype='Customer',link_name='CUST-1')],mobile_no='+91 99999 99999')
        self.f.get_doc.return_value=doc
        target=types.SimpleNamespace(business_channels=Mock(return_value=[{'value':'channel','provider':'WhatsApp','endpoint':'first'}, {'value':'channel','provider':'WhatsApp','endpoint':'second'}, {'value':'telegram','provider':'Telegram'}, {'value':'email','provider':'Email'}]),send_business=Mock(return_value={'action':'action','status':'Queued'}))
        self.f.get_doc.side_effect = lambda dt, name: (types.SimpleNamespace(endpoint='919999999999' if name == 'second' else '919888888888')
            if dt == 'Relay Contact Endpoint' else doc)
        with patch.dict(sys.modules, **{'relay_core.conversation_start':target}):
            result=self.api.execute('messages.send',{'body':'Hello'},'Contact-B','Customer','CUST-1',request_key='retry-1')
        self.assertEqual(result['action'],'action')
        self.assertEqual(target.send_business.call_args.kwargs['channel'],'channel')
        self.assertEqual(target.send_business.call_args.kwargs['endpoint'],'second')
        self.assertEqual(target.send_business.call_args.kwargs['request_key'],'retry-1')
        self.assertEqual(target.send_business.call_args.kwargs['business_name'],'CUST-1')
        self.hub.call_tool.assert_not_called()
        self.hub.execute.assert_not_called()

    def test_missing_keys_bulk_groups_and_calls_are_unavailable(self):
        self.assertFalse(hasattr(self.api,'enqueue'))
        for operation in ('messages.send','groups.send','groups.media','groups.template','calls.action'):
            with self.assertRaises(ValueError):self.api.execute(operation)
        self.hub.call_tool.assert_not_called()

    def test_account_delivery_list_requires_administrator(self):
        with patch('relay_core.permissions.require_administrator') as gate:
            self.api.deliveries()
            gate.assert_called_once()
            gate.side_effect=PermissionError
            with self.assertRaises(PermissionError): self.api.deliveries()

    def test_template_sample_upload_is_manager_scoped(self):
        args={'media_type':'document','filename':'sample.pdf','mime_type':'application/pdf','content_base64':'JVBERi0xLjc='}
        self.api.execute('templates.media_upload',args)
        self.api.require_access.assert_called_once_with('Relay WhatsApp Template','write')
        self.assertEqual(self.hub.execute.call_args.args[0],dict(args,operation='templates.media_upload'))
        self.api.require_access.side_effect=PermissionError('Denied')
        self.hub.reset_mock()
        with self.assertRaises(PermissionError):self.api.execute('templates.media_upload',args)
        self.hub.execute.assert_not_called()

    def test_campaign_media_upload_is_manager_scoped_and_not_audited(self):
        from relay_core import whatsapp_templates
        args={'media_type':'image','mime_type':'image/png','filename':'offer.png','content_base64':'iVBORw0KGgo='}
        self.hub.execute.side_effect=[{'site':'http://yrp.site:8002'},{'id':'555'}]
        self.assertEqual(self.api.execute('messages.media_upload',args),{'id':'555'})
        self.api.require_access.assert_called_once_with('Relay Campaign','write')
        self.assertEqual(self.hub.execute.call_args.args[0],dict(args,operation='messages.media_upload'))
        whatsapp_templates.record_request.assert_not_called()
        with self.assertRaises(ValueError):self.api.prepare('messages.media_upload',dict(args,media_url='https://cdn.example/a.png'))

    def test_template_sample_upload_rejects_oversized_bytes_and_wrong_site(self):
        with self.assertRaises(ValueError):self.api.execute('templates.media_upload',{'content_base64':'x'*(file_limits.encoded_length(file_limits.MAX_BYTES)+4)})
        self.hub.execute.assert_not_called()
        self.hub.execute.return_value={'site':'https://other.site'}
        with self.assertRaises(ValueError):self.api.execute('templates.media_upload',{'content_base64':'JVBERi0xLjc=','mime_type':'application/pdf'})
        self.assertEqual(self.hub.execute.call_count,1)

    def test_manager_sees_redacted_hub_rejection_and_request_is_audited(self):
        from relay_core import whatsapp_templates
        from relay_core.hub import HubError
        detail="Variables can't be at the start or end of the template"
        self.hub.execute.side_effect=[{'site':'http://yrp.site:8002'},HubError('rejected',detail=detail)]
        args={'name':'order_update','language':'en_US','category':'UTILITY','components':[{'type':'BODY','text':'Hi'}]}
        with self.assertRaisesRegex(ValueError,'Hub rejected this operation: '+detail):self.api.execute('templates.create',args)
        whatsapp_templates.record_request.assert_called_once_with('templates.create',args,error=detail)
        self.f.db.commit.assert_called_once()
        whatsapp_templates.apply_request.assert_not_called()

    def test_non_manager_sees_generic_hub_rejection(self):
        from relay_core import whatsapp_templates
        from relay_core.hub import HubError
        self.f.get_roles.return_value=['Relay Communication User']
        self.hub.execute.side_effect=[{'site':'http://yrp.site:8002'},HubError('rejected',detail='templates are not enabled')]
        with self.assertRaises(ValueError) as caught:self.api.execute('templates.list')
        self.assertEqual(str(caught.exception),self.api.FAILURE)
        whatsapp_templates.record_request.assert_not_called()

    def test_successful_management_is_audited_and_applied(self):
        from relay_core import whatsapp_templates
        self.hub.execute.side_effect=[{'site':'http://yrp.site:8002'},{'id':'101','status':'PENDING'}]
        self.api.execute('templates.delete',{'name':'order_update','id':'101'})
        whatsapp_templates.record_request.assert_called_once_with('templates.delete',{'name':'order_update','id':'101'},result={'id':'101','status':'PENDING'})
        whatsapp_templates.apply_request.assert_called_once()
