"""Knowledge base: chunking, parameter-only SQL, the LIKE fallback, scope rules, the tool boundary and approvals."""
import sys
import types
import unittest
from unittest.mock import Mock, patch

from test_ai_skills import Doc, framework, module
from relay_core.ai import reply_guard
from relay_core.ai.knowledge_base.chunker import chunk_text
from relay_core.ai.tools import STAFF_ONLY
from relay_core.ai.registry import ToolContext  # noqa: F401 - loads the registry on the real framework first

SOURCE_MODULE = 'relay_core.relay_core.doctype.relay_ai_knowledge_source.relay_ai_knowledge_source'


class ChunkerTests(unittest.TestCase):
    def test_paragraphs_stay_whole_and_chunks_respect_size_and_overlap(self):
        paragraphs = [f'Paragraph {index} ' + 'word ' * 30 for index in range(6)]
        chunks = chunk_text('\n\n'.join(paragraphs), size=400, overlap=60)
        self.assertTrue(all(len(chunk) <= 400 for chunk in chunks))
        self.assertEqual(chunks[0], '\n\n'.join(paragraph.strip() for paragraph in paragraphs[:2]))
        # The next chunk starts with whole words from the end of the one before it.
        tail = chunks[1].split('\n\n')[0]
        self.assertTrue(0 < len(tail) <= 60 and chunks[0].endswith(tail), tail)

    def test_long_paragraph_splits_on_sentences_including_danda_then_words(self):
        hindi = 'छूट दस प्रतिशत है। ' * 20
        chunks = chunk_text(hindi, size=100, overlap=0)
        self.assertTrue(all(chunk.endswith('है।') and len(chunk) <= 100 for chunk in chunks))
        self.assertEqual(chunk_text('x' * 250, size=100, overlap=0), ['x' * 100, 'x' * 100, 'x' * 50])
        self.assertEqual(chunk_text('  \n\n ', size=100, overlap=10), [])

    def test_invalid_sizes_are_refused(self):
        for size, overlap in ((0, 0), (100, 100), (100, -1)):
            with self.subTest(size=size, overlap=overlap), self.assertRaises(ValueError):
                chunk_text('text', size=size, overlap=overlap)


def store_module(db_type='mariadb'):
    f = framework()
    f.conf = Doc(db_type=db_type)
    return f, module('relay_core/ai/knowledge_base/store.py', f,
                     {'frappe.utils': types.SimpleNamespace(now_datetime=lambda: '2026-11-04 12:00:00')})


class StoreTests(unittest.TestCase):
    def test_every_value_is_a_parameter_and_like_words_are_escaped(self):
        f, store = store_module()
        query = "Gate 4'; DROP TABLE x; -- 50%_off"
        f.db.sql.side_effect = [[], [Doc(name='c1', content='Gate 4', source='S1', business_name=None, score=1)]]
        rows = store.search(['S1'], query, 'Acme Textiles', ('Customer', 'Kestrel Traders'), 5)
        self.assertEqual(rows[0].content, 'Gate 4')
        for call in f.db.sql.call_args_list:
            sql, values = call.args
            for value in ('DROP', 'Acme Textiles', 'Kestrel Traders', 'S1', '50'):
                self.assertNotIn(value, sql)
            self.assertEqual((values['sources'], values['business_name']), (('S1',), 'Kestrel Traders'))
        fallback = f.db.sql.call_args_list[1].args
        self.assertIn('LIMIT 200) scoped', fallback[0])
        self.assertEqual(sorted(value for key, value in fallback[1].items() if key.startswith('word')),
                         ['%DROP%', '%Gate%', '%TABLE%'])
        self.assertEqual(store.escape_like('50%_a\\b'), '50\\%\\_a\\\\b')

    def test_fulltext_hits_skip_the_fallback(self):
        f, store = store_module()
        f.db.sql.return_value = [Doc(name='c1')]
        store.search(['S1'], 'parking', None, ('Customer', 'Kestrel Traders'), 5)
        self.assertEqual(f.db.sql.call_count, 1)

    def test_indic_words_keep_their_vowel_signs(self):
        _, store = store_module()
        self.assertEqual(store.like_words('வெள்ளிக்கிழமை பதிவு?'), ['வெள்ளிக்கிழமை', 'பதிவு'])
        self.assertEqual(store.like_words('കിഴിവ് എത്ര'), ['കിഴിവ്', 'എത്ര'])

    def test_postgres_has_no_search_or_fulltext_ddl(self):
        f, store = store_module('postgres')
        with self.assertRaises(store.Unsupported):
            store.search(['S1'], 'parking', None, ('Customer', 'Kestrel Traders'), 5)
        store.install_indexes()
        f.db.sql.assert_not_called()


