"""Relay history never owns the lifecycle of referenced documents."""
import json
from pathlib import Path


RELAY_DOCTYPES = tuple(sorted(
    json.loads(path.read_text())['name']
    for path in (Path(__file__).parent / 'relay_core' / 'doctype').glob('*/*.json')
))


def allow_cancel(doc, method=None):
    doc.ignore_linked_doctypes = list(dict.fromkeys(
        [*(doc.get('ignore_linked_doctypes') or ()), *RELAY_DOCTYPES]
    ))
