"""The one owner of knowledge chunk SQL: the FULLTEXT index, chunk writes and the scoped search. MariaDB only.

InnoDB FULLTEXT finds whole words in Tamil, Malayalam and Hindi (measured on MariaDB 11.8), but not a word inside a
longer inflected word, and it drops words under 3 characters. When it finds nothing, a LIKE match of the 3 longest
query words runs over at most 200 chunks of the same scope."""
import hashlib
import unicodedata

import frappe
from frappe.utils import now_datetime

CHUNK = 'Relay AI Knowledge Chunk'
TABLE = '`tabRelay AI Knowledge Chunk`'
FULLTEXT = 'relay_ai_chunk_content'
NAMES = 'RELAY-AIKC-.##########'
SCAN = 200
LIKE_WORDS = 3
COLUMNS = ('knowledge_base', 'source', 'chunk_index', 'content', 'content_hash', 'reference_doctype',
           'reference_name', 'company', 'business_doctype', 'business_name')
SCOPE = ("source IN %(sources)s AND (IFNULL(company, '') = '' OR company = %(company)s) "
         "AND (IFNULL(business_name, '') = '' OR (business_doctype = %(business_doctype)s "
         "AND business_name = %(business_name)s))")
MATCH = 'MATCH(content) AGAINST (%(query)s IN NATURAL LANGUAGE MODE)'


class Unsupported(RuntimeError):
    """This database has no FULLTEXT search for knowledge chunks."""


def is_supported() -> bool:
    return frappe.conf.db_type != 'postgres'


def install_indexes() -> None:
    """Lookup indexes and the FULLTEXT index, created only when absent. Postgres sites get no knowledge search."""
    if not is_supported():
        return
    frappe.db.add_index(CHUNK, ['knowledge_base', 'source'], 'relay_ai_chunk_base_source')
    frappe.db.add_index(CHUNK, ['source', 'reference_name'], 'relay_ai_chunk_reference')
    frappe.db.add_index(CHUNK, ['business_doctype', 'business_name'], 'relay_ai_chunk_business')
    if not frappe.db.sql(f'SHOW INDEX FROM {TABLE} WHERE Key_name = %s', FULLTEXT):
        frappe.db.sql(f'CREATE FULLTEXT INDEX {FULLTEXT} ON {TABLE} (content)')


def content_hash(*parts) -> str:
    return hashlib.sha256('\x1f'.join(str(part or '') for part in parts).encode()).hexdigest()


def delete(source: str, reference_names: list[str] | None = None) -> None:
    filters = {'source': source}
    if reference_names is not None:
        if not reference_names:
            return
        filters['reference_name'] = ['in', reference_names]
    frappe.db.delete(CHUNK, filters)


def insert(rows: list[dict]) -> None:
    """Rows hold COLUMNS; the caller commits."""
    if not rows:
        return
    from frappe.model.naming import make_autoname
    now, user = now_datetime(), frappe.session.user
    values = [(make_autoname(NAMES), now, now, user, user, *(row.get(column) for column in COLUMNS)) for row in rows]
    frappe.db.bulk_insert(CHUNK, ('name', 'creation', 'modified', 'owner', 'modified_by', *COLUMNS), values)


def indexed_hashes(source: str, reference_names: list[str] | None = None) -> dict[str, str]:
    """reference_name -> content_hash of a DocType source's rows, all of them or the given ones."""
    filters = {'source': source}
    if reference_names is not None:
        filters['reference_name'] = ['in', reference_names or ['']]
    rows = frappe.get_all(CHUNK, filters=filters, fields=['reference_name', 'content_hash'], distinct=True)
    return {row.reference_name: row.content_hash for row in rows}


def search(sources: list[str], query: str, company: str | None, business: tuple[str, str], limit: int) -> list[dict]:
    """The best chunks of `sources` for `query` that this company and business may see: name, source, content,
    business_name and score. Every value is a query parameter."""
    if not is_supported():
        raise Unsupported('Knowledge search needs MariaDB')
    values = dict(sources=tuple(sources), company=company, business_doctype=business[0], business_name=business[1],
                  query=query, limit=limit)
    rows = frappe.db.sql(f'SELECT name, source, content, business_name, {MATCH} AS score FROM {TABLE} '
                         f'WHERE {SCOPE} AND {MATCH} ORDER BY score DESC, name LIMIT %(limit)s', values, as_dict=True)
    return rows or search_like(values, like_words(query))


def search_like(values: dict, words: list[str]) -> list[dict]:
    """The fallback: chunks of the scope that contain the most query words, scanning at most SCAN chunks."""
    if not words:
        return []
    values = dict(values, **{f'word{index}': '%' + escape_like(word) + '%' for index, word in enumerate(words)})
    tests = [f'(content LIKE %(word{index})s)' for index in range(len(words))]
    return frappe.db.sql(f'SELECT name, source, content, business_name, {" + ".join(tests)} AS score '
                         f'FROM (SELECT name, source, content, business_name FROM {TABLE} WHERE {SCOPE} '
                         f'ORDER BY name LIMIT {SCAN}) scoped WHERE {" OR ".join(tests)} '
                         'ORDER BY score DESC, name LIMIT %(limit)s', values, as_dict=True)


def like_words(query: str) -> list[str]:
    """The longest distinct words of the query; vowel signs and viramas stay inside their word."""
    text = ''.join(char if char.isalnum() or unicodedata.category(char).startswith('M') else ' ' for char in query)
    words = sorted({word for word in text.split() if len(word) >= 2}, key=lambda word: (-len(word), word))
    return words[:LIKE_WORDS]


def escape_like(word: str) -> str:
    return word.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
