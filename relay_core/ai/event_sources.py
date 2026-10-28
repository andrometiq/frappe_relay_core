"""Bounded reads of Relay AI Event sources: attached files and public links. Source text is untrusted data.

Links are fetched without cookies or credentials. Every hop of a redirect resolves its host again, refuses private,
loopback, link-local and metadata addresses (in test mode only loopback is allowed) and connects to that checked
address, so a second DNS answer cannot move the request elsewhere."""
import hashlib
import html
import http.client
import io
import ipaddress
import re
import socket
import ssl
import time
import zipfile
from dataclasses import asdict, dataclass, field
from urllib.parse import urljoin, urlsplit

from relay_core import test_mode

MB = 1024 * 1024
MAX_URL_LENGTH = 1000
MAX_REDIRECTS = 3
FETCH_TIMEOUT = 15
CHUNK = 64 * 1024
MAX_PDF_PAGES = 50
MAX_DOCX_XML = 20 * MB
REDIRECTS = (301, 302, 303, 307, 308)
HEADERS = {'User-Agent': 'RelayCore-EventMemory/1', 'Accept': 'text/html, text/plain, application/pdf;q=0.9, */*;q=0.1',
           'Accept-Encoding': 'identity'}

PDF = 'application/pdf'
DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
TEXT_TYPES = {'text/plain', 'text/markdown', 'text/csv', 'application/json'}
HTML_TYPES = {'text/html', 'application/xhtml+xml'}
IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/webp'}
EXTENSIONS = {'txt': 'text/plain', 'md': 'text/markdown', 'csv': 'text/csv', 'json': 'application/json',
              'html': 'text/html', 'htm': 'text/html', 'pdf': PDF, 'docx': DOCX, 'jpg': 'image/jpeg',
              'jpeg': 'image/jpeg', 'png': 'image/png', 'webp': 'image/webp'}


class SourceError(ValueError):
    """A source that cannot be read. The message is the reason kept on the build record."""


@dataclass
class Source:
    """One input of an event memory build. `status` is Read, Cut (text shortened to the budget) or Skipped."""
    id: str
    kind: str
    label: str
    status: str = 'Read'
    reason: str = ''
    file: str | None = None
    url: str | None = None
    final_url: str | None = None
    bytes: int = 0
    sha256: str = ''
    text: str = field(default='', repr=False)

    @property
    def manifest(self) -> dict:
        return {key: value for key, value in asdict(self).items() if key != 'text'}

    def skip(self, reason: str) -> None:
        self.status, self.reason, self.text = 'Skipped', reason, ''


def too_large(limit: int) -> str:
    return f'Larger than the {limit / MB:g} MB limit'


def check_url(url: str):
    """The parts of an http or https URL without user name or password."""
    parts = urlsplit(url) if isinstance(url, str) else None
    if not parts or parts.scheme not in ('http', 'https') or not parts.hostname or len(url) > MAX_URL_LENGTH:
        raise SourceError('Use an http or https address')
    if parts.username or parts.password:
        raise SourceError('Remove the user name and password from the address')
    try:
        parts.port
    except ValueError:
        raise SourceError('The address has an invalid port') from None
    return parts


def resolve(parts, url: str) -> str:
    """One checked IP address of the URL's host."""
    try:
        test_mode.ensure_allowed(url)
    except test_mode.TestModeBlocked:
        raise SourceError('Test mode is on: only local addresses are read') from None
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == 'https' else 80),
                                   type=socket.SOCK_STREAM)
    except OSError:
        raise SourceError('The host name does not resolve') from None
    local = test_mode.is_enabled()
    addresses = sorted({info[4][0].split('%')[0] for info in infos})
    for value in addresses:
        address = ipaddress.ip_address(value)
        address = getattr(address, 'ipv4_mapped', None) or address
        if address.is_multicast or not (address.is_loopback if local else address.is_global):
            raise SourceError('The address is private or reserved')
    if not addresses:
        raise SourceError('The host name does not resolve')
    return addresses[0]


class PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, port, address, timeout):
        super().__init__(host, port, timeout=timeout)
        self.address = address

    def connect(self):
        self.sock = socket.create_connection((self.address, self.port), self.timeout)


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, port, address, timeout):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def request(url: str, limit: int, deadline: float):
    """(status, headers, body) of one GET to a checked address; the body is at most `limit` bytes."""
    parts = check_url(url)
    address = resolve(parts, url)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SourceError('The page took too long')
    connection_class = PinnedHTTPSConnection if parts.scheme == 'https' else PinnedHTTPConnection
    connection = connection_class(parts.hostname, parts.port, address, remaining)
    try:
        connection.request('GET', (parts.path or '/') + (f'?{parts.query}' if parts.query else ''), headers=HEADERS)
        response = connection.getresponse()
        if response.status in REDIRECTS:
            return response.status, response.headers, b''
        if (response.headers.get('Content-Encoding') or 'identity').lower() != 'identity':
            raise SourceError('Compressed pages are not read')
        return response.status, response.headers, read_limited(response, limit, deadline)
    except (OSError, http.client.HTTPException):
        raise SourceError('The page could not be read') from None
    finally:
        connection.close()


