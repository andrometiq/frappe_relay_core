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
        self.f.PermissionError=ValueError
        self.person_access=self.enterContext(patch('relay_core.business_access.require_person'))
        self.enterContext(patch('relay_core.business_access.allowed_types', return_value={'Customer'}))
        self.people_query=self.enterContext(patch('relay_core.business_access.people_query', side_effect=lambda **kwargs: self.f.qb.get_query('Contact', **kwargs)))
        self.api.contact_query=Mock(return_value='independent_business_scope')
        self.f.qb=Mock()
        search=self.f.qb.get_query.return_value
        search.where.return_value=search
        search.run.side_effect=lambda **kwargs:self.f.get_list.return_value

    def test_write_is_post_only_and_requires_config_access(self):
        self.assertEqual(self.api.update_channel.allowed_methods,['POST'])
        self.api.update_channel('RELAY-CH-0000000001',' Account ', '1')
        self.assertEqual(self.api.require_access.call_args_list[0].kwargs,{'configure':True})
        doc=self.f.get_doc.return_value
        self.assertEqual(doc.account,'Account');self.assertEqual(doc.enabled,1)
        doc.check_permission.assert_any_call('write');doc.save.assert_called_once()

    def use_role(self, role):
        """Answer permission checks from the role -> DocType rights of the DocPerm matrix."""
        self.f.session = types.SimpleNamespace(user='test@example.invalid')
        self.f.get_roles = lambda: [role]
        rights={
            'Relay Communication User':set(),
            'Relay Communication Team User':{'all_teams'},
            'Relay Communication Manager':{'all_teams',('Relay Team','write'),('Relay WhatsApp Billing Month','read'),
                                           ('Relay AI Skill','write'),('Relay Business Event Rule','write')},
            'System Manager':{'all_teams',('Relay Team','write'),('Relay WhatsApp Billing Month','read'),
                              ('Relay AI Skill','write'),('Relay Business Event Rule','write'),('Relay Settings','write')},
        }[role]
        self.f.has_permission=lambda doctype,ptype='read',**kwargs:(doctype,ptype) in rights
        self.api.can_manage=lambda:('Relay Team','write') in rights
        self.api.can_configure=lambda:('Relay Settings','write') in rights
        self.api.sees_all_teams=lambda:'all_teams' in rights

    def test_capabilities_keep_enabled_channels_and_add_their_features(self):
        self.use_role('Relay Communication Manager')
        whatsapp=Mock();whatsapp.name='WhatsApp';whatsapp.get_features.return_value={'templates':True}
        numbers=[{'name':'WA-1','label':'Sales','address':'+91 1'},{'name':'WA-2','label':'Support','address':'+91 2'}]
        with patch('relay_core.channels.enabled',return_value=[whatsapp]),patch('relay_core.hub_channels.site_numbers',return_value=numbers) as listed:
            result=self.api.capabilities()
        self.assertEqual(result,{'contact_transfer':True,'manage':True,'teams':False,'teams_enabled':False,'folders':True,'billing':True,'multi_team':True,'configure':False,
                                 'ai':True,'skills':True,'business_events':True,'flows':True,
                                 'enabled_channels':['WhatsApp'],'channels':{'WhatsApp':{'templates':True}},'whatsapp_numbers':numbers,
                                 'inbox_channels':[dict(row,medium='WhatsApp') for row in numbers]})
        listed.assert_called_once_with('WhatsApp')

    def test_inbox_channels_list_the_site_channels_of_every_enabled_medium(self):
        self.use_role('Relay Communication User')
        mediums=[]
        for name in ('WhatsApp','Email'):
            medium=Mock();medium.name=name;medium.get_features.return_value={};mediums.append(medium)
        rows={'WhatsApp':[{'name':'WA-1','label':'Sales','address':'+91 1'}],'Email':[{'name':'EM-1','label':'Desk','address':'desk@x'}]}
        with patch('relay_core.channels.enabled',return_value=mediums),patch('relay_core.hub_channels.site_numbers',side_effect=rows.get):
            result=self.api.capabilities()
        self.assertEqual(result['inbox_channels'],[{'name':'WA-1','label':'Sales','address':'+91 1','medium':'WhatsApp'},
                                                   {'name':'EM-1','label':'Desk','address':'desk@x','medium':'Email'}])
        self.assertEqual(result['whatsapp_numbers'],rows['WhatsApp'])

    def test_capabilities_list_no_numbers_when_whatsapp_is_off(self):
        self.use_role('Relay Communication User')
        with patch('relay_core.channels.enabled',return_value=[]),patch('relay_core.hub_channels.site_numbers') as listed:
            result=self.api.capabilities()
        self.assertEqual((result['whatsapp_numbers'],result['inbox_channels']),([],[]))
        listed.assert_not_called()

    def test_capabilities_follow_each_role(self):
        flags=('manage','teams','billing','multi_team','configure','skills','business_events')
        expected={
            'Relay Communication User':(False,False,False,False,False,False,False),
            'Relay Communication Team User':(False,False,False,True,False,False,False),
            'Relay Communication Manager':(True,False,True,True,False,True,True),
            'System Manager':(True,False,True,True,True,True,True),
        }
        for role,values in expected.items():
            self.use_role(role)
            with patch('relay_core.channels.enabled',return_value=[]):
                result=self.api.capabilities()
            self.assertEqual(tuple(result[flag] for flag in flags),values,role)
            self.assertEqual(result['contact_transfer'], role in ('Relay Communication Manager', 'System Manager'))

    def test_folders_and_teams_switches_hide_their_capabilities(self):
        self.use_role('System Manager')
        with patch('relay_core.channels.enabled',return_value=[]),patch('relay_core.features.is_enabled',return_value=False):
            result=self.api.capabilities()
        self.assertEqual((result['manage'],result['teams'],result['teams_enabled'],result['folders']),(True,False,False,False))

    def test_invalid_input_does_not_write(self):
        for name,account,enabled in [('','valid',1),('RELAY-CH-0000000001','',1),('RELAY-CH-0000000001','valid','garbage')]:
            with self.assertRaises(ValueError):self.api.update_channel(name,account,enabled)
        self.f.get_doc.return_value.save.assert_not_called()

    def test_paging_is_bounded_ordered_and_permission_aware(self):
        class Row(dict):
            __getattr__ = dict.get
        self.f.get_list.return_value=[Row(name=f'RELAY-MSG-{i:010}',channel='RELAY-CH-0000000001') for i in range(101,0,-1)]
        self.f.get_doc.return_value.get.side_effect = lambda key: {'channel': 'Telegram'}.get(key)
        page_query=Mock();page_query.return_value.run.return_value=self.f.get_list.return_value
        with patch.dict(sys.modules,**{'relay_core.timeline':types.SimpleNamespace(page_query=page_query)}):
            result=self.api.messages('RELAY-CON-0000000001',limit=9999)
        self.assertEqual(len(result['items']),100);self.assertTrue(result['has_more'])
        self.assertEqual(result['first'],'RELAY-MSG-0000000002')
        self.assertEqual(page_query.call_args_list[1].args[2],101)
        self.assertTrue({'relay_contact','business_doctype','business_name'}.issubset(page_query.call_args_list[1].args[0]))
        self.api.readable_contact.assert_called_with('RELAY-CON-0000000001')
        self.f.get_doc.return_value.check_permission.assert_called_with('read')

    def test_message_business_context_is_not_returned_without_contact_access(self):
        self.api.readable_contact.side_effect = PermissionError('private conversation')
        with self.assertRaises(PermissionError):
            self.api.messages('RELAY-CON-0000000001')
        self.f.get_doc.assert_not_called()

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
        args=self.f.qb.get_query.call_args
        self.assertEqual(args.args,('Relay Contact',))
        self.assertFalse(args.kwargs['ignore_permissions'])
        self.assertEqual(args.kwargs['limit'],51)
        self.assertEqual(self.f.qb.get_query.return_value.where.call_args.args[0].get_sql(),'(independent_business_scope)')
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
            check_permission=Mock(), has_permission=Mock(return_value=True),
            links=[types.SimpleNamespace(link_doctype='Customer', link_name=name) for name in ['visible', 'private']])
        person.links.append(types.SimpleNamespace(link_doctype='Supplier', link_name='unconfigured'))
        docs = {('Contact', 'fixture-contact'): person,
                ('Customer', 'visible'): types.SimpleNamespace(has_permission=lambda _: True),
                ('Customer', 'private'): types.SimpleNamespace(has_permission=lambda _: False),
                ('Relay Channel', 'wa'): types.SimpleNamespace(channel='WhatsApp', has_permission=lambda _: True),
                ('Relay Channel', 'email'): types.SimpleNamespace(channel='Email', has_permission=lambda _: True)}
        self.f.get_doc.side_effect=lambda dt,name:docs[(dt,name)]
        self.api.business_types=Mock(return_value=['Customer'])
        self.f.db=types.SimpleNamespace(get_value=Mock(return_value='relay-contact'), exists=lambda dt,name: True)
        endpoint=types.SimpleNamespace(name='binding', channel='wa', verified=0)
        self.f.get_all=Mock(return_value=[endpoint,types.SimpleNamespace(channel='email')])
        with patch('relay_core.business_access.primary_record', return_value=None), patch('relay_core.contacts.can_manage_links', return_value=False):
            result=self.api.contact_details('fixture-contact')
        self.assertEqual(result['links'],[{'doctype':'Customer','name':'visible'}, {'doctype':'Customer','name':'private'}])
        self.assertIsNone(result['primary'])
        self.assertEqual([row.channel for row in result['endpoints']],['wa','email'])
        self.assertEqual([row.provider for row in result['endpoints']],['WhatsApp','Email'])
        self.api.readable_contact.assert_called_once_with('relay-contact')
        person.check_permission.assert_not_called()
        self.assertEqual(self.api.contact_details.allowed_methods,['GET'])
        self.assertEqual((result['can_edit_links'], result['can_set_primary']), (True, True))
        person.has_permission.assert_called_once_with('write')
        person.has_permission.return_value=False
        with patch('relay_core.business_access.primary_record', return_value=None), patch('relay_core.contacts.can_manage_links', return_value=False):
            result=self.api.contact_details('fixture-contact')
        self.assertEqual((result['can_edit_links'], result['can_set_primary']), (False, False), 'Read-only users get no link controls')

    def test_details_stop_before_endpoint_read_when_assignment_is_denied(self):
        person=types.SimpleNamespace(name='fixture-contact',check_permission=Mock(),links=[])
        self.f.get_doc.return_value=person
        self.api.business_types=Mock(return_value=[])
        self.f.db=types.SimpleNamespace(get_value=Mock(return_value='relay-contact'), exists=lambda dt,name: True)
        self.f.get_all=Mock()
        self.api.readable_contact.side_effect=PermissionError('Not assigned')
        with self.assertRaises(PermissionError):self.api.contact_details('fixture-contact')
        self.f.get_all.assert_not_called()

    def test_details_without_a_conversation_need_contact_read(self):
        person=types.SimpleNamespace(name='fixture-contact',check_permission=Mock(side_effect=PermissionError),links=[])
        self.f.get_doc.return_value=person
        self.f.db=types.SimpleNamespace(get_value=Mock(return_value=None))
        self.person_access.side_effect=PermissionError
        with self.assertRaises(PermissionError):self.api.contact_details('fixture-contact')
        self.api.readable_contact.assert_not_called()


