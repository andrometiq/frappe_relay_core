import json
import sys
import types
import unittest
from unittest.mock import Mock, patch
from test_ai_skills import Doc, framework, module


def stub_framework():
    f = framework()
    f.ValidationError = ValueError
    f.QueryDeadlockError = type('QueryDeadlockError', (Exception,), {})
    f._dict = Doc
    f.cache = Mock()
    f.throw = Mock(side_effect=lambda message, exc=ValueError: (_ for _ in ()).throw(exc(message)))
    f.parse_json = json.loads
    return f


class DocumentSendTests(unittest.TestCase):
    def setUp(self):
        self.f = stub_framework()
        self.sends = module('relay_core/document_sends.py', self.f)
        self.order = Doc(doctype='YRP Sales Order', name='ORD/1', customer='CUST-A', customer_name='Ravi Traders',
                         transaction_date='2026-10-27')

    def test_placeholders_fill_text_and_keep_typed_filter_values(self):
        config = Doc(report_filters=json.dumps({'customer': '{{doc.customer}}', 'party': ['{{ doc.customer }}'],
                                                 'title': 'Due for {{doc.customer_name}}', 'ageing': 30}))
        self.order.amount = 1250.5
        config.report_filters = config.report_filters[:-1] + ', "amount": "{{doc.amount}}"}'
        self.assertEqual(self.sends.report_filters(config, self.order), {'customer': 'CUST-A', 'party': ['CUST-A'],
            'title': 'Due for Ravi Traders', 'ageing': 30, 'amount': 1250.5})
        self.assertEqual(self.sends.file_name(Doc(file_name='Order_{{doc.name}}'), self.order), 'Order_ORD_1.pdf')
        self.assertEqual(self.sends.file_name(Doc(file_name='../"x".PDF'), self.order), 'x_.PDF')
        with self.assertRaises(ValueError): self.sends.report_filters(Doc(report_filters='[1]'), self.order)

    def test_validation_names_unknown_fields_and_wrong_print_format(self):
        self.f.get_meta.return_value = Doc(fields=[Doc(fieldname='customer'), Doc(fieldname='contact_person')],
            get_field=lambda key: Doc(fieldtype='Link', options='Contact') if key == 'contact_person' else None)
        with self.assertRaisesRegex(ValueError, 'missing_field'):
            self.sends.validate(Doc(file_name='{{doc.missing_field}}.pdf'), 'YRP Sales Order')
        self.f.db.get_value.return_value = 'Sales Invoice'
        with self.assertRaisesRegex(ValueError, 'print format'):
            self.sends.validate(Doc(attachment_type='Print Format', print_format='Invoice'), 'YRP Sales Order')
        self.f.db.get_value.return_value = 'YRP Sales Order'
        self.sends.validate(Doc(attachment_type='Print Format', print_format='Essdee Order',
                                recipients='Document contact field', contact_field='contact_person'), 'YRP Sales Order')
        with self.assertRaisesRegex(ValueError, 'Contact field'):
            self.sends.validate(Doc(recipients='Document contact field', contact_field='customer'), 'YRP Sales Order')
        with self.assertRaisesRegex(ValueError, 'who receives'):
            self.sends.validate(Doc(recipients='Everyone'), 'YRP Sales Order')

    def test_pdf_goes_in_document_header_or_follows_the_template(self):
        hub = Mock(); hub.execute.return_value = {'id': '9001'}
        template = {'name': 'order_pdf', 'language': 'en', 'components': [{'type': 'body', 'parameters': []}]}
        listed = {'components': [{'type': 'HEADER', 'format': 'DOCUMENT'}, {'type': 'BODY', 'text': 'Hi {{1}}'}]}
        whatsapp = types.SimpleNamespace(client=lambda: hub, HubError=RuntimeError)
        modules = {'relay_core.whatsapp': whatsapp, 'relay_core.hub_channels': types.SimpleNamespace(hub_arguments=lambda channel, args: args),
                   'relay_core.whatsapp_templates': types.SimpleNamespace(definition=lambda *args: listed)}
        with patch.dict(sys.modules, modules):
            data, document = self.sends.with_document(template, 'CH-1', 'Order.pdf', b'%PDF-1')
            self.assertEqual(data['components'][0], {'type': 'header', 'parameters': [
                {'type': 'document', 'document': {'id': '9001', 'filename': 'Order.pdf'}}]})
            self.assertEqual(document, ('Order.pdf', b'%PDF-1', None))
            upload = hub.execute.call_args.args[0]
            self.assertEqual((upload['operation'], upload['media_type'], upload['mime_type']), ('messages.media_upload', 'document', 'application/pdf'))
            listed['components'] = listed['components'][1:]
            data, document = self.sends.with_document(template, 'CH-1', 'Order.pdf', b'%PDF-1')
            self.assertEqual(data, template)
            self.assertEqual(document[2]['arguments'], {'media_type': 'document', 'media_id': '9001', 'filename': 'Order.pdf'})
            hub.execute.return_value = {}
            with self.assertRaises(RuntimeError): self.sends.with_document(template, 'CH-1', 'Order.pdf', b'%PDF-1')

    def test_follow_up_document_only_after_an_accepted_template(self):
        send = Mock(side_effect=[{'status': 'Rejected', 'action': None}])
        self.sends.keep_copy = Mock()
        follow = {'operation': 'messages.media', 'arguments': {}}
        with patch.dict(sys.modules, {'relay_core.conversation_start': types.SimpleNamespace(send_business=send)}):
            self.sends.send_template(('PERSON-A', 'EP-1'), 'CH-1', {'name': 't'}, 'key', ('Customer', 'CUST-A'), ('a.pdf', b'x', follow))
            self.assertEqual(send.call_count, 1)
            send.side_effect = [{'status': 'Submitted', 'action': 'A-1'}, ValueError('window closed')]
            result = self.sends.send_template(('PERSON-A', 'EP-1'), 'CH-1', {'name': 't'}, 'key', ('Customer', 'CUST-A'), ('a.pdf', b'x', follow))
        self.assertEqual(result['document'], {'status': 'Rejected', 'error': 'window closed'})
        self.assertEqual(send.call_args.args[:5], ('PERSON-A', 'CH-1', 'whatsapp', follow, 'key-pdf'))
        self.assertEqual(send.call_args.kwargs, {'endpoint': 'EP-1'})

    def test_primary_contact_prefers_the_customer_primary_then_the_first_linked(self):
        self.f.get_all.return_value = ['PERSON-A', 'PERSON-B']
        self.f.get_meta.return_value = Doc(get_field=lambda key: Doc(fieldtype='Link'))
        self.f.db.get_value.return_value = 'PERSON-B'
        primary = Doc(recipients='Primary contact')
        self.assertEqual(self.sends.contacts(primary, self.order, 'Customer', 'CUST-A'), ['PERSON-B'])
        self.f.db.get_value.return_value = 'PERSON-OTHER'
        self.assertEqual(self.sends.contacts(primary, self.order, 'Customer', 'CUST-A'), ['PERSON-A'])
        self.assertEqual(self.sends.contacts(Doc(recipients='All business contacts'), self.order, 'Customer', 'CUST-A'), ['PERSON-A', 'PERSON-B'])
        self.order.contact_person = 'PERSON-C'
        self.assertEqual(self.sends.contacts(Doc(recipients='Document contact field', contact_field='contact_person'),
                                             self.order, 'Customer', 'CUST-A'), ['PERSON-C'])
        self.f.get_all.return_value = []
        self.assertEqual(self.sends.contacts(primary, self.order, 'Customer', 'CUST-A'), [])

    def test_targets_send_to_every_number_or_the_mobile_number(self):
        self.sends.relay_ready = Mock(return_value='RELAY-1')
        self.f.get_all.return_value = [Doc(name='EP-1', endpoint='919000000001'), Doc(name='EP-2', endpoint='919000000002')]
        self.f.db.get_value.return_value = '+91 90000 00002'
        identity = types.SimpleNamespace(phone_number=lambda value: '919000000002' if value else None)
        with patch.dict(sys.modules, {'relay_core.identity': identity}):
            self.assertEqual(self.sends.targets(Doc(recipients='All business contacts'), 'PERSON-A', 'CH-1'),
                             [('PERSON-A', 'EP-1'), ('PERSON-A', 'EP-2')])
            self.assertEqual(self.sends.targets(Doc(recipients='Primary contact'), 'PERSON-A', 'CH-1'), [('PERSON-A', 'EP-2')])
            self.f.get_all.return_value = []
            with self.assertRaisesRegex(ValueError, 'no WhatsApp number'):
                self.sends.targets(Doc(recipients='Primary contact'), 'PERSON-A', 'CH-1')

    def test_relay_contact_is_created_from_the_contact_numbers_only_when_readable(self):
        person = Doc(name='PERSON-A', full_name='Ravi')
        self.f.get_doc.side_effect = lambda values, *args: person if values == 'Contact' else Doc(values, name='RELAY-NEW')
        enroll = Mock()
        modules = {'relay_core.contact_lifecycle': types.SimpleNamespace(enroll=enroll, relay_contact=lambda name: None),
                   'relay_core.identity': types.SimpleNamespace(contact_identities=lambda doc: {'WhatsApp': {'919000000001'}})}
        with patch.dict(sys.modules, modules):
            self.assertEqual(self.sends.relay_ready('PERSON-A', 'CH-1'), 'RELAY-NEW')
            enroll.assert_called_once_with('RELAY-NEW', 'CH-1', 'WhatsApp', '919000000001')
            person.denied = True
            with self.assertRaises(PermissionError): self.sends.relay_ready('PERSON-A', 'CH-1')


