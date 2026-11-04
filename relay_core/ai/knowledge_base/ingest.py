"""Knowledge source ingest into Relay AI Knowledge Chunk rows, without embeddings.

Text, File, URL and Event sources are one document: each run reads, chunks and replaces all chunks of the source in
one transaction, and skips unchanged text. DocType sources are a watermark sweep on `modified` in pages of 500, read
as the knowledge base's run-as user; a per-row hash skips unchanged rows, and rows that left the filter or were
deleted lose their chunks. One lock per source serialises runs."""
import types

import frappe
from frappe.utils import now_datetime, nowdate

from relay_core import ai_features
from relay_core.ai.knowledge_base import store
from relay_core.ai.knowledge_base.chunker import chunk_text

SOURCE = 'Relay AI Knowledge Source'
BASE = 'Relay AI Knowledge Base'
EVENT = 'Relay AI Event'
BATCH = 500
MAX_TEXT = 300000
LOCK_TIMEOUT = 1500


def queue_sync(source: str, rebuild: bool = False, revision: str | None = None) -> None:
    """One job per source input after commit; a newer input gets its own job, as event memory builds do."""
    revision = revision or str(frappe.db.get_value(SOURCE, source, 'modified'))
    job = store.content_hash(source, revision, rebuild)[:32]
    frappe.enqueue('relay_core.ai.knowledge_base.ingest.sync', queue='long', timeout=LOCK_TIMEOUT,
                   job_id='relay-ai-knowledge-' + job, deduplicate=True, enqueue_after_commit=True,
                   source=source, rebuild=rebuild)


@ai_features.when_enabled
def sync(source: str, rebuild: bool = False) -> None:
    if not frappe.db.exists(SOURCE, source):
        return
    key = frappe.cache.make_key('relay-ai-knowledge:' + source)
    with frappe.cache.lock(key, timeout=LOCK_TIMEOUT, blocking_timeout=LOCK_TIMEOUT):
        SourceSync(source).run(rebuild)


@frappe.whitelist(methods=['POST'])
@ai_features.required
def rebuild(name: str) -> None:
    """Purge and re-chunk one source."""
    from relay_core.business_access import document_name
    document_name(name)
    frappe.get_doc(SOURCE, name).check_permission('write')
    queue_sync(name, rebuild=True, revision=str(now_datetime()))


def sync_due() -> None:
    """Daily job: re-sync auto-sync DocType and URL sources."""
    for name in frappe.get_all(SOURCE, filters={'auto_sync': 1, 'source_type': ['in', ['DocType', 'URL']]},
                               pluck='name'):
        queue_sync(name, revision=nowdate())


class SourceSync:
    """One locked run of one source."""

    def __init__(self, name: str):
        self.doc = frappe.get_doc(SOURCE, name)
        self.base = frappe.get_doc(BASE, self.doc.knowledge_base)

    def run(self, rebuild: bool = False) -> None:
        started = now_datetime()
        self.doc.db_set('status', 'Processing', update_modified=False)
        frappe.db.commit()
        try:
            if self.doc.source_type == 'DocType':
                self.sweep(rebuild)
            else:
                self.replace(rebuild)
            values = dict(status='Completed', error_log='', last_synced_at=started,
                          chunk_count=frappe.db.count(store.CHUNK, {'source': self.doc.name}))
        except Exception as error:
            frappe.db.rollback()
            frappe.log_error(title=f'Relay AI knowledge source failed: {self.doc.name}',
                             reference_doctype=SOURCE, reference_name=self.doc.name)
            values = dict(status='Failed', error_log=(str(error) or type(error).__name__)[:2000])
        self.doc.db_set(values, update_modified=False)
        frappe.db.commit()

    def chunks(self, text: str, digest: str, **values) -> list[dict]:
        pieces = chunk_text(text, self.doc.chunk_size or 1200, self.doc.chunk_overlap or 0)
        return [dict(values, knowledge_base=self.doc.knowledge_base, source=self.doc.name, chunk_index=index,
                     content=piece, content_hash=digest) for index, piece in enumerate(pieces)]

    def replace(self, rebuild: bool) -> None:
        text, company = self.read()
        if len(text) > MAX_TEXT:
            raise ValueError(f'The source has more than {MAX_TEXT} characters of text')
        digest = store.content_hash(text, company, self.doc.chunk_size, self.doc.chunk_overlap)
        if digest == self.doc.revision and not rebuild:
            return
        store.delete(self.doc.name)
        store.insert(self.chunks(text, digest, company=company))
        self.doc.db_set('revision', digest, update_modified=False)

    def read(self) -> tuple[str, str | None]:
        """(text, chunk company). Files and links use the event source readers and their size limit."""
        from relay_core.ai.event_memory import file_limit
        from relay_core.ai.event_sources import SourceError, read_file, read_link
        kind = self.doc.source_type
        if kind == 'Text':
            return self.doc.content or '', self.base.company
        if kind == 'Event':
            return event_text(self.doc.event), frappe.db.get_value(EVENT, self.doc.event, 'company')
        if kind == 'File':
            source = read_file(self.attached_file(), file_limit())
        else:
            source = read_link(types.SimpleNamespace(idx=1, url=self.doc.url, note=self.doc.title), file_limit())
        if source.status != 'Read':
            raise SourceError(source.reason)
        return source.text, self.base.company

    def attached_file(self):
        """The File attached to this source; a file of another document is never read."""
        name = frappe.db.get_value('File', {'file_url': self.doc.file, 'attached_to_doctype': SOURCE,
                                            'attached_to_name': self.doc.name, 'is_folder': 0})
        if not name:
            raise ValueError('Attach the file to this source')
        return frappe.get_doc('File', name)

    def sweep(self, rebuild: bool) -> None:
        from relay_core.ai.tools import as_user
        from relay_core.relay_core.doctype.relay_ai_knowledge_source.relay_ai_knowledge_source import (
            filters_of, is_approved)
        if not is_approved(self.doc, self.base):
            raise ValueError('A manager must approve this source configuration')
        # A newly approved configuration reads every row again.
        rebuild = rebuild or self.doc.revision != self.doc.approved_hash
        if rebuild:
            store.delete(self.doc.name)
        watermark = None if rebuild else self.doc.last_synced_at
        filters = [[key, *value] if isinstance(value, (list, tuple)) else [key, '=', value]
                   for key, value in filters_of(self.doc).items()]
        rows = Rows(self.doc)
        with as_user(self.base.run_as_user):
            start = 0
            while True:
                page = frappe.get_list(self.doc.reference_doctype, fields=rows.fields,
                    filters=filters + ([['modified', '>=', watermark]] if watermark else []),
                    order_by='modified asc, name asc', offset=start, limit=BATCH)
                self.upsert(rows, page)
                if len(page) < BATCH:
                    break
                start += BATCH
            current = set(frappe.get_list(self.doc.reference_doctype, filters=filters, pluck='name', limit=0))
        store.delete(self.doc.name, sorted(set(store.indexed_hashes(self.doc.name)) - current))
        self.doc.db_set('revision', self.doc.approved_hash, update_modified=False)

    def upsert(self, rows: 'Rows', page: list) -> None:
        known = store.indexed_hashes(self.doc.name, [row.name for row in page])
        stale, chunks = [], []
        for row in page:
            text, values = rows.text(row), rows.scope(row)
            digest = store.content_hash(text, *values.values(), self.doc.chunk_size, self.doc.chunk_overlap) if text else None
            if known.get(row.name) == digest:
                continue
            if row.name in known:
                stale.append(row.name)
            if digest:
                chunks += self.chunks(text, digest, reference_doctype=self.doc.reference_doctype,
                                      reference_name=row.name, **values)
        store.delete(self.doc.name, stale)
        store.insert(chunks)


