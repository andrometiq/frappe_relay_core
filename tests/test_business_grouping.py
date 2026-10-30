"""Read-time grouping: real SQL aggregates over representative in-memory records.

Frappe permission SQL is supplied at the service boundary; live MariaDB/query-hook
integration is separately required after migrating the development site.
"""
import json
import re
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from frappe import _dict
from relay_core import business_groups as groups
from relay_core.patches.v1_0 import add_business_group_fields as migration
from relay_core.relay_core.doctype.relay_contact_type import relay_contact_type as controller


class GroupConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.meta = Mock(issingle=0, istable=0, module='Selling')
        self.meta.get_field.side_effect = lambda name: _dict(fieldname=name, fieldtype='Data', permlevel=0, hidden=0) if name in ('region', 'team', 'zone') else None
        self.fake = Mock()
        self.fake.session.user = 'Administrator'
        self.fake.get_meta.return_value = self.meta
        self.fake.throw.side_effect = ValueError
        self.enterContext(patch.object(groups, 'frappe', self.fake))
        self.enterContext(patch('relay_core.business_access.require_type'))
        self.enterContext(patch('relay_core.business_access.allowed_types', return_value={'Local Business', 'Other'}))
        self.enterContext(patch('relay_core.business_access.people_query', side_effect=lambda **kwargs: self.fake.qb.get_query('Contact', ignore_permissions=True, **kwargs)))
        self.enterContext(patch.object(controller, 'frappe', self.fake))
        self.enterContext(patch.object(controller, 'require_access'))

    def validate(self, rows):
        doc = _dict(business_doctype='Local Business', grouping_fields=[_dict(row) for row in rows])
        controller.RelayContactType.validate(doc)
        return doc

    def test_order_is_priority_then_row_order_and_not_fieldname(self):
        config = self.validate([{'fieldname': 'team', 'priority': 2, 'idx': 1},
                                {'fieldname': 'zone', 'priority': 1, 'idx': 2},
                                {'fieldname': 'region', 'priority': 1, 'idx': 3}])
        self.assertEqual(groups.configuration('Local Business', config), ['zone', 'region', 'team'])

    def test_rejects_missing_hidden_privileged_unsupported_and_duplicate_fields(self):
        for properties in ({'hidden': 1}, {'permlevel': 1}, {'fieldtype': 'Table'}, {'fieldtype': 'Text'}):
            self.meta.get_field.side_effect = None
            self.meta.get_field.return_value = _dict(fieldtype='Data', permlevel=0, hidden=0)
            self.meta.get_field.return_value.update(properties)
            with self.subTest(properties=properties), self.assertRaises(ValueError):
                self.validate([{'fieldname': 'region', 'priority': 1}])
        self.meta.get_field.return_value = None
        with self.assertRaises(ValueError):
            self.validate([{'fieldname': 'link.region', 'priority': 1}])
        self.meta.get_field.return_value = _dict(fieldtype='Link', hidden=0, permlevel=0)
        with self.assertRaises(ValueError):
            self.validate([{'fieldname': 'region', 'priority': 1}] * 2)
        with self.assertRaises(ValueError):
            self.validate([{'fieldname': 'region', 'priority': 1}] * 7)

    def test_priority_is_required_and_positive_integer(self):
        for value in (None, '', 0, -1, 1.5, True, 'first'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.validate([{'fieldname': 'region', 'priority': value}])
        self.validate([{'fieldname': 'region', 'priority': '1'}])

    def test_legacy_fallback_and_clearing_table(self):
        config = _dict(grouping_field='region', grouping_fields=[])
        self.assertEqual(groups.configuration('Local Business', config), ['region'])
        config.business_doctype = 'Local Business'
        controller.RelayContactType.validate(config)
        self.assertEqual(groups.configuration('Local Business', config), [])

    def test_patch_copies_only_empty_tables_and_is_repeatable(self):
        config = _dict(business_doctype='Local Business', grouping_field='region', grouping_fields=[])
        inserted = Mock()
        def append(field, values):
            row = _dict(values, idx=len(config[field]) + 1, db_insert=inserted)
            config[field].append(row)
            return SimpleNamespace(db_insert=inserted)
        doc = Mock()
        doc.business_doctype = config.business_doctype
        doc.get.side_effect = config.get
        doc.append.side_effect = append
        self.fake.get_all.return_value = ['Local Business']
        self.fake.get_doc.return_value = doc
        with patch.object(migration, 'frappe', self.fake):
            migration.execute()
            migration.execute()
        self.assertEqual(len(config.grouping_fields), 1)
        self.assertEqual(config.grouping_fields[0].priority, 1)
        inserted.assert_called_once()
        config.grouping_fields = [_dict(fieldname='team', priority=3, idx=1)]
        with patch.object(migration, 'frappe', self.fake):
            migration.execute()
        self.assertEqual(config.grouping_fields[0].fieldname, 'team')
        self.assertEqual(self.fake.db.add_index.call_args.args[:2], ('Local Business', ['team']))
        self.assertLess(len(self.fake.db.add_index.call_args.args[2]), 64)


class GroupAggregateTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE `tabLocal Business` (name TEXT PRIMARY KEY, title TEXT, region TEXT, team TEXT, allowed INTEGER);
            CREATE INDEX local_region ON `tabLocal Business` (region);
            CREATE TABLE `tabRelay Chat` (business_doctype TEXT, business_name TEXT, unread_count INTEGER, last_message_at TEXT, allowed INTEGER,
                UNIQUE(business_doctype, business_name));
        ''')
        self.db.executemany('INSERT INTO `tabLocal Business` VALUES (?, ?, ?, ?, ?)', [
            ('a', 'Alpha', None, 'One', 1), ('b', 'Beta', '', 'Two', 1),
            ('c', 'Gamma', 'North', 'One', 1), ('d', 'Hidden', 'Secret', 'One', 0),
            ('e', 'Empty', 'North', 'Two', 1), ('f', 'Assigned elsewhere', 'North', 'One', 1)])
        self.db.executemany('INSERT INTO `tabRelay Chat` VALUES (?, ?, ?, ?, ?)', [
            ('Local Business', 'a', 3, '2026-10-01', 1), ('Local Business', 'b', 5, '2026-10-02', 1),
            ('Local Business', 'c', 7, '2026-10-03', 1), ('Local Business', 'd', 99, '2026-10-04', 1),
            ('Local Business', 'f', 0, '2026-10-05', 0)])
        self.db.executescript('''
            CREATE TABLE `tabContact` (name TEXT PRIMARY KEY, full_name TEXT, mobile_no TEXT, phone TEXT, email_id TEXT, allowed INTEGER);
            CREATE TABLE `tabDynamic Link` (parent TEXT, parenttype TEXT, parentfield TEXT, link_doctype TEXT, link_name TEXT);
            CREATE TABLE `tabRelay Contact` (name TEXT PRIMARY KEY, contact TEXT, display_name TEXT, allowed INTEGER,
                primary_doctype TEXT, primary_name TEXT);
            CREATE TABLE `tabRelay Contact Type` (business_doctype TEXT PRIMARY KEY, enabled INTEGER);
            INSERT INTO `tabRelay Contact Type` VALUES ('Local Business', 1), ('Other', 1), ('Disabled Type', 0);
            CREATE TABLE `tabRelay Channel` (name TEXT PRIMARY KEY, allowed INTEGER);
            CREATE TABLE `tabRelay Message` (name TEXT PRIMARY KEY, business_doctype TEXT, business_name TEXT, relay_contact TEXT,
                channel TEXT, content TEXT, direction TEXT, sent_at TEXT, creation TEXT, legacy_triage INTEGER, allowed INTEGER, unread INTEGER,
                relay_timeline_time TEXT GENERATED ALWAYS AS (COALESCE(sent_at, creation)) VIRTUAL);
            INSERT INTO `tabContact` VALUES ('alice', 'Alice', '555001', '', '', 1), ('hidden', 'Hidden person', '555999', '', '', 0);
            INSERT INTO `tabRelay Contact` VALUES ('r1', 'alice', 'Alice', 1, NULL, NULL), ('r2', 'hidden', 'Hidden person', 0, NULL, NULL);
            INSERT INTO `tabRelay Channel` VALUES ('ch1', 1), ('ch2', 1), ('hidden', 0);
            INSERT INTO `tabDynamic Link` VALUES ('alice', 'Contact', 'links', 'Local Business', 'a'),
                ('alice', 'Contact', 'links', 'Local Business', 'b'), ('hidden', 'Contact', 'links', 'Local Business', 'a');
            INSERT INTO `tabRelay Message` VALUES
                ('m1', 'Local Business', 'a', 'r1', 'ch1', 'Visible preview', 'Incoming', '2026-10-01', '2026-10-01', 0, 1, 1),
                ('m2', 'Local Business', 'a', 'r2', 'ch1', 'Hidden preview', 'Incoming', '2026-10-09', '2026-10-09', 0, 0, 1),
                ('m3', 'Local Business', 'b', 'r1', 'ch2', 'Second preview', 'Incoming', '2026-10-02', '2026-10-02', 0, 1, 1);
        ''')
        self.db.execute('ALTER TABLE `tabRelay Chat` ADD COLUMN last_channel TEXT')
        self.db.execute("UPDATE `tabRelay Chat` SET last_channel=CASE WHEN business_name='a' THEN 'ch1' ELSE 'ch2' END")
        self.fake = Mock()
        self.fake.throw.side_effect = ValueError
        self.fake.parse_json.side_effect = json.loads
        self.fake.session.user = 'local-only@example.invalid'
        self.fake.qb.get_query.side_effect = lambda doctype, **kwargs: self.query(f'SELECT name FROM `tab{doctype}` WHERE allowed=1')
        self.fake.get_meta.return_value = SimpleNamespace(title_field='title', get_field=lambda field: _dict(hidden=0, permlevel=0, label=field.title()))
        self.fake.db.escape.side_effect = lambda value: "'" + value.replace("'", "''") + "'"
        self.fake.has_permission.return_value = True
        self.fake.db.sql.side_effect = self.sql
        self.enterContext(patch.object(groups, 'frappe', self.fake))
        self.enterContext(patch('relay_core.business_access.require_type'))
        self.enterContext(patch('relay_core.business_access.allowed_types', return_value={'Local Business', 'Other'}))
        self.enterContext(patch('relay_core.business_access.people_query', side_effect=lambda **kwargs: self.fake.qb.get_query('Contact', ignore_permissions=True, **kwargs)))
        self.enterContext(patch.object(groups, 'check_type'))
        self.enterContext(patch.object(groups, 'require_access'))
        self.chat_query = self.enterContext(patch('relay_core.relay_chats.query', return_value=''))
        self.enterContext(patch('relay_core.inbox._unread_query', return_value=self.query('SELECT name FROM `tabRelay Message` WHERE allowed=1 AND unread=1')))
        self.enterContext(patch('relay_core.summaries.ai_features.is_enabled', return_value=False))
        self.enterContext(patch('relay_core.inbox_filters.channel_names', side_effect=lambda medium, channel, channels: channels))
        self.enterContext(patch('relay_core.inbox_filters.business_filter'))
        self.enterContext(patch('relay_core.timeline.has_timeline_column', return_value=True))
        self.enterContext(patch('relay_core.timeline.index_hint', return_value=''))

    def query(self, sql, values=None):
        return SimpleNamespace(walk=lambda: (sql, values or {}))

    def sql(self, query, values, as_dict=True):
        values = dict(values)
        for key, value in list(values.items()):
            if isinstance(value, tuple):
                query = query.replace('%(' + key + ')s', '(' + ', '.join(f'%({key}_{i})s' for i in range(len(value))) + ')')
                values.update({f'{key}_{i}': item for i, item in enumerate(value)})
                del values[key]
        query = re.sub(r'%\((\w+)\)s', r':\1', query).replace('%%', '%')
        return [_dict(dict(row)) for row in self.db.execute(query, values).fetchall()]

    def test_blank_bucket_and_permission_filter_before_aggregation(self):
        rows = groups.aggregate('Local Business', ['region', 'team'], [])
        self.assertEqual([(r.value, r.label, r.record_count, r.unread) for r in rows],
                         [('', 'Not set', 2, 8), ('North', 'North', 3, 7)])
        self.fake.qb.get_query.assert_called_with('Local Business', fields=['name'], ignore_permissions=True, order_by='')
        totals = groups.aggregate('Local Business', [], [], totals=True)[0]
        self.assertEqual((totals.record_count, totals.unread), (5, 15))
        self.db.execute("UPDATE `tabLocal Business` SET allowed=0 WHERE name='c'")
        self.assertEqual(groups.aggregate('Local Business', [], [], totals=True)[0].unread, 8)

    def test_nested_path_and_last_level_record_activity(self):
        levels = ['region', 'team']
        rows = groups.aggregate('Local Business', levels, [''])
        self.assertEqual([(r.value, r.unread) for r in rows], [('One', 3), ('Two', 5)])
        records = groups.aggregate('Local Business', levels, ['', 'Two'])
        self.assertEqual([(r.name, r.label, r.unread, r.last_activity) for r in records], [('b', 'Beta', 5, '2026-10-02')])
        self.assertEqual(groups.aggregate('Local Business', levels, ['North'], 'Gamma')[0].unread, 7)
        self.assertEqual(groups.aggregate('Local Business', levels, [], 'Hidden'), [])

    def test_no_groups_and_record_pagination(self):
        for index in range(70):
            self.db.execute('INSERT INTO `tabLocal Business` VALUES (?, ?, ?, ?, ?)',
                            (f'z{index:03}', f'Local record {index}', '', '', 1))
        with patch.object(groups, 'configuration', return_value=[]):
            first = groups.browse('Local Business')
            second = groups.browse('Local Business', start=first['next'])
            third = groups.browse('Local Business', start=second['next'])
        self.assertEqual(first['kind'], 'record')
        names = [r['name'] for page in (first, second, third) for r in page['items']]
        self.assertEqual((len(names), len(set(names)), third['next']), (75, 75, None))

    def test_ticket_values_are_batched_and_hidden_records_are_not_enriched(self):
        tickets = [_dict(business_doctype='Local Business', business_name=name) for name in ('a', 'b', 'd', 'a')]
        with patch.object(groups, 'configuration', return_value=['region', 'team']):
            columns = groups.ticket_values(tickets, 'Local Business')
        self.fake.db.sql.assert_called_once()
        self.assertEqual([field['fieldname'] for field in columns], ['region', 'team'])
        self.assertEqual(tickets[0].business_title, 'Alpha')
        self.assertEqual(tickets[0].group_values, {'region': '', 'team': 'One'})
        self.assertEqual(tickets[2].business_title, '')
        self.assertEqual(tickets[2].group_values, {})
        self.assertEqual(tickets[3].group_values, tickets[0].group_values)
        self.fake.db.sql.reset_mock()
        self.assertEqual(groups.ticket_values(tickets), [])
        self.fake.db.sql.assert_called_once()
        self.assertEqual(tickets[0].group_values, {})

    def test_root_types_and_legacy_adapters_share_counts(self):
        with patch('relay_core.business_types.list_types', return_value=[_dict(business_doctype='Local Business', label='Local', enabled=1)]), \
                patch.object(groups, 'configuration', return_value=['region', 'team']):
            root = groups.browse()
            self.assertEqual((root['items'][0]['record_count'], root['items'][0]['unread']), (5, 15))
            directory = groups.directory('Local Business')
            tiles = groups.browse('Local Business')
            self.assertEqual({row['value']: row['unread'] for row in directory['items']}, {row['value']: row['unread'] for row in tiles['items']})
            records = groups.records('Local Business', group='')
            self.assertEqual([row['name'] for row in records['items']], ['a', 'b'])
            self.assertEqual(sum(row['unread'] for row in records['items']), 8)

    def test_restricted_activity_excludes_hidden_contacts_and_reads_only_the_record_page(self):
        self.chat_query.return_value = "`tabRelay Chat`.business_name LIKE '100% Cotton'"
        self.db.execute("UPDATE `tabRelay Chat` SET unread_count=99, last_message_at='2026-10-09' WHERE business_name='a'")
        row = groups.aggregate('Local Business', [], [], business_name='a')[0]
        self.assertEqual((row.unread, row.last_activity, row.unread_records), (1, '2026-10-01', 1))
        page, counts = [call.args for call in self.fake.db.sql.call_args_list]
        self.assertNotIn('tabRelay Message', page[0])
        self.assertEqual(counts[1]['page'], ('a',))
        self.assertIn('IN %(page)s', counts[0])
        self.db.execute("UPDATE `tabRelay Message` SET allowed=0 WHERE name='m1'")
        row = groups.aggregate('Local Business', [], [], business_name='a')[0]
        self.assertEqual((row.unread, row.last_activity, row.unread_records), (0, None, 0))

    def test_unrestricted_counters_and_unread_record_counts(self):
        self.fake.db.sql.reset_mock()
        row = groups.aggregate('Local Business', [], [], totals=True)[0]
        self.assertEqual((row.unread, row.unread_records), (15, 3))
        self.assertNotIn('tabRelay Message', self.fake.db.sql.call_args.args[0])

    def test_browse_search_filters_the_shown_level(self):
        types = [_dict(business_doctype='Local Business', label='Local', enabled=1), _dict(business_doctype='Other', label='Other', enabled=1)]
        with patch.object(groups, 'configuration', return_value=['region', 'team']), \
                patch('relay_core.business_types.list_types', return_value=types):
            self.assertEqual([row.value for row in groups.directory('Local Business', query='North')['items']], ['North'])
            root = groups.browse(query='loc')['items']
            self.assertEqual([(row['doctype'], row['record_count']) for row in root], [('Local Business', 5)])
            self.assertEqual([row['value'] for row in groups.browse('Local Business', query='nor')['items']], ['North'])
            self.assertEqual(groups.browse('Local Business', query='Gamma')['items'], [])
            records = groups.browse('Local Business', path='["North", "One"]', path_fields='["region", "team"]', query='gam')
            self.assertEqual([row['name'] for row in records['items']], ['c'])
            self.assertEqual(groups.browse('Local Business', path='["North", "One"]', query='North')['items'], [])

    def test_group_tiles_name_their_field_and_stale_paths_restart_at_the_type(self):
        with patch.object(groups, 'configuration', return_value=['team']):
            page = groups.browse('Local Business')
            self.assertEqual({row['field'] for row in page['items']}, {'team'})
            self.assertEqual((page['path'], page['path_fields']), ([], []))
            for path, fields in (('["North", "One"]', '["region", "team"]'), ('["One"]', '["region"]'), ('["One"]', '[]')):
                with self.subTest(path=path, fields=fields):
                    stale = groups.browse('Local Business', path=path, path_fields=fields)
                    self.assertEqual((stale['kind'], stale['path']), ('group', []))
            current = groups.browse('Local Business', path='["One"]', path_fields='["team"]')
            self.assertEqual((current['kind'], current['path_fields']), ('record', ['team']))
            self.assertEqual(sorted(row['name'] for row in current['items']), ['a', 'c', 'f'])
            with self.assertRaises(ValueError):
                groups.browse('Local Business', path='["One", "One"]')
            with self.assertRaises(ValueError):
                groups.browse('Local Business', path='["One"]', path_fields='[1]')

    def test_legacy_records_search_contacts_before_group_filter_and_paging(self):
        with patch.object(groups, 'configuration', return_value=['region']):
            for search in ('Alice', '555001'):
                page = groups.records('Local Business', group='', query=search)
                self.assertEqual([row.name for row in page['items']], ['a', 'b'])
                self.assertEqual(groups.records('Local Business', group='North', query=search)['items'], [])
            self.assertEqual(groups.records('Local Business', group='', query='555999')['items'], [])
            self.assertEqual([row.name for row in groups.records('Local Business', group='', query='Alice', start=1)['items']], ['b'])

    def test_legacy_records_restore_permission_filtered_previews_and_descriptions(self):
        with patch.object(groups, 'configuration', return_value=['region']), \
                patch('relay_core.summaries.business_previews', return_value={'a': 'Visible summary'}):
            rows = groups.records('Local Business')['items']
        self.assertEqual((rows[0].last_message, rows[0].description, rows[0].summary),
                         ('Visible preview', 'Contact: Alice', 'Visible summary'))
        self.assertEqual(rows[1].last_message, 'Second preview')
        self.assertEqual(self.fake.db.sql.call_count, 4, 'Record page, activity, latest messages and descriptions are batched')

    def test_channel_and_record_filters_apply_before_group_totals(self):
        with patch.object(groups, 'configuration', return_value=['region']), \
                patch('relay_core.business_types.list_types', return_value=[_dict(business_doctype='Local Business', enabled=1, label='Local')]):
            page = groups.browse(channels=['ch1'], business_type='Local Business', business_name='a')
            self.assertEqual((page['items'][0]['record_count'], page['items'][0]['unread']), (1, 3))
            self.assertEqual(groups.browse(channels=[])['items'], [])
            self.assertEqual(groups.browse(business_type='Other')['items'], [])
            self.assertEqual(groups.browse('Local Business', business_type='Other')['items'], [])
            self.assertEqual({row['value']: row['record_count'] for row in groups.browse('Local Business', channels=['ch2'])['items']}, {'': 1, 'North': 2})
            self.chat_query.return_value = 'restricted'
            filtered = groups.browse('Local Business', channels=['ch1'])['items'][0]
            self.assertEqual((filtered['record_count'], filtered['unread']), (1, 1))

    def test_contacts_count_unique_readable_people_without_multiplying_records(self):
        row = groups.aggregate('Local Business', ['region'], [], contacts=True)[0]
        self.assertEqual((row.record_count, row.contact_count, row.unread), (2, 1, 0))
        rows = groups.aggregate('Local Business', ['region'], [''], contacts=True)
        self.assertEqual([(row.name, row.contact_count) for row in rows], [('a', 1), ('b', 1)])

    def test_permission_parameters_and_literal_percent_survive_outer_binding(self):
        from pymysql.converters import escape_item, encoders
        values = {}
        sql = groups.bound_query(self.query("SELECT %(param1)s WHERE '100% Cotton'='100% Cotton'", {'param1': '50% Silk'}), values, 'first_')
        sql += ' UNION ALL ' + groups.bound_query(self.query('SELECT %(param1)s', {'param1': 'Other'}), values, 'second_')
        bound = sql % {key: escape_item(value, 'utf8mb4', encoders) for key, value in values.items()}
        self.assertEqual(bound, "SELECT '50% Silk' WHERE '100% Cotton'='100% Cotton' UNION ALL SELECT 'Other'")
        self.fake.qb.get_query.side_effect = lambda doctype, **kwargs: self.query(
            'SELECT name FROM `tabLocal Business` WHERE title<>%(param1)s', {'param1': '100% Cotton' if doctype == 'Local Business' else 'Other'})
        self.db.execute('CREATE TABLE `tabOther` AS SELECT * FROM `tabLocal Business`')
        tickets = [_dict(business_doctype=dt, business_name='a') for dt in ('Local Business', 'Other')]
        groups.ticket_values(tickets)
        self.assertEqual([ticket.business_title for ticket in tickets], ['Alpha', 'Alpha'])
        params = self.fake.db.sql.call_args.args[1]
        self.assertEqual((params['ticket0_param1'], params['ticket1_param1']), ('100% Cotton', 'Other'))

    def test_large_directory_keeps_counts_and_pagination_in_one_query(self):
        self.db.executemany('INSERT INTO `tabLocal Business` VALUES (?, ?, ?, ?, ?)',
            [(f'load-{i:05}', f'Local load {i}', 'Load', 'One', int(i % 3 != 0)) for i in range(15000)])
        self.fake.db.sql.reset_mock()
        rows = groups.aggregate('Local Business', ['region'], ['Load'], start=30)
        self.assertEqual(len(rows), 31)
        self.assertEqual((rows[0].name, rows[-1].name), ('load-00046', 'load-00091'))
        self.assertEqual(self.fake.db.sql.call_count, 2)
        total = groups.aggregate('Local Business', ['region'], ['Load'], totals=True)[0]
        self.assertEqual((total.record_count, total.unread, total.unread_records), (10000, 0, 0))

    def test_restricted_activity_checks_contacts_channels_triage_and_read_state(self):
        self.chat_query.return_value = 'restricted'
        self.db.execute("UPDATE `tabRelay Message` SET allowed=1 WHERE name='m2'")
        self.assertEqual(groups.aggregate('Local Business', [], [], business_name='a')[0].unread, 1)
        self.db.execute("UPDATE `tabRelay Message` SET unread=0 WHERE name='m1'")
        row = groups.aggregate('Local Business', [], [], business_name='a')[0]
        self.assertEqual((row.unread, row.last_activity), (0, '2026-10-01'))
        self.db.execute("UPDATE `tabRelay Message` SET legacy_triage=1 WHERE name='m1'")
        self.assertIsNone(groups.aggregate('Local Business', [], [], business_name='a')[0].last_activity)
        self.db.execute("UPDATE `tabRelay Message` SET legacy_triage=0 WHERE name='m1'")
        self.db.execute("UPDATE `tabRelay Channel` SET allowed=0 WHERE name='ch1'")
        self.assertIsNone(groups.aggregate('Local Business', [], [], business_name='a')[0].last_activity)

    def test_contacts_root_includes_permission_filtered_unlinked_count(self):
        original = self.fake.qb.get_query.side_effect
        def query(doctype, **kwargs):
            if kwargs.get('fields') == [{'COUNT': 'name', 'as': 'total'}]:
                self.assertTrue(kwargs['ignore_permissions'])
                self.assertEqual(kwargs['filters'], ['unlinked predicate'])
                return SimpleNamespace(run=lambda **kwargs: [{'total': 2}])
            return original(doctype, **kwargs)
        self.fake.qb.get_query.side_effect = query
        with patch.object(groups, 'configuration', return_value=[]), \
                patch('relay_core.contacts.unlinked_people', return_value='unlinked predicate'), \
                patch('relay_core.business_types.list_types', return_value=[_dict(business_doctype='Local Business', enabled=1, label='Local')]):
            page = groups.browse(contacts=1)
        self.assertEqual(page['items'][0]['contact_count'], 1)
        self.assertEqual(page['items'][-1], {'kind': 'unlinked', 'label': 'Not linked', 'contact_count': 2})

    def test_summary_previews_batch_evidence_and_reject_hidden_or_changed_sources(self):
        from relay_core import summaries
        content = [{'message': 'm1', 'time': '2026-10-01', 'direction': 'Incoming', 'text': 'Visible preview', 'contact': 'Alice'}]
        ready = _dict(business_name='a', channel='ch1', sources='["m1"]', input_hash=summaries.digest(content),
                      result='{"overview": "Visible summary"}')
        hidden = _dict(ready, sources='["m1", "m2"]', result='{"overview": "Hidden summary"}')
        stale = _dict(ready, input_hash='old', result='{"overview": "Stale summary"}')
        self.fake.get_all.return_value = [hidden, stale, ready]
        with patch.object(summaries, 'frappe', self.fake), patch.object(summaries.ai_features, 'is_enabled', return_value=True):
            self.assertEqual(summaries.business_previews('Local Business', ('a', 'b')), {'a': 'Visible summary'})
            self.fake.db.sql.assert_called_once()
            self.fake.get_all.assert_called_once()
            self.db.execute("UPDATE `tabRelay Contact` SET allowed=0 WHERE name='r1'")
            self.assertEqual(summaries.business_previews('Local Business', ('a', 'b')), {})

    def test_current_behavior_docs_have_no_validation_or_handoff_sections(self):
        from pathlib import Path
        doc = (Path(__file__).resolve().parents[1] / 'docs/business-grouping.md').read_text()
        self.assertNotRegex(doc.lower(), r'validation|handoff|migrat|bench |export-fixtures')
        self.assertIn('record badges count unread messages', doc)
        self.assertIn('Contacts tiles show contact counts', doc)
        self.assertTrue(all('\n' not in paragraph for paragraph in doc.strip().split('\n\n')))

    def unstamped(self, *links, primary=None):
        """Contact carol (r3) with `links`, and one unread incoming message on ch2 that names no record."""
        self.db.execute("INSERT INTO `tabContact` VALUES ('carol', 'Carol', '555003', '', '', 1)")
        self.db.execute("INSERT INTO `tabRelay Contact` VALUES ('r3', 'carol', 'Carol', 1, ?, ?)", primary or (None, None))
        self.db.executemany("INSERT INTO `tabDynamic Link` VALUES ('carol', 'Contact', 'links', ?, ?)", links)
        self.db.execute("INSERT INTO `tabRelay Message` (name, relay_contact, channel, content, direction, sent_at, creation, "
                        "legacy_triage, allowed, unread) VALUES ('m4', 'r3', 'ch2', 'No record', 'Incoming', '2026-10-06', '2026-10-06', 0, 1, 1)")
        self.chat_query.return_value = 'restricted'

    def test_restricted_activity_counts_unstamped_messages_under_the_contacts_only_record(self):
        self.unstamped(('Local Business', 'e'), ('Disabled Type', 'x'))
        row = groups.aggregate('Local Business', [], [], business_name='e')[0]
        self.assertEqual((row.unread, row.last_activity, row.unread_records), (1, '2026-10-06', 1))
        rows = groups.aggregate('Local Business', ['region'], ['North'], channels=['ch2'])
        self.assertEqual([(row.name, row.unread) for row in rows], [('e', 1)])
        total = groups.aggregate('Local Business', [], [], totals=True)[0]
        self.assertEqual((total.unread, total.last_activity), (3, '2026-10-06'))

    def test_unstamped_messages_of_multi_record_contacts_need_a_marked_primary(self):
        self.unstamped(('Local Business', 'e'), ('Other', 'z'))
        self.assertIsNone(groups.aggregate('Local Business', [], [], business_name='e')[0].last_activity)
        self.db.execute("UPDATE `tabRelay Contact` SET primary_doctype='Other', primary_name='z' WHERE name='r3'")
        self.assertIsNone(groups.aggregate('Local Business', [], [], business_name='e')[0].last_activity)
        self.db.execute("UPDATE `tabRelay Contact` SET primary_doctype='Local Business', primary_name='e' WHERE name='r3'")
        self.assertEqual(groups.aggregate('Local Business', [], [], business_name='e')[0].unread, 1)

    def test_unstamped_messages_follow_message_scope_and_triage(self):
        self.unstamped(('Local Business', 'e'))
        self.db.execute("UPDATE `tabRelay Message` SET allowed=0 WHERE name='m4'")
        self.assertIsNone(groups.aggregate('Local Business', [], [], business_name='e')[0].last_activity)
        self.db.execute("UPDATE `tabRelay Message` SET allowed=1, legacy_triage=1 WHERE name='m4'")
        self.assertIsNone(groups.aggregate('Local Business', [], [], business_name='e')[0].last_activity)

    def test_restricted_totals_and_groups_filter_by_newest_channel(self):
        self.chat_query.return_value = 'restricted'
        self.db.execute("UPDATE `tabRelay Message` SET allowed=1 WHERE name='m2'")
        total = groups.aggregate('Local Business', [], [], totals=True)[0]
        self.assertEqual((total.record_count, total.unread, total.unread_records, total.last_activity), (5, 2, 2, '2026-10-02'))
        rows = groups.aggregate('Local Business', ['region'], [])
        self.assertEqual([(row.value, row.unread, row.last_activity) for row in rows],
                         [('', 2, '2026-10-02'), ('North', 0, None)])
        rows = groups.aggregate('Local Business', ['region'], [], channels=['ch1'])
        self.assertEqual([(row.value, row.record_count, row.unread) for row in rows], [('', 1, 1)])

    def test_browse_orders_records_by_newest_readable_activity_then_title(self):
        with patch.object(groups, 'configuration', return_value=[]):
            def names(**kwargs):
                return [row['name'] for row in groups.browse('Local Business', **kwargs)['items']]

            self.assertEqual(names(), ['f', 'c', 'b', 'a', 'e'], 'Unrestricted viewers use Relay Chat times')
            self.unstamped(('Local Business', 'e'))
            self.assertEqual(names(), ['e', 'b', 'a', 'f', 'c'], 'A hidden newer message does not lift a; no activity sorts by title')
            self.assertEqual(names(query='a'), ['b', 'a', 'f', 'c'], 'Search keeps the order')
            self.assertEqual(names(channels=['ch2']), ['e', 'b'])
            self.assertEqual([row['name'] for row in groups.records('Local Business')['items']], ['a', 'b', 'c', 'e', 'f'],
                             'Legacy pickers keep name order')

    def test_record_pages_follow_activity_order_without_duplicates(self):
        self.chat_query.return_value = 'restricted'
        for index in range(70):
            self.db.execute('INSERT INTO `tabLocal Business` VALUES (?, ?, ?, ?, ?)', (f'z{index:03}', f'Record {index % 7}', '', '', 1))
            if index % 3 == 0:
                self.db.execute("INSERT INTO `tabRelay Message` (name, business_doctype, business_name, relay_contact, channel, direction, "
                                "sent_at, creation, legacy_triage, allowed, unread) VALUES (?, 'Local Business', ?, 'r1', 'ch1', 'Incoming', ?, ?, 0, 1, 0)",
                                (f'mz{index}', f'z{index:03}', f'2026-09-{index % 28 + 1:02}', '2026-09-01'))
        with patch.object(groups, 'configuration', return_value=[]):
            pages, start = [], 0
            while start is not None:
                page = groups.browse('Local Business', start=start)
                pages += page['items']
                start = page['next']
        self.assertEqual(len(pages), len({row['name'] for row in pages}))
        self.assertEqual(len(pages), 75)
        dated = [row['last_activity'] for row in pages if row['last_activity']]
        self.assertEqual(dated, sorted(dated, reverse=True))
        undated = pages[len(dated):]
        self.assertFalse(any(row['last_activity'] for row in undated))
        self.assertEqual([(row['label'], row['name']) for row in undated], sorted((row['label'], row['name']) for row in undated))

    def test_browse_orders_group_tiles_by_newest_activity_and_directory_by_value(self):
        with patch.object(groups, 'configuration', return_value=['region']):
            self.assertEqual([row['value'] for row in groups.browse('Local Business')['items']], ['North', ''])
            self.assertEqual([row.value for row in groups.directory('Local Business')['items']], ['', 'North'])

    def test_empty_record_page_skips_activity(self):
        self.chat_query.return_value = 'restricted'
        self.fake.db.sql.reset_mock()
        self.assertEqual(groups.aggregate('Local Business', [], [], 'nothing matches'), [])
        self.fake.db.sql.assert_called_once()

    def test_bad_path_and_page_never_query_business_data(self):
        for value in ('{}', '[1]', '["a", "b", "c"]'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                groups.path_values(value, ['region', 'team'])
        for value in (-1, True, 'x', 100001):
            with self.subTest(value=value), self.assertRaises(ValueError):
                groups.aggregate('Local Business', [], [], start=value)
        self.fake.db.sql.assert_not_called()


if __name__ == '__main__':
    unittest.main()


class BusinessTimeIndexTests(unittest.TestCase):
    def run_install(self, db_type):
        from relay_core import timeline
        fake = Mock()
        fake.conf.db_type = db_type
        fake.db.has_column.return_value = True
        with patch.object(timeline, 'frappe', fake):
            timeline.install_indexes()
            return fake, timeline.timeline_sql('m')

    def test_business_activity_index_and_time_expression_on_both_engines(self):
        fake, time = self.run_install('mariadb')
        fake.db.add_index.assert_any_call('Relay Message', ['business_doctype', 'business_name', 'relay_timeline_time', 'name'], 'relay_business_time')
        self.assertEqual(time, 'm.relay_timeline_time')
        from relay_core import timeline
        with patch.object(timeline, 'frappe', fake):
            self.assertEqual(timeline.index_hint('relay_business_time'), ' FORCE INDEX (`relay_business_time`)')
        fake, time = self.run_install('postgres')
        statements = [call.args[0] for call in fake.db.sql.call_args_list]
        self.assertIn('CREATE INDEX IF NOT EXISTS "relay_business_time" ON "tabRelay Message" '
                      '(business_doctype, business_name, (COALESCE(sent_at, creation)), name)', statements)
        self.assertEqual(time, 'COALESCE(m.sent_at, m.creation)')
        with patch.object(timeline, 'frappe', fake):
            self.assertEqual(timeline.index_hint('relay_business_time'), '')