class Rows(list):
    """frappe.get_all over fixed rows with dict filters of `=` and `in`."""
    def __call__(self, doctype, filters=None, fields=None, **kwargs):
        def matches(row):
            return all(row.get(key) in value[1] if isinstance(value, list) else row.get(key) == value
                       for key, value in (filters or {}).items())
        found = [row for row in self if row['doctype'] == doctype and matches(row)]
        return found[:kwargs['limit']] if kwargs.get('limit') else found


class RetrieverTests(unittest.TestCase):
    def setUp(self):
        self.f = framework()
        self.rows = Rows([
            Doc(doctype='Relay AI Knowledge Base', name='KB-SHARED', enabled=1, audience='customer', company=None, title='Shared', description='Price lists'),
            Doc(doctype='Relay AI Knowledge Base', name='KB-STAFF', enabled=1, audience='staff', company=None, title='Staff'),
            Doc(doctype='Relay AI Knowledge Base', name='KB-OFF', enabled=0, audience='customer', company=None, title='Off'),
            Doc(doctype='Relay AI Knowledge Base', name='KB-OTHER', enabled=1, audience='customer', company='Other Co', title='Other'),
            Doc(doctype='Relay AI Knowledge Source', name='S-TEXT', knowledge_base='KB-SHARED', source_type='Text'),
            Doc(doctype='Relay AI Knowledge Source', name='S-STAFF', knowledge_base='KB-STAFF', source_type='Text'),
            Doc(doctype='Relay AI Knowledge Source', name='S-EVENT', knowledge_base='KB-SHARED', source_type='Event', event='EV-1'),
            Doc(doctype='Relay AI Knowledge Source', name='S-ROWS', knowledge_base='KB-SHARED', source_type='DocType'),
        ])
        self.f.get_all = self.rows
        self.f.get_cached_doc = lambda doctype, name: next(row for row in self.rows if row.name == name)
        self.store = types.SimpleNamespace(is_supported=lambda: True, search=Mock(return_value=[
            Doc(content='x' * 2000, score=1.5, source='S-TEXT')]))
        self.events = Mock(return_value=[])
        self.approved = Mock(return_value=False)
        self.enterContext(patch.dict(sys.modules, {
            'relay_core.ai.event_memory': types.SimpleNamespace(eligible_events=self.events),
            SOURCE_MODULE: types.SimpleNamespace(is_approved=self.approved)}))
        self.retriever = module('relay_core/ai/knowledge_base/retriever.py', self.f,
                                {'relay_core.ai.knowledge_base': types.SimpleNamespace(store=self.store)})
        self.skill = Doc(knowledge_bases=[Doc(knowledge_base=name) for name in ('KB-SHARED', 'KB-STAFF', 'KB-OFF', 'KB-OTHER')])

    def search(self, business=('Customer', 'Kestrel Traders'), **kwargs):
        return self.retriever.search(self.skill, business, 'Acme Textiles', 'parking', **kwargs)

    def test_only_enabled_customer_bases_of_the_company_and_eligible_sources(self):
        found = self.search()
        names, query, company, business, limit = self.store.search.call_args.args
        self.assertEqual((names, query, company, business, limit), (['S-TEXT'], 'parking', 'Acme Textiles', ('Customer', 'Kestrel Traders'), 5))
        self.assertEqual(found, [{'text': 'x' * 1500, 'score': 1.5, 'source': 'S-TEXT'}])
        self.events.return_value = [Doc(name='EV-1')]
        self.approved.return_value = True
        self.search(business=('Supplier', 'Riverside Traders Association'))
        self.assertEqual(sorted(self.store.search.call_args.args[0]), ['S-EVENT', 'S-ROWS', 'S-TEXT'])
        self.events.assert_called_with('Supplier', 'Acme Textiles', limit=None)

    def test_doctype_chunks_count_only_after_a_sweep_under_the_current_approval(self):
        self.approved.return_value = True
        rows = next(row for row in self.rows if row.name == 'S-ROWS')
        for revision, approved_hash, found in (('h-old', 'h-new', False), (None, 'h-new', False), ('h-new', 'h-new', True)):
            rows.revision, rows.approved_hash = revision, approved_hash
            with self.subTest(revision=revision):
                self.search()
                self.assertEqual('S-ROWS' in self.store.search.call_args.args[0], found)

    def test_no_bound_base_raises_and_invalid_input_is_refused(self):
        self.skill.knowledge_bases = []
        with self.assertRaises(ValueError):
            self.search()
        self.assertFalse(self.retriever.is_offered(self.skill))
        self.skill.knowledge_bases = [Doc(knowledge_base='KB-SHARED')]
        for query, limit in (('', 5), ('a' * 301, 5), ('parking', 11)):
            with self.subTest(query=query[:5], limit=limit), self.assertRaises(ValueError):
                self.retriever.search(self.skill, ('Customer', 'Kestrel Traders'), None, query, limit=limit)

    def test_staff_bases_are_never_offered_to_customers(self):
        self.skill.knowledge_bases = [Doc(knowledge_base='KB-STAFF')]
        self.assertFalse(self.retriever.is_offered(self.skill))
        self.assertEqual(self.search(), [])
        self.store.search.assert_not_called()
        self.assertTrue(self.retriever.is_offered(self.skill, 'staff'))
        self.skill.knowledge_bases = [Doc(knowledge_base='KB-SHARED')]
        self.assertIn('- Shared: Price lists', self.retriever.description(self.skill))

    def test_tool_errors_reach_the_model_as_fixed_text(self):
        context = types.SimpleNamespace(skill=self.skill, user='partner', business=('Customer', 'Kestrel Traders'),
                                        scope={'company': 'Acme Textiles'}, sources=[])
        reader = Mock()
        self.enterContext(patch.dict(sys.modules, {
            'relay_core.ai.tools': types.SimpleNamespace(Reader=Mock(return_value=reader)),
            'relay_core.ai.identity': types.SimpleNamespace(validate=Mock())}))
        result = self.retriever.search_knowledge.function('parking', ctx=context)
        self.assertEqual(result, {'note': self.retriever.NOTE, 'results': ['x' * 1500]})
        for error in (ValueError('Sender scope changed for Northwind Hosiery'), RuntimeError('SQL error in KB-STAFF')):
            reader.check_scope.side_effect = error
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, '^Knowledge search is unavailable$'):
                self.retriever.search_knowledge.function('parking', ctx=context)


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.f = framework()
        self.f.throw = Mock(side_effect=lambda message: (_ for _ in ()).throw(ValueError(message)))
        self.neutral = Mock(side_effect=ValueError('not neutral'))
        meta = Doc(get_field=lambda name: {'customer': Doc(fieldtype='Link'), 'project_name': Doc(fieldtype='Data'), 'notes': Doc(fieldtype='Text Editor'),
                                           'items': Doc(fieldtype='Table')}.get(name))
        self.enterContext(patch.dict(sys.modules, {
            'frappe_tools.ai.tools': types.SimpleNamespace(get_readable_meta=lambda doctype: meta,
                                                           is_sensitive_field=lambda name: 'password' in name),
            'relay_core.ai.tools': types.SimpleNamespace(company_neutral=self.neutral, STAFF_ONLY=STAFF_ONLY)}))
        document = types.SimpleNamespace(Document=type('Document', (Doc,), {}))
        self.controller = module('relay_core/relay_core/doctype/relay_ai_knowledge_source/relay_ai_knowledge_source.py',
                                 self.f, {'frappe.model.document': document, 'relay_core.ai_features': types.SimpleNamespace(required=lambda fn: fn)})
        self.base = Doc(name='KB-1', audience='customer', company=None, run_as_user='reader@example.com')

    def source(self, **values):
        return Doc(dict(source_type='DocType', reference_doctype='Project', content_fields='project_name\nnotes',
                        business_field='customer', filters='{"status": "Open"}', approved_hash=None), **values)

    def test_staff_only_doctypes_never_become_customer_sources(self):
        self.neutral.side_effect = None  # Even a company neutral listing cannot open staff notes.
        for doctype in ('Relay Internal Comment', 'Comment', 'Relay Ticket'):
            with self.subTest(doctype=doctype), self.assertRaisesRegex(ValueError, 'staff-only'):
                self.controller.validate_doctype_source(self.source(reference_doctype=doctype, business_field=None),
                                                        self.base)
        self.base.audience = 'staff'
        self.controller.validate_doctype_source(self.source(reference_doctype='Comment', business_field=None), self.base)

    def test_customer_rows_need_a_business_field_unless_company_neutral(self):
        self.controller.validate_doctype_source(self.source(), self.base)
        with self.assertRaisesRegex(ValueError, 'business field'):
            self.controller.validate_doctype_source(self.source(business_field=None), self.base)
        self.neutral.side_effect = None
        self.controller.validate_doctype_source(self.source(business_field=None), self.base)
        for values in (dict(content_fields='items'), dict(content_fields='api_password'), dict(filters='[1]'),
                       dict(business_field='notes')):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.controller.validate_doctype_source(self.source(**values), self.base)

    def test_any_scope_change_needs_a_new_approval(self):
        source = self.source()
        source.approved_hash = self.controller.config_hash(source, self.base)
        self.assertTrue(self.controller.is_approved(source, self.base))
        for changed, base in ((dict(content_fields='project_name'), self.base), (dict(business_field='owner'), self.base),
                              (dict(filters='{}'), self.base), ({}, Doc(self.base, audience='staff')),
                              ({}, Doc(self.base, run_as_user='other@example.com'))):
            with self.subTest(changed=changed, audience=base.audience):
                self.assertFalse(self.controller.is_approved(Doc(source, **changed), base))
        self.assertTrue(self.controller.is_approved(Doc(source_type='Text'), self.base))

    def test_a_shared_customer_source_stops_when_its_doctype_is_no_longer_company_neutral(self):
        self.neutral.side_effect = None
        source = self.source(business_field=None)
        source.approved_hash = self.controller.config_hash(source, self.base)
        self.assertTrue(self.controller.is_approved(source, self.base))
        self.neutral.side_effect = ValueError('This business type is not company neutral')
        self.assertFalse(self.controller.is_approved(source, self.base))

    def test_a_form_save_cannot_set_the_approval(self):
        doc = self.controller.RelayAIKnowledgeSource(self.source(source_type='Text', content='Hi', chunk_size=1200,
            chunk_overlap=150, approved_hash='forged', approved_by='Administrator', approved_on='now'))
        doc.flags, doc.is_new, doc.set = Doc(), lambda: True, doc.__setitem__
        doc.validate()
        self.assertEqual((doc.approved_hash, doc.approved_by, doc.approved_on), (None, None, None))


