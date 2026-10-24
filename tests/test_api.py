"""API contract tests with an isolated Frappe boundary; no site writes."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

class ApiTests(unittest.TestCase):
    def setUp(self):
        def whitelist(**kwargs):
            def decorate(fn):
                fn.allowed_methods=kwargs['methods']
                return fn
            return decorate
        def throw(message,*args):raise ValueError(message)
        self.f=types.SimpleNamespace(whitelist=whitelist,throw=throw,get_doc=Mock(),get_list=Mock(return_value=[]))
        spec=importlib.util.spec_from_file_location('tested_relay_api',Path('relay_core/api.py'))
        self.api=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,frappe=self.f):spec.loader.exec_module(self.api)
        self.api.require_access=Mock();self.api.readable_contact=Mock()

    def test_write_is_post_only_and_requires_config_access(self):
        self.assertEqual(self.api.update_channel.allowed_methods,['POST'])
        self.api.update_channel('RELAY-CH-0000000001',' Account ', '1')
        self.assertEqual(self.api.require_access.call_args_list[0].kwargs,{'configure':True})
        doc=self.f.get_doc.return_value
        self.assertEqual(doc.account,'Account');self.assertEqual(doc.enabled,1)
        doc.check_permission.assert_any_call('write');doc.save.assert_called_once()

    def test_invalid_input_does_not_write(self):
        for name,account,enabled in [('bad','valid',1),('RELAY-CH-0000000001','',1),('RELAY-CH-0000000001','valid','garbage')]:
            with self.assertRaises(ValueError):self.api.update_channel(name,account,enabled)
        self.f.get_doc.return_value.save.assert_not_called()

    def test_paging_is_bounded_ordered_and_permission_aware(self):
        self.f.get_list.return_value=[types.SimpleNamespace(name=f'RELAY-MSG-{i:010}',channel='RELAY-CH-0000000001') for i in range(101,0,-1)]
        page_query=Mock();page_query.return_value.run.return_value=self.f.get_list.return_value
        with patch.dict(sys.modules,**{'relay_core.timeline':types.SimpleNamespace(page_query=page_query)}):
            result=self.api.messages('RELAY-CON-0000000001',limit=9999)
        self.assertEqual(len(result['items']),100);self.assertTrue(result['has_more'])
        self.assertEqual(result['first'],'RELAY-MSG-0000000002')
        self.assertEqual(page_query.call_args_list[1].args[2],101)
        self.api.readable_contact.assert_called_with('RELAY-CON-0000000001')
        self.f.get_doc.return_value.check_permission.assert_called_with('read')

    def test_invalid_cursors_rejected_before_query(self):
        for kwargs in [{'contact':None},{'contact':{}},{'contact':'RELAY-CON-0000000001','before':'x'}, {'contact':'RELAY-CON-0000000001','limit':'bad'}, {'contact':'RELAY-CON-0000000001','before':'x','after':'y'}]:
            with self.assertRaises(ValueError):self.api.messages(**kwargs)
        self.f.get_list.assert_not_called()

    def test_settings_response_does_not_expose_secrets(self):
        self.f.get_doc.return_value.get.side_effect=lambda key:key
        self.assertEqual(set(self.api.channel_settings('RELAY-CH-0000000001')),{'name','channel','account','enabled'})

    def test_contact_search_runs_in_permission_filtered_database_query(self):
        self.f.get_list.return_value=[{'name':f'RELAY-CON-{i:010}', 'display_name':'Asha'} for i in range(1,52)]
        result=self.api.contacts(query='a%_',limit=10000)
        self.assertEqual(len(result['items']),50)
        self.assertIsNone(result['previous'])
        self.assertEqual(result['next'],{'after':'RELAY-CON-0000000050'})
        args=self.f.get_list.call_args
        self.assertEqual(args.args,('Relay Contact',))
        self.assertEqual(args.kwargs['page_length'],51)
        self.assertEqual(args.kwargs['or_filters'][0],['display_name','like','%a%\\%%\\_%'])

    def test_contact_reverse_page_and_invalid_input(self):
        self.f.get_list.return_value=[{'name':f'RELAY-CON-{i:010}'} for i in (3,2,1)]
        result=self.api.contacts(before='RELAY-CON-0000000004',limit=2)
        self.assertEqual([r['id'] for r in result['items']],['RELAY-CON-0000000002','RELAY-CON-0000000003'])
        self.assertEqual(result['previous'],{'before':'RELAY-CON-0000000002'})
        for kwargs in ({'query':'x'*81},{'query':{}},{'limit':True},{'before':'bad'},{'before':'RELAY-CON-0000000001','after':'RELAY-CON-0000000002'}):
            with self.assertRaises(ValueError):self.api.contacts(**kwargs)


class ContactDetailsTests(unittest.TestCase):
    setUp = ApiTests.setUp
    def test_details_exclude_private_links_and_include_readable_channels(self):
        person = types.SimpleNamespace(name='fixture-contact', full_name='Local fixture', mobile_no='15550000001', phone='',
            check_permission=Mock(), links=[types.SimpleNamespace(link_doctype='Customer', link_name=name) for name in ['visible', 'private']])
        person.links.append(types.SimpleNamespace(link_doctype='Supplier', link_name='unconfigured'))
        docs = {('Contact', 'fixture-contact'): person,
                ('Customer', 'visible'): types.SimpleNamespace(has_permission=lambda _: True),
                ('Customer', 'private'): types.SimpleNamespace(has_permission=lambda _: False),
                ('Relay Channel', 'wa'): types.SimpleNamespace(channel='WhatsApp', has_permission=lambda _: True),
                ('Relay Channel', 'email'): types.SimpleNamespace(channel='Email', has_permission=lambda _: True)}
        self.f.get_doc.side_effect=lambda dt,name:docs[(dt,name)]
        self.api.business_types=Mock(return_value=['Customer'])
        self.f.db=types.SimpleNamespace(get_value=Mock(return_value='relay-contact'))
        endpoint=types.SimpleNamespace(name='binding', channel='wa', verified=0)
        self.f.get_all=Mock(return_value=[endpoint,types.SimpleNamespace(channel='email')])
        result=self.api.contact_details('fixture-contact')
        self.assertEqual(result['links'],[{'doctype':'Customer','name':'visible'}])
        self.assertEqual([row.channel for row in result['endpoints']],['wa','email'])
        self.assertEqual([row.provider for row in result['endpoints']],['WhatsApp','Email'])
        self.api.readable_contact.assert_called_once_with('relay-contact')
        person.check_permission.assert_called_once_with('read')
        self.assertEqual(self.api.contact_details.allowed_methods,['GET'])

    def test_details_stop_before_endpoint_read_when_assignment_is_denied(self):
        person=types.SimpleNamespace(name='fixture-contact',check_permission=Mock(),links=[])
        self.f.get_doc.return_value=person
        self.api.business_types=Mock(return_value=[])
        self.f.db=types.SimpleNamespace(get_value=Mock(return_value='relay-contact'))
        self.f.get_all=Mock()
        self.api.readable_contact.side_effect=PermissionError('Not assigned')
        with self.assertRaises(PermissionError):self.api.contact_details('fixture-contact')
        self.f.get_all.assert_not_called()


class ChannelUITests(unittest.TestCase):
    setUp = ApiTests.setUp

    def test_contact_directory_bounds_search_and_denies_before_query(self):
        self.f.get_list.return_value = [types.SimpleNamespace(name=str(i)) for i in range(31)]
        result = self.api.contact_directory('a%_', 'before')
        self.assertEqual(len(result['items']), 30)
        self.assertEqual(result['next'], '29')
        query = self.f.get_list.call_args.kwargs
        self.assertEqual(query['filters']['full_name'], ['like', '%a\\%\\_%'])
        self.assertEqual(query['filters']['name'], ['>', 'before'])
        self.assertEqual(query['page_length'], 31)
        self.api.require_access.side_effect = PermissionError
        with self.assertRaises(PermissionError): self.api.contact_directory()
        for value in ({}, 'a' * 81):
            self.api.require_access.side_effect = None
            with self.assertRaises(ValueError): self.api.contact_directory(value)

    def test_profile_returns_only_safe_identity_and_rechecks_access(self):
        self.api.readable_contact.return_value = (types.SimpleNamespace(name='relay', display_name='Local', contact='person', secret='hidden'), None)
        self.assertEqual(self.api.contact_profile('relay'), {'name':'relay','display_name':'Local','contact':'person'})
        self.api.readable_contact.side_effect = PermissionError
        with self.assertRaises(PermissionError): self.api.contact_profile('relay')

    def test_channels_are_account_scoped_and_permission_filtered(self):
        with patch.dict(sys.modules, {'relay_core.settings': types.SimpleNamespace(value=lambda _: 'local')}):
            self.assertEqual(self.api.channel_options(), {'items':[]})
        self.assertEqual(self.f.get_list.call_args.kwargs['filters'], {'account':'local'})
        self.assertEqual(self.f.get_list.call_args.kwargs['fields'], ['name','channel','enabled'])
        self.api.require_access.side_effect = PermissionError
        with self.assertRaises(PermissionError): self.api.channel_options()

    def test_preferences_check_exact_business_before_read(self):
        check = Mock()
        with patch.dict(sys.modules, {'relay_core.conversation_start':types.SimpleNamespace(business_contact=check)}):
            self.assertEqual(self.api.contact_preferences('person','Customer','local'), {'items':[]})
            check.assert_called_with('person','Customer','local')
            self.assertEqual(self.f.get_list.call_args.kwargs['filters'], {'contact':'person','business_doctype':'Customer','business_name':'local'})
            check.side_effect = PermissionError
            with self.assertRaises(PermissionError): self.api.contact_preferences('person','Supplier','private')

    def test_consent_save_is_post_only_and_never_transfers_ownership(self):
        from contextlib import nullcontext
        self.f.PermissionError = PermissionError
        self.f.throw = lambda message, exception=ValueError: (_ for _ in ()).throw(exception(message))
        binding = types.SimpleNamespace(relay_contact='relay', channel='channel', verified=1)
        doc = Mock(); doc.name='preference';doc.endpoint='endpoint';doc.consent='Granted';doc.priority=2
        self.f.get_doc.side_effect = lambda dt, name: binding if dt == 'Relay Contact Endpoint' else Mock()
        self.f.db = types.SimpleNamespace(get_value=Mock(side_effect=['person', None]))
        self.f.new_doc = Mock(return_value=doc)
        self.f.cache = types.SimpleNamespace(lock=lambda *a, **kw:nullcontext())
        modules={'relay_core.conversation_start':types.SimpleNamespace(business_contact=Mock()),
                 'relay_core.channel_preferences':types.SimpleNamespace(scope_key=lambda *a:'scope')}
        with patch.dict(sys.modules, modules):
            result=self.api.save_contact_preference('person','Customer','local','endpoint','Granted',2)
            self.assertEqual(result,{'name':'preference','endpoint':'endpoint','consent':'Granted','priority':2})
            self.api.require_access.assert_called_with(configure=True)
            doc.save.assert_called_once()
            self.f.db.get_value.side_effect=None;self.f.db.get_value.return_value='other-person'
            with self.assertRaises(PermissionError): self.api.save_contact_preference('person','Customer','local','endpoint','Granted',2)
            self.f.db.get_value.return_value='person';binding.verified=0
            with self.assertRaises(ValueError): self.api.save_contact_preference('person','Customer','local','endpoint','Granted',2)
        self.assertEqual(self.api.save_contact_preference.allowed_methods,['POST'])
