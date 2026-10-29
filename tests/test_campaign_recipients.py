"""Campaign recipients from contact filters, opted-out skips, scheduled starts and Manager-only access, with mocks only."""
import hashlib
import json
import unittest
from contextlib import nullcontext
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
from frappe import _dict
from relay_core import bulk_campaigns, campaign_audience, campaign_schedule

NOW = datetime(2026, 10, 27, 10, 0, 0)
FIELDS = [{'key': 'body:name', 'label': 'Body value name', 'component': 'body', 'name': 'name'},
          {'key': 'body:city', 'label': 'Body value city', 'component': 'body', 'name': 'city'}]


def throw(message, exc=frappe.ValidationError):
    raise exc(message)


def campaign(**values):
    return _dict({'name': 'Winter launch', 'channel': 'WA', 'status': 'Draft', 'template_name': 'notice', 'language': 'en',
                  'arguments': json.dumps({'template': {}, 'fields': FIELDS}), 'reply_window_hours': 72, **values})


class FilterTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('relay_core.business_access.require_type'))
        self.enterContext(patch('frappe.throw', side_effect=throw))
        self.enterContext(patch.object(campaign_audience, 'linked_types', return_value=['Customer']))
        self.enterContext(patch.object(campaign_audience, 'segment_fields',
                                       return_value=[SimpleNamespace(fieldname='territory')]))
        self.permission = self.enterContext(patch.object(campaign_audience, 'contact_query', return_value=''))

    def test_every_filter_becomes_one_parameterised_condition(self):
        audience = campaign_audience.checked({'tag': 'vip_1', 'doctype': 'Customer', 'segments': {'territory': 'South'},
                                              'number': '9198', 'last_message_from': '2026-10-01',
                                              'last_message_to': '2026-10-20', 'include': ['C1', 'C1'], 'exclude': ['C2']})
        sql, values = campaign_audience.where('WA', audience)
        self.assertEqual(audience['include'], ['C1'])
        self.assertEqual(values, {'channel': 'WA', 'tag': '%,vip\\_1,%', 'doctype': 'Customer', 'segment_0': 'South',
                                  'number': '%9198%', 'last_from': '2026-10-01', 'last_to': '2026-10-21',
                                  'include': ('C1',), 'exclude': ('C2',)})
        self.assertIn('e.channel=%(channel)s AND e.verified=1', sql)
        self.assertIn('b.`territory`=%(segment_0)s', sql)
        self.assertIn(') OR `tabRelay Contact`.name IN %(include)s)', sql)
        self.assertTrue(sql.endswith('AND `tabRelay Contact`.name NOT IN %(exclude)s'))

    def test_no_filter_matches_every_verified_number_the_user_may_read(self):
        self.permission.return_value = '`tabRelay Contact`.contact IN (SELECT name FROM `tabContact`)'
        sql, values = campaign_audience.where('WA', campaign_audience.checked({}))
        self.assertEqual(values, {'channel': 'WA'})
        self.assertEqual(sql, 'e.channel=%(channel)s AND e.verified=1 AND (`tabRelay Contact`.contact IN '
                              '(SELECT name FROM `tabContact`)) AND (1=1)')

    def test_contacts_added_by_hand_without_a_filter_pick_only_those_contacts(self):
        sql, values = campaign_audience.where('WA', campaign_audience.checked({'include': ['C1'], 'exclude': ['C2']}))
        self.assertEqual(values, {'channel': 'WA', 'include': ('C1',), 'exclude': ('C2',)})
        self.assertIn('AND (`tabRelay Contact`.name IN %(include)s) AND', sql)
        self.assertNotIn('1=1', sql)

    def test_filters_outside_the_offered_choices_are_refused(self):
        for audience in ({'doctype': 'Item'}, {'segments': {'territory': 'South'}},
                         {'doctype': 'Customer', 'segments': {'credit_limit': '1'}}, {'number': '+91 98'},
                         {'owner': 'x'}, {'include': ['C'] * 501}, 'not filters'):
            with self.subTest(audience=audience), self.assertRaises(frappe.ValidationError):
                campaign_audience.checked(audience)

    def test_contact_rows_carry_contact_and_linked_record_values(self):
        doc = campaign(recipient_filters='{}', column_map=json.dumps(
            {'phone': 'phone', 'fields': {'body:name': 'contact.first_name', 'body:city': 'Customer.city'}, 'fixed': {}}))
        pages = [[_dict(endpoint='CE-1', number='919876543210', contact='Asha', display_name='Asha K'),
                  _dict(endpoint='CE-2', number='919876543211', contact='Ravi', display_name='Ravi')], []]
        fake = Mock(db=Mock(sql=Mock(side_effect=lambda *args, **kwargs: pages.pop(0))))
        fake.get_all.side_effect = lambda doctype, **kwargs: {
            'Contact': [_dict(name='Asha', first_name='Asha'), _dict(name='Ravi', first_name='Ravi')],
            'Dynamic Link': [_dict(parent='Asha', link_name='CUST-1')], 'Customer': [_dict(name='CUST-1', city='Chennai')]}[doctype]
        fake.get_list.return_value = [_dict(name='CUST-1', city='Chennai')]
        with patch.object(campaign_audience, 'frappe', fake):
            rows = list(campaign_audience.contact_rows(doc))
        self.assertEqual(rows, [
            (1, {'phone': '919876543210', 'contact.first_name': 'Asha', 'Customer.city': 'Chennai'}),
            (2, {'phone': '919876543211', 'contact.first_name': 'Ravi', 'Customer.city': ''})])
        self.assertEqual(fake.get_all.call_args.kwargs['fields'], ['name', 'city'])  # Relay type access was checked first.

    def test_import_saves_filters_and_mapping_and_starts_the_import(self):
        doc = campaign(source_file='/private/files/old.csv')
        sources = [{'value': 'contact.first_name'}, {'value': 'Customer.city'}]
        with patch.object(campaign_audience.bulk_campaigns, 'bulk', return_value=doc), \
                patch.object(campaign_audience, 'sources', return_value=sources), \
                patch.object(campaign_audience.bulk_campaigns, 'start_import') as start_import, \
                patch.object(campaign_audience.bulk_campaigns, 'read', return_value={'name': doc.name}):
            campaign_audience.import_contacts(doc.name, {'number': '9198'}, {
                'fields': {'body:name': 'contact.first_name'}, 'fixed': {'body:city': 'Chennai'}})
            with self.assertRaisesRegex(frappe.ValidationError, 'not in the file'):
                campaign_audience.import_contacts(doc.name, {}, {'fields': {'body:name': 'contact.salary'}, 'fixed': {}})
        start_import.assert_called_once_with(doc)
        self.assertEqual(json.loads(doc.recipient_filters), {'number': '9198'})
        self.assertEqual(json.loads(doc.column_map)['phone'], 'phone')
        self.assertIsNone(doc.source_file)

    def test_a_sheet_upload_replaces_contact_filters(self):
        doc = campaign(recipient_filters='{"tag": "vip"}', source_file=None)
        with patch.object(bulk_campaigns, 'bulk', return_value=doc), patch.object(bulk_campaigns, 'source_path'), \
                patch.object(bulk_campaigns.bulk_sheet, 'columns', return_value=(['Mobile'], [])), \
                patch.object(bulk_campaigns, 'internal_save'):
            bulk_campaigns.inspect(doc.name, '/private/files/people.csv')
        self.assertIsNone(doc.recipient_filters)
        self.assertEqual(doc.source_file, '/private/files/people.csv')

    def test_import_reads_contact_rows_for_a_contact_campaign(self):
        with patch.object(campaign_audience, 'contact_rows', return_value=iter([])) as rows:
            self.assertIs(bulk_campaigns.recipient_rows(campaign(recipient_filters='{}')), rows.return_value)


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('frappe.throw', side_effect=throw))
        self.enterContext(patch('frappe.utils.now_datetime', return_value=NOW))

    def test_start_time_is_in_the_future_and_at_most_ninety_days_ahead(self):
        self.assertEqual(campaign_schedule.start_time('2026-10-28 09:30:15.5'), datetime(2026, 10, 28, 9, 30, 15))
        for value in (None, '', 'tomorrow', '2026-10-27 10:00:30', '2027-02-01 09:00:00'):
            with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
                campaign_schedule.start_time(value)

    def test_a_due_campaign_starts_once_when_two_workers_run(self):
        state = {'Winter launch': 'Scheduled'}
        db = Mock()
        db.get_value.side_effect = lambda doctype, name, field, for_update=False: state[name]
        db.set_value.side_effect = lambda doctype, name, values: state.update({name: values['status']})
        fake = SimpleNamespace(db=db, utils=SimpleNamespace(now_datetime=lambda: NOW),
                               get_all=Mock(return_value=['Winter launch']), QueryDeadlockError=frappe.QueryDeadlockError)
        with patch.object(campaign_schedule, 'frappe', fake), patch.object(campaign_schedule, 'start') as start:
            campaign_schedule.start_due()
            campaign_schedule.start_due()
        start.assert_called_once_with('Winter launch')
        self.assertEqual(state['Winter launch'], 'Running')
        self.assertEqual(fake.get_all.call_args.kwargs['filters'], {'status': 'Scheduled', 'scheduled_at': ['<=', NOW]})
        self.assertEqual(db.commit.call_count, 1)

    def test_a_worker_that_loses_the_race_on_a_snapshot_conflict_does_not_start(self):
        db = Mock()
        db.get_value.side_effect = frappe.QueryDeadlockError('Record has changed since last read')
        with patch.object(campaign_schedule, 'frappe', SimpleNamespace(db=db, QueryDeadlockError=frappe.QueryDeadlockError)):
            self.assertFalse(campaign_schedule.claim('Winter launch'))
        db.set_value.assert_not_called()

    def test_a_failed_start_check_pauses_the_campaign_with_the_reason(self):
        doc = campaign(status='Running', execution_user='manager@example.com', started_at=None)
        fake = Mock(session=_dict(user='Administrator'), ValidationError=frappe.ValidationError,
                    PermissionError=frappe.PermissionError)
        fake.get_doc.return_value = doc
        fake.db.get_value.return_value = 1
        with patch.object(campaign_schedule, 'frappe', fake), patch('relay_core.bulk_updates.changed'), \
                patch.object(bulk_campaigns, 'check_ready', side_effect=frappe.ValidationError('Choose an approved template')), \
                patch.object(bulk_campaigns, 'enqueue') as enqueue:
            campaign_schedule.start('Winter launch')
        enqueue.assert_not_called()
        fake.db.set_value.assert_called_once_with('Relay Campaign', 'Winter launch', {
            'status': 'Paused', 'last_error': 'The scheduled start failed: Choose an approved template'})
        self.assertEqual(fake.set_user.call_args_list[-1].args, ('Administrator',))

    def test_a_started_campaign_queues_its_first_slice(self):
        doc = campaign(status='Running', execution_user='manager@example.com', started_at=None)
        fake = Mock(session=_dict(user='Administrator'), utils=SimpleNamespace(now_datetime=lambda: NOW))
        fake.get_doc.return_value = doc
        fake.db.get_value.return_value = 1
        with patch.object(campaign_schedule, 'frappe', fake), patch('relay_core.bulk_updates.changed'), \
                patch('relay_core.bulk_updates.open_reply_window'), patch.object(campaign_schedule, 'internal_save'), \
                patch.object(bulk_campaigns, 'check_ready', return_value={'media_id': 'M1'}), \
                patch.object(bulk_campaigns, 'enqueue') as enqueue:
            campaign_schedule.start('Winter launch')
        enqueue.assert_called_once_with('send_job', 'Winter launch', slot='control')
        self.assertEqual((doc.media_id, doc.started_at), ('M1', NOW))

    def test_schedule_checks_now_and_unschedule_returns_to_draft(self):
        doc = campaign(scheduled_at=None)
        cache = SimpleNamespace(lock=lambda *args, **kwargs: nullcontext(), delete_value=Mock())
        with patch.object(bulk_campaigns, 'require_access'), patch.object(bulk_campaigns, 'bulk', return_value=doc), \
                patch.object(bulk_campaigns, 'check_ready', return_value={}) as check_ready, \
                patch.object(bulk_campaigns, 'internal_save'), patch.object(bulk_campaigns, 'read'), \
                patch.object(bulk_campaigns, 'enqueue') as enqueue, patch('frappe.cache', cache), \
                patch('frappe.session', _dict(user='manager@example.com')):
            bulk_campaigns.control(doc.name, 'schedule', '2026-10-28 09:00:00')
            self.assertEqual((doc.status, doc.scheduled_at, doc.execution_user),
                             ('Scheduled', datetime(2026, 10, 28, 9, 0), 'manager@example.com'))
            check_ready.assert_called_once()
            enqueue.assert_not_called()
            bulk_campaigns.control(doc.name, 'unschedule')
        self.assertEqual((doc.status, doc.scheduled_at), ('Draft', None))


