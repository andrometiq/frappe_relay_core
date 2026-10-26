"""Number-based WhatsApp sends: recipient resolution, journal routing, keys, templates and per-item results."""
import unittest
from unittest.mock import Mock, patch
import frappe
from frappe import _dict
from relay_core import messaging_api

NUMBER = '919876543210'
NAMED = {'parameter_format': 'NAMED', 'components': [
    {'type': 'HEADER', 'format': 'IMAGE'}, {'type': 'BODY', 'text': 'Hi {{customer_name}}, order {{order}} is ready'},
    {'type': 'BUTTONS', 'buttons': [{'type': 'URL', 'text': 'Track', 'url': 'https://shop.example/{{1}}'}]}]}
POSITIONAL = {'components': [{'type': 'BODY', 'text': 'Order {{1}} for {{2}}'}]}


def throw(message, exc=frappe.ValidationError):
    raise exc(message)


class SendTests(unittest.TestCase):
    def setUp(self):
        self.sent = Mock(return_value={'action': 'ACT-1', 'status': 'Submitted', 'message': 'RELAY-MSG-0000000001'})
        self.window = Mock(return_value={NUMBER})
        patches = [patch.object(messaging_api, 'require_access'), patch.object(messaging_api.frappe, 'throw', throw),
                   patch.object(messaging_api, 'whatsapp_channel', return_value='WA'),
                   patch.object(messaging_api.service_window, 'open_numbers', self.window),
                   patch.object(messaging_api, 'recipient', return_value=('Contact Asha', ('Customer', 'Asha Stores'))),
                   patch.object(messaging_api.whatsapp, 'send', self.sent), patch('relay_core.identity.default_region', return_value='IN')]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_endpoints_are_post_only(self):
        for method in (messaging_api.send_text, messaging_api.send_media, messaging_api.send_template,
                       messaging_api.send_messages):
            self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[method], ['POST'])

    def test_text_goes_through_the_journal_with_the_contact_and_its_business(self):
        result = messaging_api.send_text('+91 98765 43210', 'Your order is ready')
        message = self.sent.call_args.args[0]
        self.assertEqual({key: message[key] for key in ('operation', 'arguments', 'contact', 'business_doctype', 'business_name')},
                         {'operation': 'messages.send', 'arguments': {'body': 'Your order is ready'}, 'contact': 'Contact Asha',
                          'business_doctype': 'Customer', 'business_name': 'Asha Stores'})
        self.assertEqual(result, {'action': 'ACT-1', 'status': 'Submitted', 'message': 'RELAY-MSG-0000000001',
                                  'number': NUMBER, 'contact': 'Contact Asha', 'key': message['key']})

    def test_a_repeat_keeps_its_key_and_a_given_key_is_used(self):
        first = messaging_api.send_text(NUMBER, 'Your order is ready')['key']
        self.assertEqual(messaging_api.send_text('+' + NUMBER, 'Your order is ready')['key'], first)
        self.assertNotEqual(messaging_api.send_text(NUMBER, 'Another text')['key'], first)
        self.assertEqual(messaging_api.send_text(NUMBER, 'Your order is ready', key='order-25')['key'], 'api-order-25')
        for bad in ('has space', 'x' * 101, 25):
            with self.subTest(key=bad), self.assertRaises(frappe.ValidationError):
                messaging_api.send_text(NUMBER, 'Your order is ready', key=bad)

    def test_text_and_media_outside_the_reply_window_fail_before_any_send(self):
        self.window.return_value = set()
        for call in (lambda: messaging_api.send_text(NUMBER, 'Hello'),
                     lambda: messaging_api.send_media(NUMBER, 'https://cdn.example/a.jpg', 'image')):
            with self.assertRaisesRegex(frappe.ValidationError, '24-hour reply window'):
                call()
        self.sent.assert_not_called()

    def test_media_checks_the_link_type_and_file_name(self):
        messaging_api.send_media(NUMBER, 'https://cdn.example/bill.pdf', 'document', caption='Bill', filename='bill.pdf')
        self.assertEqual(self.sent.call_args.args[0]['arguments'], {'media_type': 'document', 'media_url': 'https://cdn.example/bill.pdf',
                                                                   'caption': 'Bill', 'filename': 'bill.pdf'})
        for args in (('http://cdn.example/a.jpg', 'image'), ('https://cdn.example/a.jpg', 'sticker'),
                     ('https://cdn.example/a.jpg', 'image', None, 'a.jpg')):
            with self.subTest(args=args), self.assertRaises(frappe.ValidationError):
                messaging_api.send_media(NUMBER, *args)

    def test_templates_fill_named_positional_and_header_media_values(self):
        with patch('relay_core.whatsapp_templates.definition', return_value=NAMED):
            messaging_api.send_template(NUMBER, 'order_ready', 'en', {'customer_name': 'Asha', 'order': 'SO-25', 'button:0': 'SO-25'},
                                        header_media_url='https://cdn.example/a.jpg')
        components = self.sent.call_args.args[0]['arguments']['components']
        self.assertEqual(components[0], {'type': 'header', 'parameters': [{'type': 'image', 'image': {'link': 'https://cdn.example/a.jpg'}}]})
        self.assertEqual(components[1]['parameters'][0], {'type': 'text', 'text': 'Asha', 'parameter_name': 'customer_name'})
        with patch('relay_core.whatsapp_templates.definition', return_value=POSITIONAL):
            messaging_api.send_template(NUMBER, 'order', 'en', '["SO-25", "Asha"]')
        self.assertEqual(self.sent.call_args.args[0]['arguments']['components'],
                         [{'type': 'body', 'parameters': [{'type': 'text', 'text': 'SO-25'}, {'type': 'text', 'text': 'Asha'}]}])
        self.window.assert_not_called()  # Templates open the conversation.

    def test_template_values_must_match_the_template(self):
        cases = [(NAMED, {'customer_name': 'Asha', 'order': 'SO-25', 'button:0': 'x'}, None, 'Missing Header image URL'),
                 (POSITIONAL, ['SO-25'], None, 'Missing Body value 2'), (POSITIONAL, ['a', 'b', 'c'], None, 'more values'),
                 (POSITIONAL, 'not json', None, '')]
        for template, params, header, message in cases:
            with self.subTest(params=params), patch('relay_core.whatsapp_templates.definition', return_value=template):
                with self.assertRaisesRegex(Exception, message):
                    messaging_api.send_template(NUMBER, 'order', 'en', params, header)
        with patch('relay_core.whatsapp_templates.definition', return_value=None), \
                self.assertRaisesRegex(frappe.ValidationError, 'Template not found'):
            messaging_api.send_template(NUMBER, 'missing', 'en')
        self.sent.assert_not_called()

    def test_sends_are_denied_without_relay_access_before_any_lookup(self):
        calls = (lambda: messaging_api.send_text(NUMBER, 'Hello'),
                 lambda: messaging_api.send_media(NUMBER, 'https://cdn.example/a.jpg', 'image'),
                 lambda: messaging_api.send_template(NUMBER, 'order', 'en', ['SO-25']))
        with patch.object(messaging_api, 'require_access', side_effect=frappe.PermissionError), \
                patch('relay_core.whatsapp_templates.definition') as definition:
            for call in calls:
                with self.assertRaises(frappe.PermissionError):
                    call()
        definition.assert_not_called()
        self.sent.assert_not_called()


