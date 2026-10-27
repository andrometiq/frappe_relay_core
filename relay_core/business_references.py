"""Relay history never owns the lifecycle of referenced documents.

Delete link checks skip Relay DocTypes through `ignore_links_on_delete`. Cancel link checks need
no hook: they block only on submitted rows, and no Relay DocType is submittable."""
import json
from pathlib import Path


RELAY_DOCTYPES = tuple(sorted(
    json.loads(path.read_text())['name']
    for path in (Path(__file__).parent / 'relay_core' / 'doctype').glob('*/*.json')
))