def read_limited(response, limit: int, deadline: float) -> bytes:
    body = bytearray()
    while chunk := response.read(CHUNK):
        body += chunk
        if len(body) > limit:
            raise SourceError(too_large(limit))
        if time.monotonic() > deadline:
            raise SourceError('The page took too long')
    return bytes(body)


def fetch(url: str, limit: int) -> tuple[str, str, bytes]:
    """(final URL, content type, body) of a public page, following at most 3 checked redirects."""
    deadline = time.monotonic() + FETCH_TIMEOUT
    for _ in range(MAX_REDIRECTS + 1):
        status, headers, body = request(url, limit, deadline)
        if status in REDIRECTS:
            if not headers.get('Location'):
                raise SourceError('The page redirects without a location')
            url = urljoin(url, headers['Location'])
            continue
        if status != 200:
            raise SourceError(f'The page answered HTTP {status}')
        return url, headers.get_content_type(), body
    raise SourceError('The page redirects too many times')


def mime_of(name: str, declared: str | None = None) -> str | None:
    return EXTENSIONS.get((name or '').rsplit('.', 1)[-1].lower()) or declared


def clean(text: str) -> str:
    return re.sub(r'\n\s*\n+', '\n\n', re.sub(r'[ \t\r\f\v]+', ' ', text)).strip()


def html_text(raw: bytes) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(raw, 'html.parser')
    for tag in soup(['script', 'style', 'noscript', 'template']):
        tag.decompose()
    return soup.get_text('\n')


def pdf_text(raw: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(raw))
    if reader.is_encrypted:
        raise SourceError('The PDF is password protected')
    if len(reader.pages) > MAX_PDF_PAGES:
        raise SourceError(f'The PDF has more than {MAX_PDF_PAGES} pages')
    return '\n'.join(page.extract_text() or '' for page in reader.pages)


def docx_text(raw: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if archive.getinfo('word/document.xml').file_size > MAX_DOCX_XML:
            raise SourceError('The document is too large to read')
        xml = archive.read('word/document.xml').decode('utf-8', errors='replace')
    return html.unescape(re.sub(r'<[^>]+>', '', re.sub(r'</w:p>|<w:br/>|<w:tab/>', '\n', xml)))


def extract(raw: bytes, mime: str | None, describe=None) -> str:
    """Plain text of a file or page body. `describe(raw, mime)` reads an image; without it images are skipped."""
    if mime in IMAGE_TYPES:
        if not describe:
            raise SourceError('Images need an event memory model with vision support')
        readers = {mime: lambda body: describe(body, mime)}
    else:
        readers = {**dict.fromkeys(TEXT_TYPES, lambda body: body.decode('utf-8', errors='replace')),
                   **dict.fromkeys(HTML_TYPES, html_text), PDF: pdf_text, DOCX: docx_text}
    if mime not in readers:
        raise SourceError('This file type is not read')
    try:
        text = clean(readers[mime](raw))
    except SourceError:
        raise
    except Exception:
        raise SourceError('The file could not be read') from None
    if not text:
        raise SourceError('No readable text was found')
    return text


def fingerprint(source: Source, raw: bytes) -> None:
    source.bytes, source.sha256 = len(raw), hashlib.sha256(raw).hexdigest()


def read_file(file, limit: int, describe=None) -> Source:
    """A File attached to the event, read from this site only."""
    source = Source(id='file-' + file.name, kind='File', label=file.file_name or file.name, file=file.name)
    try:
        if not (file.file_url or '').startswith(('/files/', '/private/files/')):
            raise SourceError('Only files stored on this site are read')
        if (file.file_size or 0) > limit:
            raise SourceError(too_large(limit))
        raw = file.get_content()
        raw = raw.encode() if isinstance(raw, str) else raw
        if len(raw) > limit:
            raise SourceError(too_large(limit))
        fingerprint(source, raw)
        source.text = extract(raw, mime_of(file.file_name or file.file_url), describe)
    except SourceError as error:
        source.skip(str(error))
    return source


def read_link(row, limit: int, describe=None) -> Source:
    source = Source(id=f'link-{row.idx}', kind='Link', label=row.note or row.url, url=row.url)
    try:
        source.final_url, content_type, raw = fetch(row.url, limit)
        fingerprint(source, raw)
        source.text = extract(raw, content_type if content_type != 'application/octet-stream'
                              else mime_of(urlsplit(source.final_url).path), describe)
    except SourceError as error:
        source.skip(str(error))
    return source


def fit(sources: list[Source], budget: int) -> None:
    """Keep the total text within `budget` characters in source order, marking what was cut or skipped."""
    remaining = budget
    for source in sources:
        if source.status != 'Read':
            continue
        if remaining <= 0:
            source.skip(f'Over the input budget of {budget} characters')
        elif len(source.text) > remaining:
            source.text = source.text[:remaining]
            source.status, source.reason = 'Cut', f'Only the first {remaining} characters were read'
        remaining -= len(source.text)