class ChannelUITests(unittest.TestCase):
    setUp = ApiTests.setUp

    def test_contact_directory_bounds_search_and_denies_before_query(self):
        self.f.get_list.return_value = [types.SimpleNamespace(name=str(i)) for i in range(31)]
        result = self.api.contact_directory('a%_', 'before')
        self.assertEqual(len(result['items']), 30)
        self.assertEqual(result['next'], '29')
        query = self.people_query.call_args.kwargs
        self.assertEqual(query['filters'], [['Contact', 'name', '>', 'before']])
        self.assertIn(['Contact', 'full_name', 'like', '%a\\%\\_%'], query['or_filters'])
        self.assertIn(['Contact', 'mobile_no', 'like', '%a\\%\\_%'], query['or_filters'])
        self.assertEqual(query['limit'], 31)
        self.api.business_types = Mock(return_value=['Customer'])
        self.api.contact_directory('', None, 'Customer')
        self.assertEqual(self.people_query.call_args.kwargs['filters'], [['Dynamic Link', 'link_doctype', '=', 'Customer']])
        self.assertTrue(self.people_query.call_args.kwargs['distinct'])
        with self.assertRaises(ValueError): self.api.contact_directory('', None, 'User')
        self.api.require_access.side_effect = PermissionError
        with self.assertRaises(PermissionError): self.api.contact_directory()
        for value in ({}, 'a' * 81):
            self.api.require_access.side_effect = None
            with self.assertRaises(ValueError): self.api.contact_directory(value)

    def test_profile_returns_only_safe_identity_and_rechecks_access(self):
        person = types.SimpleNamespace(name='person', mobile_no='', phone=' +91 98765 43210 ', email_id='')
        self.api.readable_contact.return_value = (types.SimpleNamespace(name='relay', display_name='Local', contact='person', secret='hidden'), person)
        header = {'doctype': 'Customer', 'name': 'C1', 'title': 'Primary customer'}
        links = [('Customer', 'C1'), ('Supplier', 'S1')]
        self.f.has_permission = Mock(side_effect=lambda doctype, ptype, doc: doctype == 'Customer')
        with patch('relay_core.business_access.primary_record', return_value=header) as primary, \
                patch('relay_core.business_access.candidates', return_value=links), \
                patch('relay_core.contacts.contact_emails', return_value={'person': 'ann@example.invalid'}) as emails:
            self.assertEqual(self.api.contact_profile('relay'), {'name':'relay','display_name':'Local','contact':'person',
                                                                 'primary': header, 'link_count': 1,
                                                                 'phone': '+91 98765 43210', 'email': 'ann@example.invalid'})
        primary.assert_called_once_with('relay', links)
        emails.assert_called_once_with(['person'])
        self.api.readable_contact.side_effect = PermissionError
        with self.assertRaises(PermissionError): self.api.contact_profile('relay')

    def test_channels_are_account_scoped_and_permission_filtered(self):
        with patch.dict(sys.modules, {'relay_core.settings': types.SimpleNamespace(value=lambda _: 'local')}):
            self.assertEqual(self.api.channel_options(), {'items':[]})
        self.assertEqual(self.f.get_list.call_args.kwargs['filters'], {'account':'local'})
        self.assertEqual(self.f.get_list.call_args.kwargs['fields'], ['name','channel','enabled','label','address','is_default'])
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


