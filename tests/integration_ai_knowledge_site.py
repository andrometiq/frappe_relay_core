"""Local relay.test acceptance of knowledge base ingest and retrieval on MariaDB FULLTEXT; no model or channel calls.

Run from the app folder: SITES_PATH=<bench>/sites ../../env/bin/python -B -m unittest discover -s tests -p 'integration_ai_knowledge_site.py'
Fixtures are fake (Acme Textiles, Kestrel Traders, Northwind Hosiery) and removed afterwards. Ingest jobs run inline.
"""
import os
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SITES = os.environ['SITES_PATH']
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import frappe

from relay_core.ai.knowledge_base import ingest, retriever

COMPANY = 'Acme Textiles'
READER = 'relay-knowledge-reader@example.invalid'
MULTILINGUAL = '\n\n'.join([
    'Riverside Traders Association annual meet: registration closes on Friday at the Sampleville hall.',
    'சாம்பிள்வில் அரங்கில் வெள்ளிக்கிழமை பதிவு முடிவடைகிறது. சலுகைகளுக்கு அழைக்கவும்.',
    'സാമ്പിൾവില്ലെ ഹാളിൽ വെള്ളിയാഴ്ച രജിസ്ട്രേഷൻ അവസാനിക്കും. കിഴിവ് പത്ത് ശതമാനം.',
    'सैंपलविल हॉल में शुक्रवार को पंजीकरण बंद होगा। छूट दस प्रतिशत है।'])


def text_pdf(pages):
    """A minimal PDF with one Helvetica text line per page."""
    objects = ['<< /Type /Catalog /Pages 2 0 R >>', None, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    kids = []
    for text in pages:
        stream = f'BT /F1 12 Tf 72 720 Td ({text}) Tj ET'
        objects.append(f'<< /Length {len(stream)} >>\nstream\n{stream}\nendstream')
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {len(objects)} 0 R '
                       '/Resources << /Font << /F1 3 0 R >> >> >>')
        kids.append(f'{len(objects)} 0 R')
    objects[1] = f'<< /Type /Pages /Kids [{" ".join(kids)}] /Count {len(pages)} >>'
    body, offsets = b'%PDF-1.4\n', []
    for number, value in enumerate(objects, 1):
        offsets.append(len(body))
        body += f'{number} 0 obj\n{value}\nendobj\n'.encode()
    xref = len(body)
    body += f'xref\n0 {len(objects) + 1}\n0000000000 65535 f \n'.encode()
    body += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets)
    return body + f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()


def skill(*bases):
    return frappe._dict(knowledge_bases=[frappe._dict(knowledge_base=name) for name in bases])


def texts(bases, query, business=('Customer', 'Kestrel Traders'), company=COMPANY):
    return [row['text'] for row in retriever.search(skill(*bases), business, company, query)]


class KnowledgeSiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.stack.enter_context(patch.object(frappe, 'enqueue'))
        cls.stack.enter_context(patch.object(frappe, 'publish_realtime'))
        os.chdir(SITES)
        frappe.init(site='relay.test', sites_path=SITES)
        frappe.connect()
        frappe.set_user('Administrator')
        assert Path(frappe.get_app_path('relay_core')).resolve().parent == ROOT, 'Run with the worktree first'
        for name in ('relay_ai_knowledge_base', 'relay_ai_knowledge_source', 'relay_ai_knowledge_chunk'):
            frappe.reload_doc('relay_core', 'doctype', name, force=True)
        cls.ai_enabled = frappe.db.get_single_value('Relay Settings', 'enable_ai_features')
        frappe.db.set_single_value('Relay Settings', 'enable_ai_features', 1)
        if not frappe.db.exists('User', READER):
            frappe.get_doc(dict(doctype='User', email=READER, first_name='Acme Textiles knowledge reader',
                                send_welcome_email=0, roles=[{'role': 'System Manager'}, {'role': 'Projects User'}])).insert()
        frappe.db.set_value('User', READER, 'enabled', 1)
        cls.created = []
        frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        frappe.db.rollback()
        # With AI off, removing an event file does not create a new event source.
        frappe.db.set_single_value('Relay Settings', 'enable_ai_features', cls.ai_enabled or 0)
        for doctype, name in reversed(cls.created):
            frappe.delete_doc(doctype, name, force=True, ignore_missing=True, ignore_permissions=True)
        frappe.db.set_value('User', READER, 'enabled', 0)
        frappe.db.commit()
        frappe.destroy()
        cls.stack.close()

    def make(self, doctype, **values):
        doc = frappe.get_doc(dict(doctype=doctype, **values)).insert(ignore_permissions=True)
        self.created.append((doctype, doc.name))
        return doc

    def base(self, title, **values):
        return self.make('Relay AI Knowledge Base', title='Acme Textiles ' + title, run_as_user=READER, **values).name

    def source(self, base, **values):
        doc = self.make('Relay AI Knowledge Source', knowledge_base=base, title='Acme Textiles source', **values)
        ingest.sync(doc.name)
        # InnoDB FULLTEXT sees rows only after commit.
        frappe.db.commit()
        return frappe.get_doc('Relay AI Knowledge Source', doc.name)

    def test_tamil_malayalam_hindi_and_english_queries_hit(self):
        base = self.base('Languages', audience='customer')
        self.assertEqual(self.source(base, source_type='Text', content=MULTILINGUAL, chunk_size=200, chunk_overlap=40).status, 'Completed')
        for query, expected in (('registration Friday', 'Riverside'), ('வெள்ளிக்கிழமை பதிவு', 'சாம்பிள்வில்'),
                                ('രജിസ്ട്രേഷൻ എപ്പോൾ', 'സാമ്പിൾവില്ലെ'), ('पंजीकरण कब', 'सैंपलविल'),
                                # Inside a longer inflected word only the LIKE fallback finds it.
                                ('சலுகை', 'சாம்பிள்வில்')):
            with self.subTest(query=query):
                found = texts([base], query)
                self.assertTrue(any(expected in text for text in found), found)

    def test_scope_drops_disabled_staff_and_other_company_bases(self):
        other_company = 'Sampleville Traders Co'
        if not frappe.db.exists('Company', other_company):
            frappe.get_doc(dict(doctype='Company', name=other_company, company_name=other_company, abbr='STC',
                                country='India', default_currency='INR')).db_insert()
            self.created.append(('Company', other_company))
        shared = self.base('Shared', audience='customer', company='')
        staff = self.base('Staff margins', audience='staff', company='')
        disabled = self.base('Disabled', audience='customer', enabled=0, company='')
        other = self.base('Other company', audience='customer', company=other_company)
        for base in (shared, staff, disabled, other):
            self.source(base, source_type='Text', content=f'Sampleville price list {base} carton rates')
        found = texts([shared, staff, disabled, other], 'Sampleville carton rates')
        self.assertEqual([shared in text for text in found], [True])
        with self.assertRaises(ValueError):
            retriever.search(skill(), ('Customer', 'Kestrel Traders'), COMPANY, 'carton')

    def test_event_pdf_page_three_and_customer_only_audience(self):
        # Saving the event creates its source and, on first use, the Events knowledge base.
        existing = frappe.db.get_value('Relay AI Knowledge Base', {'is_events': 1})
        event = self.make('Relay AI Event', title='Riverside Traders Association meet', enabled=1, company=COMPANY,
                          description='Annual meet of the Riverside Traders Association in Sampleville.',
                          audience=[{'business_doctype': 'Customer'}])
        pages = ['Welcome to the annual meet', 'The hall map is at the entrance', 'Parking is at Gate 4 near the canal']
        self.make('File', file_name='meet.pdf', attached_to_doctype='Relay AI Event', attached_to_name=event.name,
                  is_private=1, content=text_pdf(pages))
        # Today's memory keeps a few facts and drops page 3.
        frappe.db.set_value('Relay AI Event', event.name, dict(memory_status='Ready', memory_revision='r1',
            memory='Annual meet in Sampleville.\n- Welcome desk at the hall'), update_modified=False)
        ingest.queue_event(event.name)
        source = frappe.db.get_value('Relay AI Knowledge Source', {'event': event.name})
        if not existing:
            self.created.append(('Relay AI Knowledge Base', ingest.events_base()))
        self.created.append(('Relay AI Knowledge Source', source))
        ingest.sync(source)
        frappe.db.commit()
        self.assertNotIn('Gate 4', frappe.db.get_value('Relay AI Event', event.name, 'memory'))
        found = texts([ingest.events_base()], 'Where is parking?')
        self.assertTrue(found and 'Parking is at Gate 4' in found[0], found)
        self.assertEqual(texts([ingest.events_base()], 'Where is parking?', business=('Supplier', 'Riverside Traders Association')), [])
        frappe.db.set_value('Relay AI Event', event.name, 'enabled', 0)
        self.assertEqual(texts([ingest.events_base()], 'Where is parking?'), [])
        # The patch gives each existing event one source, also when run again.
        from relay_core.patches.v1_0 import index_ai_events
        frappe.delete_doc('Relay AI Knowledge Source', source, ignore_permissions=True)
        for _ in range(2):
            index_ai_events.execute()
        sources = frappe.get_all('Relay AI Knowledge Source', filters={'event': event.name}, pluck='name')
        self.assertEqual(len(sources), 1)
        self.created.append(('Relay AI Knowledge Source', sources[0]))

    def test_doctype_rows_follow_business_hash_filter_and_approval(self):
        from relay_core.relay_core.doctype.relay_ai_knowledge_source.relay_ai_knowledge_source import approve
        base = self.base('Projects', audience='customer')
        with self.assertRaises(frappe.ValidationError):
            self.make('Relay AI Knowledge Source', knowledge_base=base, title='Acme Textiles projects',
                      source_type='DocType', reference_doctype='Project', content_fields='project_name\nnotes')
        projects = {customer: self.make('Project', project_name=f'Sampleville looms for {customer}', company=COMPANY,
                                        customer=customer, status='Open', notes=f'Loom delivery {customer} week 12')
                    for customer in ('Kestrel Traders', 'Northwind Hosiery')}
        source = self.source(base, source_type='DocType', reference_doctype='Project', business_field='customer',
                             content_fields='project_name\nnotes', filters='{"status": "Open"}')
        self.assertEqual((source.status, source.chunk_count), ('Failed', 0))
        approve(source.name)
        ingest.sync(source.name)
        frappe.db.commit()
        found = texts([base], 'Sampleville loom delivery')
        self.assertEqual(len(found), 1)
        self.assertIn('Kestrel Traders', found[0])
        self.assertNotIn('Northwind Hosiery', ' '.join(found))
        chunk = lambda customer: frappe.db.get_value('Relay AI Knowledge Chunk', {'source': source.name,
            'reference_name': projects[customer].name}, 'name')
        before = chunk('Kestrel Traders'), chunk('Northwind Hosiery')
        frappe.db.set_value('Project', projects['Northwind Hosiery'].name, 'notes', 'Loom delivery moved to week 14')
        ingest.sync(source.name)
        self.assertEqual(chunk('Kestrel Traders'), before[0])
        self.assertNotEqual(chunk('Northwind Hosiery'), before[1])
        frappe.db.set_value('Project', projects['Kestrel Traders'].name, 'status', 'Completed')
        ingest.sync(source.name)
        self.assertIsNone(chunk('Kestrel Traders'))
        frappe.delete_doc('Project', projects['Northwind Hosiery'].name, force=True)
        ingest.sync(source.name)
        self.assertIsNone(chunk('Northwind Hosiery'))
        frappe.db.set_value('Project', projects['Kestrel Traders'].name, 'status', 'Open')
        ingest.sync(source.name)
        frappe.db.commit()
        self.assertEqual(len(texts([base], 'Sampleville loom delivery')), 1)
        doc = frappe.get_doc('Relay AI Knowledge Source', source.name)
        doc.content_fields = 'project_name\nnotes\nstatus'
        doc.approved_hash = doc.current_hash
        doc.save(ignore_permissions=True)
        self.assertNotEqual(doc.approved_hash, doc.current_hash)
        self.assertEqual(texts([base], 'Sampleville loom delivery'), [])
        frappe.delete_doc('Relay AI Knowledge Base', base, ignore_permissions=True)
        self.assertFalse(frappe.db.exists('Relay AI Knowledge Chunk', {'source': source.name}))


if __name__ == '__main__':
    unittest.main()