class ChunkGuardTests(unittest.TestCase):
    def test_returned_chunks_allow_contacts_and_quotes_but_shared_chunks_do_not_allow_names(self):
        f = framework()
        f.db.exists.return_value = True
        f.get_doc.return_value = Doc()
        f.get_all.side_effect = lambda doctype, filters, **kwargs: [name for name in filters['name'][1]
                                                                    if (doctype, name) == ('Customer', 'Northwind Hosiery')]
        self.enterContext(patch.object(reply_guard, 'frappe', f))
        self.enterContext(patch('relay_core.business_access.candidates', return_value=[]))
        chunk = 'Parking is at Gate 4 near the canal and the help desk number is 919000000101 for every visitor.'
        scope = dict(company=None, business=['Customer', 'Kestrel Traders'])
        skill = Doc(instructions='Answer briefly.')
        # Chunks go to evidence only; a long verbatim quote of a chunk is a normal answer.
        reply_guard.check(chunk, skill, scope, evidence=reply_guard.contacts({'results': [chunk]}), knowledge=())
        with self.assertRaises(reply_guard.ReplyBlocked):
            reply_guard.check('Call 919000000101.', skill, scope, evidence=(), knowledge=())
        with self.assertRaises(reply_guard.ReplyBlocked):
            reply_guard.check('Northwind Hosiery also parks there.', skill, scope,
                              evidence=['Northwind Hosiery also parks there.'], knowledge=())


class EventsBaseTests(unittest.TestCase):
    def test_the_events_base_is_for_every_company_not_the_users_default(self):
        from relay_core.ai.knowledge_base import ingest
        f = framework()
        f.db.get_value.return_value = None
        f.get_doc.side_effect = lambda values: Doc(values, name='KB-EVENTS', flags=Doc())
        with patch.object(ingest, 'frappe', f):
            self.assertEqual(ingest.events_base(), 'KB-EVENTS')
        self.assertEqual(f.get_doc.call_args.args[0].get('company'), '')


if __name__ == '__main__':
    unittest.main()