class ListTests(unittest.TestCase):
    def test_each_item_gets_its_own_result_and_a_failure_rolls_back_only_itself(self):
        db = Mock()
        with patch.object(messaging_api, 'require_access'), patch.object(messaging_api.frappe, 'db', db), \
                patch.object(messaging_api.frappe, 'throw', throw), patch.object(messaging_api.frappe, 'clear_messages') as clear, \
                patch.object(messaging_api, 'send_text', side_effect=[{'action': 'ACT-1'}, frappe.PermissionError('Not permitted')]), \
                patch.object(messaging_api, 'SENDS', {}) as sends:
            sends.update(text=messaging_api.send_text, media=messaging_api.send_media)
            result = messaging_api.send_messages([{'type': 'text', 'number': NUMBER, 'body': 'Hi'},
                                                  {'type': 'text', 'number': NUMBER, 'body': 'Hi'},
                                                  {'type': 'media', 'number': NUMBER, 'body': 'Hi'}, {'type': 'call'}, 'text'])
        self.assertEqual(result['results'][0], {'index': 0, 'ok': True, 'action': 'ACT-1'})
        self.assertEqual([(row['ok'], row.get('error')) for row in result['results'][1:]],
                         [(False, 'Not permitted'), (False, 'Give the fields a media send needs and no others'),
                          (False, 'type must be text, media or template'), (False, 'type must be text, media or template')])
        self.assertEqual(db.rollback.call_count, 4)
        self.assertEqual(clear.call_count, 4)

    def test_lists_are_capped_and_denied_without_access(self):
        with patch.object(messaging_api, 'require_access'), patch.object(messaging_api.frappe, 'throw', throw):
            for items in ([], [{'type': 'text'}] * 101, {'type': 'text'}):
                with self.subTest(size=len(items)), self.assertRaises(frappe.ValidationError):
                    messaging_api.send_messages(items)
        with patch.object(messaging_api, 'require_access', side_effect=frappe.PermissionError):
            with self.assertRaises(frappe.PermissionError):
                messaging_api.send_messages([{'type': 'text'}])


class RecipientTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        patches = [patch.object(messaging_api.frappe, 'db', self.db), patch.object(messaging_api.frappe, 'throw', throw),
                   patch('relay_core.identity.default_region', return_value='IN')]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def binding(self, verified=1, mobile='+' + NUMBER):
        def get_value(doctype, filters, fields=None, as_dict=False):
            return {'Relay Contact Endpoint': _dict(relay_contact='RELAY-CON-1', verified=verified),
                    'Relay Contact': 'Contact Asha', 'Contact': _dict(mobile_no=mobile, phone='')}[doctype]
        self.db.get_value.side_effect = get_value

    def test_a_known_number_uses_its_primary_business_or_the_given_one(self):
        self.binding()
        with patch('relay_core.business_access.primary', return_value=('Customer', 'Asha Stores')):
            self.assertEqual(messaging_api.recipient('WA', NUMBER, None, None), ('Contact Asha', ('Customer', 'Asha Stores')))
        with patch('relay_core.business_access.primary', return_value=None) as primary:
            with self.assertRaisesRegex(frappe.ValidationError, 'primary business record'):
                messaging_api.recipient('WA', NUMBER, None, None)
            self.assertEqual(messaging_api.recipient('WA', NUMBER, 'Supplier', 'B')[1], ('Supplier', 'B'))
            self.assertEqual(primary.call_count, 1)

    def test_a_revoked_or_secondary_number_is_refused(self):
        for binding, message in (({'verified': 0}, 'revoked'), ({'mobile': '+919000000001'}, 'main mobile')):
            self.binding(**binding)
            with self.subTest(message=message), self.assertRaisesRegex(frappe.ValidationError, message):
                messaging_api.recipient('WA', NUMBER, 'Customer', 'Asha Stores')

    def test_an_unknown_number_needs_a_business_and_the_contact_create_rules(self):
        self.db.get_value.return_value = None
        with self.assertRaisesRegex(frappe.ValidationError, 'business_doctype'):
            messaging_api.recipient('WA', NUMBER, None, None)
        create = Mock(return_value={'contact': 'Contact New'})
        with patch.dict('sys.modules', {'relay_core.contacts': Mock(create=create)}):
            self.assertEqual(messaging_api.recipient('WA', NUMBER, 'Customer', 'Asha Stores'),
                             ('Contact New', ('Customer', 'Asha Stores')))
            create.assert_called_once_with('+' + NUMBER, NUMBER, 'WA', [{'doctype': 'Customer', 'name': 'Asha Stores'}])
            self.db.commit.assert_called_once()
            create.side_effect = frappe.PermissionError('Not permitted')
            with self.assertRaises(frappe.PermissionError):  # Only managers create contacts.
                messaging_api.recipient('WA', NUMBER, 'Customer', 'Asha Stores')


if __name__ == '__main__':
    unittest.main()