class EventRuleDocumentTests(unittest.TestCase):
    def setUp(self):
        self.f = stub_framework()
        self.f.cache.get_value.return_value = {('YRP Sales Order', 'on_submit')}
        self.intents = []
        automation = types.SimpleNamespace(internal_save=lambda doc, **kw: self.intents.append(doc))
        tools = module('relay_core/ai/tools.py', self.f)
        self.events = module('relay_core/business_events.py', self.f,
            {'relay_core.ai.tools': tools, 'relay_core.automation.service': automation})
        self.events.snapshot = Mock(return_value={'name': 'order_pdf', 'language': 'en', 'components': [{'type': 'body', 'parameters': []}]})
        self.events.snapshot_ownership = Mock()
        self.f.get_doc.side_effect = lambda values: Doc(values, name='DELIVERY-%d' % len(self.intents))
        self.f.db.exists.return_value = False
        self.rule = Doc(name='RULE-1', modified='v1', recipient_field='customer', business_doctype='Customer', run_as_user='service',
                        channel='CH-1', recipients='All business contacts', condition='doc.commitment_level_label')
        self.order = Doc(doctype='YRP Sales Order', name='ORD-1', customer='CUST-A', commitment_level_label='Level 1')
        self.sends = types.SimpleNamespace(contacts=Mock(return_value=['PERSON-A', 'PERSON-B']),
            targets=Mock(side_effect=[[('PERSON-A', 'EP-1'), ('PERSON-A', 'EP-2')], ValueError('no number')]))
        self.patch = patch.dict(sys.modules, {'relay_core.document_sends': self.sends}); self.patch.start(); self.addCleanup(self.patch.stop)
        self.f.safe_eval = lambda code, globals_, locals_: eval(code, {}, locals_)

    def test_condition_false_creates_no_delivery(self):
        self.order.commitment_level_label = None
        self.events.capture(self.rule, self.order, 'on_submit')
        self.assertEqual(self.intents, [])
        self.sends.contacts.assert_not_called()

    def test_every_number_gets_its_own_delivery_and_a_contact_without_number_is_skipped(self):
        self.events.capture(self.rule, self.order, 'on_submit')
        self.assertEqual([(row.contact, row.endpoint) for row in self.intents], [('PERSON-A', 'EP-1'), ('PERSON-A', 'EP-2')])
        self.assertNotEqual(self.intents[0].event_key, self.intents[1].event_key)
        self.f.log_error.assert_called_once()
        self.assertEqual(self.events.snapshot_ownership.call_args.args[-1], 'EP-2')

    def test_no_usable_number_fails_the_rule(self):
        self.sends.targets = Mock(side_effect=ValueError('no number'))
        with self.assertRaisesRegex(ValueError, 'usable WhatsApp number'):
            self.events.capture(self.rule, self.order, 'on_submit')

    def test_pdf_rule_dispatch_renders_as_rule_user_and_sends_to_the_delivery_endpoint(self):
        self.rule.update(attachment_type='Print Format', print_format='Essdee Order')
        delivery = Doc(payload=json.dumps({'name': 'order_pdf', 'language': 'en', 'components': []}), contact='PERSON-A',
                       endpoint='EP-2', event_key='KEY', business_doctype='Customer', business_name='CUST-A',
                       source_doctype='YRP Sales Order', source_name='ORD-1')
        self.f.get_doc.side_effect = lambda doctype, name: self.order
        self.sends.render_pdf = Mock(return_value=('Order_ORD-1.pdf', b'%PDF'))
        self.sends.with_document = Mock(return_value=({'name': 'order_pdf'}, ('Order_ORD-1.pdf', b'%PDF', None)))
        self.sends.send_template = Mock(return_value={'status': 'Submitted'})
        with patch.dict(sys.modules, {'relay_core.conversation_start': types.SimpleNamespace(send_business=Mock())}):
            self.assertEqual(self.events.send_delivery(delivery, self.rule), {'status': 'Submitted'})
        self.sends.render_pdf.assert_called_once_with(self.rule, self.order)
        self.assertEqual(self.sends.send_template.call_args.args, (('PERSON-A', 'EP-2'), 'CH-1', {'name': 'order_pdf'},
                         'KEY', ('Customer', 'CUST-A'), ('Order_ORD-1.pdf', b'%PDF', None)))

    def test_recipient_choices_need_a_fixed_whatsapp_channel(self):
        self.sends.validate = Mock()
        self.f.db.get_value.return_value = 'WhatsApp'
        self.events.validate_document_options(self.rule)
        for change in ({'use_preferences': 1}, {'channel': None}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'fixed WhatsApp channel'):
                self.events.validate_document_options(Doc(self.rule, **change))


if __name__ == '__main__':
    unittest.main()