class ManagerOnlyTests(unittest.TestCase):
    def test_a_user_without_campaign_write_is_refused(self):
        calls = {
            'options': lambda: campaign_audience.options('Winter launch'),
            'preview': lambda: campaign_audience.preview('Winter launch', {}),
            'search': lambda: campaign_audience.search('Winter launch', 'Asha'),
            'import': lambda: campaign_audience.import_contacts('Winter launch', {}, {'fields': {}, 'fixed': {}}),
            'schedule': lambda: bulk_campaigns.control('Winter launch', 'schedule', '2026-10-28 09:00:00'),
        }
        with patch('frappe.throw', side_effect=throw), patch('frappe.has_permission', return_value=False) as allowed, \
                patch('frappe.get_doc') as get_doc:
            for name, call in calls.items():
                with self.subTest(call=name), self.assertRaises(frappe.PermissionError):
                    call()
        get_doc.assert_not_called()
        self.assertEqual(allowed.call_args.args, ('Relay Campaign', 'write'))


class CampaignSkipTests(unittest.TestCase):
    def test_endpoint_facts_count_a_keyword_opt_out_and_a_denied_preference(self):
        def get_all(doctype, **kwargs):
            if doctype == 'Relay Contact Endpoint':
                return [_dict(name='CE-1', endpoint_key=key('911'), relay_contact='R1', verified=1, marketing_opt_out=1),
                        _dict(name='CE-2', endpoint_key=key('912'), relay_contact='R2', verified=1, marketing_opt_out=0),
                        _dict(name='CE-3', endpoint_key=key('913'), relay_contact='R3', verified=1, marketing_opt_out=0)]
            return {'Relay Contact': [['R1', 'Asha'], ['R2', 'Ravi'], ['R3', 'Mani']],
                    'Relay Channel Preference': ['CE-3']}[doctype]
        key = lambda number: hashlib.sha256(('WA:' + number).encode()).hexdigest()  # noqa: E731
        with patch.object(bulk_campaigns, 'frappe', SimpleNamespace(get_all=get_all)):
            contacts, opted_out = bulk_campaigns.endpoint_facts('WA', ['911', '912', '913'])
        self.assertEqual(opted_out, {'911', '913'})
        self.assertEqual(contacts['912'], 'Ravi')

    def test_import_skips_opted_out_numbers_with_the_reason(self):
        db = Mock()
        doc = _dict(name='Winter launch', channel='WA')
        with patch.object(bulk_campaigns, 'frappe', SimpleNamespace(db=db, utils=SimpleNamespace(now=lambda: 'now'),
                                                                    session=_dict(user='manager@example.com'))), \
                patch.object(bulk_campaigns, 'endpoint_facts', return_value=({}, {'911'})):
            bulk_campaigns.insert_chunk(doc, [(1, '911', {'values': {}}, None), (2, '912', {'values': {}}, None)])
        rows = db.bulk_insert.call_args.args[2]
        self.assertEqual([(row[10], row[14]) for row in rows], [('Skipped', 'Opted out'), ('Pending', '')])

    def test_a_number_that_opts_out_after_the_import_is_skipped_at_send_time(self):
        db = Mock()
        rows = [_dict(name='REC-1', destination='911'), _dict(name='REC-2', destination='912')]
        with patch.object(bulk_campaigns, 'frappe', SimpleNamespace(db=db)), patch('relay_core.bulk_updates.changed') as changed, \
                patch.object(bulk_campaigns, 'endpoint_facts', return_value=({}, {'911'})):
            kept = bulk_campaigns.without_opted_out(_dict(name='Winter launch', channel='WA'), rows)
        self.assertEqual(kept, [rows[1]])
        self.assertEqual(db.sql.call_args.args[1], ('Opted out', ('REC-1',)))
        self.assertIn("status='Skipped'", db.sql.call_args.args[0])
        changed.assert_called_once_with('Winter launch')

    def test_skipped_rows_never_reach_hub(self):
        db = Mock()
        db.get_value.return_value = 'Running'
        db.sql.side_effect = [[_dict(name='REC-1', request_key='k1', destination='911', arguments=json.dumps({'values': {}}))],
                              None, None, []]
        hub = Mock()
        doc = _dict(name='Winter launch', channel='WA', template_name='notice', language='en', last_error='',
                    arguments=json.dumps({'template': {}, 'fields': []}))
        fake = SimpleNamespace(db=db, cache=Mock(get_value=Mock(return_value=None)), utils=SimpleNamespace(flt=lambda value: float(value or 0)))
        with patch.object(bulk_campaigns, 'frappe', fake), \
                patch.object(bulk_campaigns.whatsapp, 'client', return_value=hub), patch('relay_core.bulk_updates.changed'), \
                patch.object(bulk_campaigns, 'endpoint_facts', return_value=({}, {'911'})):
            self.assertFalse(bulk_campaigns.push(doc, float('inf')))
        hub.call_tool.assert_not_called()
