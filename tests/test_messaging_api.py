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
                   patch.object(messaging_api, 'sending_channel', return_value='WA'),
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
        self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[messaging_api.send_status], ['GET'])

    def test_text_goes_through_the_journal_with_the_contact_and_its_business(self):
        result = messaging_api.send_text('+91 98765 43210', 'Your order is ready')
        message = self.sent.call_args.args[0]
        self.assertEqual({key: message[key] for key in ('operation', 'arguments', 'contact', 'business_doctype', 'business_name')},
                         {'operation': 'messages.send', 'arguments': {'body': 'Your order is ready'}, 'contact': 'Contact Asha',
                          'business_doctype': 'Customer', 'business_name': 'Asha Stores'})
        self.assertEqual(result, {'action': 'ACT-1', 'status': 'Submitted', 'message': 'RELAY-MSG-0000000001',
                                  'number': NUMBER, 'contact': 'Contact Asha', 'key': message['key']})

    def test_a_repeat_keeps_its_key_and_a_given_key_is_used(self):
        with patch.object(messaging_api.time, 'time', return_value=6000.0):
            first = messaging_api.send_text(NUMBER, 'Your order is ready')['key']
        with patch.object(messaging_api.time, 'time', return_value=6599.0):
            self.assertEqual(messaging_api.send_text('+' + NUMBER, 'Your order is ready')['key'], first)
            self.assertNotEqual(messaging_api.send_text(NUMBER, 'Another text')['key'], first)
        self.assertEqual(messaging_api.send_text(NUMBER, 'Your order is ready', key='order-25')['key'], 'api-order-25')
        with patch.object(messaging_api.time, 'time', return_value=6600.0):  # The next 10-minute bucket sends again.
            self.assertNotEqual(messaging_api.send_text(NUMBER, 'Your order is ready')['key'], first)
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
    def setUp(self):
        self.cache = {}
        cache = Mock(get_value=lambda key, user=None: self.cache.get((user, key)),
                     set_value=lambda key, value, user=None, expires_in_sec=None: self.cache.__setitem__((user, key), value))
        self.enqueue, self.db, self.sent = Mock(), Mock(), Mock()
        self.message = {'key': 'api-k', 'operation': 'messages.send', 'arguments': {'body': 'Hi'}, 'contact': 'Contact Asha',
                        'business_doctype': 'Customer', 'business_name': 'Asha Stores'}
        patches = [patch.object(messaging_api, 'require_access'), patch.object(messaging_api.frappe, 'throw', throw),
                   patch.object(messaging_api.frappe, 'cache', cache), patch.object(messaging_api.frappe, 'db', self.db),
                   patch.object(messaging_api.frappe, 'enqueue', self.enqueue),
                   patch.object(messaging_api.frappe, 'session', _dict(user='api@example.com')),
                   patch.object(messaging_api.frappe, 'clear_messages'), patch.object(messaging_api.whatsapp, 'send', self.sent)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def checked(self, number, body, key=None, business_doctype=None, business_name=None):
        if body == 'refused':
            raise frappe.PermissionError('Not permitted')
        return dict(self.message, key='api-' + (key or body)), number

    def queue(self, items):
        with patch.dict(messaging_api.MESSAGES, text=self.checked):
            return messaging_api.send_messages(items)

    def test_items_are_checked_at_once_and_the_accepted_ones_queue_as_one_job(self):
        result = self.queue([{'type': 'text', 'number': NUMBER, 'body': 'Hi'}, {'type': 'text', 'number': NUMBER, 'body': 'refused'},
                             {'type': 'media', 'number': NUMBER, 'body': 'Hi'}, {'type': 'call'}, 'text',
                             {'type': 'text', 'number': NUMBER, 'body': 'Bye', 'key': 'k-2'}])
        self.assertEqual(result['results'][0], {'index': 0, 'ok': True, 'status': 'Pending', 'number': NUMBER,
                                                'contact': 'Contact Asha', 'key': 'api-Hi'})
        self.assertEqual([(row['ok'], row.get('error')) for row in result['results'][1:5]],
                         [(False, 'Not permitted'), (False, 'Give the fields a media send needs and no others'),
                          (False, 'type must be text, media or template'), (False, 'type must be text, media or template')])
        self.assertEqual(self.db.rollback.call_count, 4)
        self.sent.assert_not_called()  # Nothing is sent inside the request.
        job = self.enqueue.call_args
        self.assertEqual((job.args[0], job.kwargs['queue'], job.kwargs['job_id'], job.kwargs['deduplicate'], job.kwargs['batch']),
                         ('relay_core.messaging_api.deliver_batch', 'long', 'relay-send-' + result['batch'], True, result['batch']))
        self.assertEqual([message['key'] for message in job.kwargs['messages']], ['api-Hi', 'api-k-2'])

    def test_a_retried_request_gets_the_same_batch_and_job_and_a_new_request_another(self):
        items = [{'type': 'text', 'number': NUMBER, 'body': 'Hi'}]
        first, again = self.queue(items)['batch'], self.queue(items)['batch']
        self.assertEqual(first, again)
        self.assertEqual({call.kwargs['job_id'] for call in self.enqueue.call_args_list}, {'relay-send-' + first})
        self.assertNotEqual(self.queue([dict(items[0], body='Other')])['batch'], first)

    def test_nothing_is_queued_when_every_item_is_refused(self):
        result = self.queue([{'type': 'text', 'number': NUMBER, 'body': 'refused'}])
        self.assertIsNone(result['batch'])
        self.enqueue.assert_not_called()

    def test_the_job_sends_each_item_through_the_journal_and_status_reads_each_result(self):
        batch = self.queue([{'type': 'text', 'number': NUMBER, 'body': 'Hi'}, {'type': 'text', 'number': NUMBER, 'body': 'Bye'},
                            {'type': 'text', 'number': NUMBER, 'body': 'Later'}])['batch']
        messages = self.enqueue.call_args.kwargs['messages']
        self.sent.side_effect = [{'action': 'ACT-1'}, ValueError('Configure one available WhatsApp channel'), {'action': 'ACT-3'}]
        messaging_api.deliver_batch(batch, messages)
        self.assertEqual([call.args[0] for call in self.sent.call_args_list], messages)
        self.assertEqual((self.db.commit.call_count, self.db.rollback.call_count), (2, 1))
        actions = {'api-Hi': _dict(name='ACT-1', status='Submitted', outbound_message='RELAY-MSG-1')}
        self.db.get_value.side_effect = lambda doctype, filters, fields, as_dict: next(
            (row for key, row in actions.items() if filters['request_key'] ==
             messaging_api.hashlib.sha256(('api@example.com:' + key).encode()).hexdigest()), None)
        self.assertEqual(messaging_api.send_status(batch)['results'], [
            {'index': 0, 'key': 'api-Hi', 'status': 'Submitted', 'action': 'ACT-1', 'message': 'RELAY-MSG-1'},
            {'index': 1, 'key': 'api-Bye', 'status': 'Failed', 'error': 'Configure one available WhatsApp channel'},
            {'index': 2, 'key': 'api-Later', 'status': 'Pending'}])
        self.sent.side_effect = None
        messaging_api.deliver_batch(batch, messages)  # A rerun that succeeds clears the old error.
        self.assertEqual(messaging_api.send_status(batch)['results'][1]['status'], 'Pending')

    def test_status_is_only_for_the_batch_owner(self):
        batch = self.queue([{'type': 'text', 'number': NUMBER, 'body': 'Hi'}])['batch']
        with patch.object(messaging_api.frappe, 'session', _dict(user='other@example.com')), \
                self.assertRaises(frappe.DoesNotExistError):
            messaging_api.send_status(batch)
        for bad in ('missing', None):
            with self.subTest(batch=bad), self.assertRaises(frappe.DoesNotExistError):
                messaging_api.send_status(bad)

    def test_lists_are_capped_and_denied_without_access(self):
        for items in ([], [{'type': 'text'}] * 101, {'type': 'text'}):
            with self.subTest(size=len(items)), self.assertRaises(frappe.ValidationError):
                messaging_api.send_messages(items)
        with patch.object(messaging_api, 'require_access', side_effect=frappe.PermissionError):
            for call in (lambda: messaging_api.send_messages([{'type': 'text'}]), lambda: messaging_api.send_status('b')):
                with self.assertRaises(frappe.PermissionError):
                    call()
        self.enqueue.assert_not_called()


class RecipientTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        patches = [patch.object(messaging_api.frappe, 'db', self.db), patch.object(messaging_api.frappe, 'throw', throw),
                   patch('relay_core.identity.default_region', return_value='IN'),
                   patch.object(messaging_api, 'sibling_contact', return_value=None)]
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


class ChannelTests(unittest.TestCase):
    """An API send names its number, or leaves from the number the customer wrote to last."""
    def test_the_customer_number_is_found_across_channels_for_the_choice(self):
        fake = Mock()
        fake.get_all.return_value = ['Shop', 'Support']
        fake.db.get_value.return_value = 'RELAY-CON-1'
        with patch.object(messaging_api, 'frappe', fake), patch.object(messaging_api, 'connection_value', return_value='site-a'), \
                patch.object(messaging_api, 'choose', return_value='Support') as choose:
            self.assertEqual(messaging_api.sending_channel(NUMBER, None), 'Support')
            messaging_api.sending_channel(NUMBER, 'Shop')
        self.assertEqual(fake.db.get_value.call_args.args[1]['endpoint_key'][1],
                         [messaging_api.endpoint_key(name, NUMBER) for name in ('Shop', 'Support')])
        self.assertEqual(choose.call_args_list[0].kwargs, {'contact': 'RELAY-CON-1', 'requested': None})
        self.assertEqual(choose.call_args_list[1].kwargs['requested'], 'Shop')

    def test_the_chosen_number_goes_into_the_journal_and_the_template_lookup(self):
        sent = Mock(return_value={'action': 'A'})
        with patch.object(messaging_api, 'require_access'), patch.object(messaging_api, 'sending_channel', side_effect=lambda number, channel: channel or 'Shop') as pick, \
                patch.object(messaging_api.service_window, 'open_numbers', return_value={NUMBER}), \
                patch.object(messaging_api, 'recipient', return_value=('Contact Asha', ('Customer', 'Asha Stores'))), \
                patch.object(messaging_api.whatsapp, 'send', sent), patch('relay_core.identity.default_region', return_value='IN'), \
                patch('relay_core.whatsapp_templates.definition', return_value=POSITIONAL) as definition:
            messaging_api.send_text(NUMBER, 'Hi', channel='Support')
            self.assertEqual(sent.call_args.args[0]['channel'], 'Support')
            messaging_api.send_template(NUMBER, 'order', 'en', ['SO-25', 'Asha'], channel='Support')
            self.assertEqual(definition.call_args.args, ('order', 'en', 'Support'))
            result, message = messaging_api.checked_item(0, {'type': 'text', 'number': NUMBER, 'body': 'Hi', 'channel': 'Support'})
            self.assertEqual((result['ok'], message['channel']), (True, 'Support'))
        self.assertEqual(pick.call_args_list[0].args, (NUMBER, 'Support'))

    def test_a_number_known_on_another_channel_is_enrolled_not_duplicated(self):
        db = Mock()
        found = iter([None, _dict(relay_contact='RELAY-CON-1', verified=1)])
        db.get_value.side_effect = lambda doctype, *args, **kwargs: next(found) if doctype == 'Relay Contact Endpoint' else (
            'Contact Asha' if doctype == 'Relay Contact' else _dict(mobile_no='+' + NUMBER))
        with patch.object(messaging_api.frappe, 'db', db), patch.object(messaging_api, 'sibling_contact', return_value='RELAY-CON-1') as sibling, \
                patch.object(messaging_api, 'new_contact') as new_contact, patch('relay_core.identity.default_region', return_value='IN'):
            self.assertEqual(messaging_api.recipient('Support', NUMBER, 'Customer', 'Asha Stores'), ('Contact Asha', ('Customer', 'Asha Stores')))
        sibling.assert_called_once_with('Support', NUMBER)
        new_contact.assert_not_called()


if __name__ == '__main__':
    unittest.main()
