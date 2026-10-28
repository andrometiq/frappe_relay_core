import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.wa = types.ModuleType('relay_core.whatsapp')
        self.wa.READ={'capabilities'};self.wa.MANAGE={'templates.create'};self.wa.SEND={'messages.send'}
        for name in ('send','execute','deliveries','business_contacts','conversation'):
            setattr(self.wa,name,Mock(return_value={'ok':True}))
        self.f=types.SimpleNamespace(whitelist=lambda **kw:lambda fn:fn)
        permissions=types.ModuleType('relay_core.permissions');permissions.require_access=Mock()
        spec=importlib.util.spec_from_file_location('core_mcp_test',Path('relay_core/mcp.py'));self.api=importlib.util.module_from_spec(spec)
        import relay_core
        with patch.dict(sys.modules,frappe=self.f,**{'relay_core.whatsapp':self.wa,'relay_core.permissions':permissions}),patch.object(relay_core,'whatsapp',self.wa,create=True):
            spec.loader.exec_module(self.api)

    def test_single_send_uses_durable_service_and_bulk_is_absent(self):
        message={'key':'stable-1','operation':'messages.send'}
        self.api.dispatch('tools/call',{'name':'relay.messages.send','arguments':{'message':message}})
        self.wa.send.assert_called_once_with(message=message)
        with self.assertRaises(ValueError):
            self.api.dispatch('tools/call',{'name':'relay.messages.bulk','arguments':{'messages':[message]}})

    def test_unknown_tool_and_arguments_are_rejected(self):
        for params in ({'name':'frappe.db.sql','arguments':{}},{'name':'relay.messages.send','arguments':{'message':{},'ignore_permissions':True}}):
            with self.assertRaises(ValueError):self.api.dispatch('tools/call',params)
        self.wa.send.assert_not_called()

    def test_service_permission_failure_is_not_bypassed(self):
        self.wa.execute.side_effect=PermissionError('denied')
        with self.assertRaises(PermissionError):self.api.dispatch('tools/call',{'name':'relay.whatsapp.execute','arguments':{'operation':'templates.create'}})

    def test_tool_catalog_and_protocol(self):
        catalog=self.api.dispatch('tools/list',{})['tools']
        names={tool['name'] for tool in catalog}
        self.assertEqual(len(names),len(catalog))
        self.assertTrue({'relay.tickets.assign','relay.tickets.subscribe','relay.business.messages'}.issubset(names))
        self.assertTrue({'relay.flows.generate','relay.flows.validate','relay.flows.actions','relay.flows.references','relay.flows.set_enabled'}.issubset(names))
        self.assertEqual(self.api.dispatch('initialize',{'protocolVersion':'2025-06-18'})['serverInfo']['name'],'relay-core')
        with self.assertRaises(ValueError):self.api.dispatch('initialize',{'protocolVersion':'unsupported'})

    def test_flow_authoring_mcp_exposes_ai_lifecycle_without_ui(self):
        import relay_core.flows as flow_package
        service=types.ModuleType('relay_core.flows.service')
        service.directory=Mock(return_value={'items':[]});service.read=Mock();service.save=Mock()
        service.publish=Mock();service.validate_draft=Mock(return_value={'valid':True})
        service.set_enabled=Mock(return_value={'enabled':0});service.runs=Mock();service.cancel=Mock();service.enqueue=Mock()
        service.providers=Mock(return_value={'items':[]});service.references=Mock(return_value=[])
        authoring=types.ModuleType('relay_core.flows.authoring');authoring.draft=Mock(return_value={'title':'Support','command':'/support','nodes':[],'enabled':0})
        actions=types.ModuleType('relay_core.flows.actions');actions.catalog=Mock(return_value=[])
        modules={'relay_core.flows.service':service,'relay_core.flows.authoring':authoring,
                 'relay_core.flows.actions':actions}
        with patch.object(flow_package,'service',service,create=True),patch.dict(sys.modules,**modules):
            self.api.dispatch('tools/call',{'name':'relay.flows.generate','arguments':{'requirement':'Collect ledger dates and send the ledger','provider':'AI-1'}})
            authoring.draft.assert_called_once_with(requirement='Collect ledger dates and send the ledger',provider='AI-1')
            self.api.dispatch('tools/call',{'name':'relay.flows.validate','arguments':{'values':{'title':'Support'}}})
            service.validate_draft.assert_called_once_with(values={'title':'Support'})
            self.api.dispatch('tools/call',{'name':'relay.flows.set_enabled','arguments':{'name':'RELAY-FLOW-1','enabled':0}})
            service.set_enabled.assert_called_once_with(name='RELAY-FLOW-1',enabled=0)
            self.api.dispatch('tools/call',{'name':'relay.flows.actions','arguments':{}})
            actions.catalog.assert_called_once_with()
            self.api.dispatch('tools/call',{'name':'relay.flows.references','arguments':{'kind':'business_doctype','query':'Cust'}})
            service.references.assert_called_once_with(kind='business_doctype',query='Cust')

    def test_endpoint_requires_api_token_and_rejects_browser_origin(self):
        class Response:
            def __init__(self, body='', status=200, **kwargs):self.status_code=status;self.body=body
        self.f.session=types.SimpleNamespace(user='Guest')
        headers={};self.f.get_request_header=lambda k:headers.get(k)
        with patch.dict(sys.modules,**{'werkzeug.wrappers':types.SimpleNamespace(Response=Response)}):
            self.assertEqual(self.api.endpoint().status_code,401)
            self.f.session.user='member';headers['Authorization']='token key:secret';headers['Origin']='https://browser.test'
            self.assertEqual(self.api.endpoint().status_code,403)

    def test_notifications_cannot_send_and_exception_text_is_hidden(self):
        class Response:
            def __init__(self, body='', status=200, **kwargs):self.status_code=status;self.body=body
        self.f.session=types.SimpleNamespace(user='member')
        self.f.get_request_header=lambda k:'token key:secret' if k=='Authorization' else None
        body={'jsonrpc':'2.0','method':'tools/call','params':{'name':'relay.messages.send','arguments':{'message':{'key':'one','operation':'messages.send'}}}}
        self.f.request=types.SimpleNamespace(content_length=300,get_json=lambda:body)
        with patch.dict(sys.modules,**{'werkzeug.wrappers':types.SimpleNamespace(Response=Response)}):
            self.assertEqual(self.api.endpoint().status_code,400)
            self.wa.send.assert_not_called()
            body['id']=1;self.wa.send.side_effect=RuntimeError('secret-provider-token')
            result=self.api.endpoint();self.assertNotIn('secret-provider-token',result.body);self.assertIn('error',result.body)

    def test_ticket_mcp_uses_service_permission_boundary(self):
        import relay_core
        service=types.SimpleNamespace(create=Mock(return_value={'name':'TKT-00001'}),read=Mock(side_effect=PermissionError),update_status=Mock(),assign=Mock())
        with patch.object(relay_core,'tickets',service,create=True), patch.dict(sys.modules,**{'relay_core.ticket_notifications':types.SimpleNamespace(subscribe=Mock())}):
            self.api.dispatch('tools/call',{'name':'relay.tickets.create','arguments':{'subject':'Query','messages':['RELAY-MSG-0000000001']}})
            service.create.assert_called_once_with(subject='Query',messages=['RELAY-MSG-0000000001'])
            with self.assertRaises(PermissionError):
                self.api.dispatch('tools/call',{'name':'relay.tickets.read','arguments':{'name':'TKT-00001'}})

    def test_number_sends_and_campaigns_use_the_checked_services(self):
        import relay_core
        api=types.SimpleNamespace(send_text=Mock(return_value={'status':'Submitted'}),send_media=Mock(),send_template=Mock(),
                                  send_messages=Mock(return_value={'results':[]}),send_status=Mock(return_value={'results':[]}))
        campaigns=types.SimpleNamespace(create_with_rows=Mock(side_effect=PermissionError('denied')),append_rows=Mock(),read=Mock())
        with patch.object(relay_core,'messaging_api',api,create=True),patch.object(relay_core,'bulk_campaigns',campaigns,create=True):
            self.api.dispatch('tools/call',{'name':'relay.whatsapp.send_text','arguments':{'number':'919876543210','body':'Hi','key':'k-1'}})
            api.send_text.assert_called_once_with(number='919876543210',body='Hi',key='k-1')
            self.api.dispatch('tools/call',{'name':'relay.whatsapp.send_messages','arguments':{'items':[{'type':'text'}]}})
            api.send_messages.assert_called_once_with(items=[{'type':'text'}])
            self.api.dispatch('tools/call',{'name':'relay.whatsapp.send_status','arguments':{'batch':'b-1'}})
            api.send_status.assert_called_once_with(batch='b-1')
            with self.assertRaises(PermissionError):
                self.api.dispatch('tools/call',{'name':'relay.campaigns.create','arguments':{'title':'Promo','rows':[{'phone':'1'}]}})
            with self.assertRaises(ValueError):
                self.api.dispatch('tools/call',{'name':'relay.whatsapp.send_text','arguments':{'number':'919876543210'}})
        names={tool['name'] for tool in self.api.TOOLS}
        self.assertTrue({'relay.whatsapp.send_media','relay.whatsapp.send_template','relay.campaigns.append','relay.campaigns.read'}<=names)
        manager_tools=[tool['description'] for tool in self.api.TOOLS if 'Relay Communication Manager' in tool['description']]
        self.assertTrue(manager_tools)
        self.assertFalse(any('WhatsApp Manager' in text for text in manager_tools))

    def test_send_tools_take_a_channel_and_channels_are_listed(self):
        import relay_core
        api=types.SimpleNamespace(**{name:Mock(return_value={}) for name in ('send_text','send_media','send_template','send_messages')})
        email=types.SimpleNamespace(send=Mock(return_value={}));telegram=types.SimpleNamespace(send=Mock(return_value={}),groups=Mock(),execute=Mock())
        core_api=types.SimpleNamespace(channel_options=Mock(return_value={'items':[{'name':'Support'}]}))
        with patch.object(relay_core,'messaging_api',api,create=True),patch.object(relay_core,'email',email,create=True), \
                patch.object(relay_core,'telegram',telegram,create=True),patch.dict(sys.modules,{'relay_core.api':core_api}):
            self.api.dispatch('tools/call',{'name':'relay.whatsapp.send_text','arguments':{'number':'91','body':'Hi','channel':'Support'}})
            api.send_text.assert_called_once_with(number='91',body='Hi',channel='Support')
            self.api.dispatch('tools/call',{'name':'relay.messages.send','arguments':{'message':{'key':'k','operation':'messages.send','channel':'Support'}}})
            self.assertEqual(self.wa.send.call_args.kwargs['message']['channel'],'Support')
            self.api.dispatch('tools/call',{'name':'relay.whatsapp.execute','arguments':{'operation':'messages.send','channel':'Support'}})
            self.wa.execute.assert_called_once_with(operation='messages.send',channel='Support')
            self.api.dispatch('tools/call',{'name':'relay.email.send','arguments':{'to':['a@example.invalid'],'subject':'S','body':'B','channel':'Mail'}})
            email.send.assert_called_once_with(to=['a@example.invalid'],subject='S',body='B',channel_name='Mail')
            self.api.dispatch('tools/call',{'name':'relay.telegram.send','arguments':{'chat_id':1,'text':'t','channel':'Bot'}})
            telegram.send.assert_called_once_with(chat_id=1,text='t',channel='Bot')
            listed=self.api.dispatch('tools/call',{'name':'relay.channels.list','arguments':{}})
        self.assertEqual(listed['structuredContent'],{'items':[{'name':'Support'}]})
        for name in ('relay.whatsapp.send_media','relay.whatsapp.send_template'):
            self.assertIn('channel',next(tool for tool in self.api.TOOLS if tool['name']==name)['inputSchema']['properties'])

    def test_telegram_mcp_uses_checked_facade_for_groups_and_topics(self):
        import relay_core
        service=types.SimpleNamespace(groups=Mock(return_value={'success':True}),execute=Mock(return_value={'success':True}),send=Mock(return_value={'accepted':1}))
        with patch.object(relay_core,'telegram',service,create=True):
            self.api.dispatch('tools/call',{'name':'relay.telegram.groups','arguments':{'operation':'topics.create','arguments':{'chat_id':-1001,'name':'Support'}}})
            service.groups.assert_called_once_with(operation='topics.create',arguments={'chat_id':-1001,'name':'Support'})
            self.api.dispatch('tools/call',{'name':'relay.telegram.send','arguments':{'chat_id':-1001,'text':'reply','reply_to':4,'message_thread_id':8}})
            service.send.assert_called_once_with(chat_id=-1001,text='reply',reply_to=4,message_thread_id=8)

    def test_large_requests_are_allowed_only_for_group_photo_operations(self):
        class Response:
            def __init__(self, body='', status=200, **kwargs):self.status_code=status;self.body=body
        self.f.session=types.SimpleNamespace(user='manager')
        self.f.get_request_header=lambda k:'token key:secret' if k=='Authorization' else None
        body={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'relay.whatsapp.execute','arguments':{'operation':'groups.photo','arguments':{'id':'group-one','photo_base64':'synthetic'}}}}
        self.f.request=types.SimpleNamespace(content_length=2*1024*1024,get_json=lambda:body)
        with patch.dict(sys.modules,**{'werkzeug.wrappers':types.SimpleNamespace(Response=Response)}):
            self.assertEqual(self.api.endpoint().status_code,413)
            self.wa.execute.assert_not_called()
            body['params']['arguments']['operation']='templates.create'
            self.assertEqual(self.api.endpoint().status_code,413)
            self.f.request.content_length=7*1024*1024+1
            self.assertEqual(self.api.endpoint().status_code,413)