class MessageDisplayApiTests(unittest.TestCase):
    setUp = ApiTests.setUp

    def test_snapshots_and_context_decorate_even_the_anchor(self):
        class Row(dict):
            __getattr__ = dict.get
        row = Row(name='RELAY-MSG-0000000001', channel='Customer support-001', relay_contact='RELAY-CON-0000000001',
                  provider_context={'provider':'Email', 'mailbox_addresses':['forged@example.invalid']})
        channel = Mock()
        channel.get.side_effect = {'title':'Customer support','channel':'Email','mailbox_address':'support@example.invalid'}.get
        self.f.get_doc.return_value = channel
        self.f.get_list.return_value = [row]
        result = self.api.message_snapshots(row.relay_contact, [row.name])
        self.assertEqual(result['items'][0]['provider_context']['mailbox_addresses'], ['support@example.invalid'])
        # Refreshed rows replace loaded rows, so they keep the contact and business of the message.
        self.assertLessEqual({'relay_contact', 'business_doctype', 'business_name'}, set(self.f.get_list.call_args.kwargs['fields']))
        channel.check_permission.assert_called_with('read')
        doc = Mock(channel=row.channel, relay_contact=row.relay_contact)
        doc.get.side_effect = row.get
        self.f.get_doc.side_effect = lambda doctype, name: doc if doctype == 'Relay Message' else channel
        self.api.messages = Mock(return_value={'items':[],'first':None,'last':None,'has_more':False})
        result = self.api.message_context(row.name)
        self.assertEqual(result['items'][0]['channel_title'], 'Customer support')
        self.assertEqual(result['items'][0]['provider_context']['mailbox_addresses'], ['support@example.invalid'])
        self.api.require_access.side_effect = PermissionError
        with self.assertRaises(PermissionError): self.api.message_context(row.name)
        with self.assertRaises(PermissionError): self.api.message_snapshots(row.relay_contact, [row.name])

    def test_channel_names_accept_new_and_legacy_names_without_relaxing_message_ids(self):
        for value in ('Customer support-001','RELAY-CH-0000000001'):
            self.api.validate_reference(value, 'CH')
        for value in ('', None, 'line\nbreak', 'x'*141):
            with self.assertRaises(ValueError): self.api.validate_reference(value, 'CH')
        with self.assertRaises(ValueError): self.api.validate_reference('Customer support-001', 'MSG')

    def test_ticket_names_start_at_five_digits_and_grow(self):
        for value in ('TKT-00001', 'TKT-99999', 'TKT-100000'):
            self.api.validate_reference(value, 'TKT')
        for value in ('RELAY-TKT-0000000001', 'TKT-1', 'TKT-0001', 'TKT-00001\n', None):
            with self.assertRaises(ValueError): self.api.validate_reference(value, 'TKT')


def setUpModule():
    """These tests cover AI, folder and team behavior, so every feature switch is on."""
    from unittest import addModuleCleanup, mock
    for target in ('relay_core.ai_features.is_enabled', 'relay_core.features.is_enabled'):
        switch = mock.patch(target, return_value=True)
        switch.start()
        addModuleCleanup(switch.stop)