class Rows:
    """How one DocType source turns a row into chunk text and scope."""

    def __init__(self, source):
        from relay_core.relay_core.doctype.relay_ai_knowledge_source.relay_ai_knowledge_source import content_fields
        self.meta = frappe.get_meta(source.reference_doctype)
        self.content = content_fields(source)
        self.business_field = source.business_field or None
        company = self.meta.get_field('company')
        self.company_field = 'company' if company and company.fieldtype == 'Link' and company.options == 'Company' else None
        self.business_doctype = self.meta.get_field(self.business_field).options if self.business_field else None
        self.fields = sorted({'name', *self.content, *filter(None, (self.business_field, self.company_field))})

    def text(self, row) -> str:
        """Labelled content values; empty for a business-tied row without a business, so it is never shared."""
        if self.business_field and not row.get(self.business_field):
            return ''
        return '\n'.join(f'{self.meta.get_label(field) if field != "name" else "Name"}: {row.get(field)}'
                         for field in self.content if row.get(field) not in (None, ''))

    def scope(self, row) -> dict:
        return dict(company=row.get(self.company_field) if self.company_field else None,
                    business_doctype=self.business_doctype,
                    business_name=row.get(self.business_field) if self.business_field else None)


def event_text(event: str) -> str:
    """The event title, description and the text of its files and links. Images are skipped: ingest calls no model."""
    from relay_core.ai.event_memory import MAX_FILES, attached_files, file_limit
    from relay_core.ai.event_sources import read_file, read_link
    doc = frappe.get_doc(EVENT, event)
    limit = file_limit()
    parts = [doc.title, doc.description]
    parts += [read_file(frappe.get_doc('File', row.name), limit).text for row in attached_files(event)[:MAX_FILES]]
    parts += [read_link(row, limit).text for row in doc.links]
    return '\n\n'.join(part.strip() for part in parts if part and part.strip())


def events_base() -> str:
    """The customer knowledge base that holds one source per Relay AI Event, created on first use."""
    name = frappe.db.get_value(BASE, {'is_events': 1})
    if name:
        return name
    doc = frappe.get_doc(dict(doctype=BASE, title='Events', audience='customer', enabled=1, is_events=1,
                              description='Owner business events: dates, offers, rules and how to take part.'))
    doc.flags.events_base = True
    doc.insert(ignore_permissions=True)
    return doc.name


def queue_event(event: str) -> None:
    """Create the event's source, or queue its re-chunk for the event's current inputs."""
    from relay_core.ai.event_memory import get_revision
    name = frappe.db.get_value(SOURCE, {'source_type': 'Event', 'event': event})
    if not name:
        title = frappe.db.get_value(EVENT, event, 'title') or event
        frappe.get_doc(dict(doctype=SOURCE, title=title[:140], knowledge_base=events_base(), source_type='Event',
                            event=event)).insert(ignore_permissions=True)
        return
    queue_sync(name, revision=get_revision(event))


def on_event_change(doc, method=None) -> None:
    """Relay AI Event hook. A deleted event takes its source and chunks along, even while AI is off."""
    if method == 'on_trash':
        for name in frappe.get_all(SOURCE, filters={'source_type': 'Event', 'event': doc.name}, pluck='name'):
            frappe.delete_doc(SOURCE, name, ignore_permissions=True)
    elif ai_features.is_enabled():
        queue_event(doc.name)
