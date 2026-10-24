"""Scalar placeholders only; HTML is generated exclusively from escaped text."""
from html import escape, unescape
from string import Formatter


def render_text(template, values, *, limit=100000):
    if not isinstance(template, str):
        raise ValueError('Provide template text')
    parts = []
    # Frappe sanitizes persisted text fields. Decode the template once before
    # substitution; business values are already plain text and must stay intact.
    for literal, field, spec, conversion in Formatter().parse(unescape(template)):
        parts.append(literal)
        if field is not None:
            if field not in values or spec or conversion:
                raise ValueError('Use only declared scalar template fields')
            parts.append(str(values[field]))
    result = ''.join(parts)
    if not result.strip() or len(result) > limit:
        raise ValueError('Rendered template is empty or too long')
    return result


def render(subject, body, values, signature=''):
    subject = render_text(subject, values, limit=998)
    if any(ord(char) < 32 for char in subject):
        raise ValueError('Email subject must be a single line')
    body = render_text(body, values)
    if not isinstance(signature, str) or len(signature) > 2000:
        raise ValueError('Signature exceeds 2000 characters')
    if signature:
        body += '\n\n' + unescape(signature)
    if len(body) > 100000:
        raise ValueError('Email body exceeds 100000 characters')
    html = '<div>' + escape(body).replace('\n', '<br>') + '</div>'
    if len(html.encode()) > 200000:
        raise ValueError('Email HTML exceeds 200000 bytes')
    return {'subject': subject, 'body': body, 'html': html}
