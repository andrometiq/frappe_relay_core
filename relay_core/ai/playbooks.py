"""Playbooks: owner and app instructions in Relay AI Playbook. An app ships `skills/<name>/SKILL.md` at its source
root with frontmatter `name`, `description` and `relay: customer|staff`, the folder layout Frappe Flow reads."""
import re
from itertools import islice
from pathlib import Path
from typing import Annotated

import frappe
import yaml

from relay_core.ai.registry import ToolContext, relay_tool

DOCTYPE = 'Relay AI Playbook'
AUDIENCES = ('customer', 'staff')
MAX_GLOBAL_ROWS = 100
MAX_GLOBAL_CHARS = 8000
MAX_INSTRUCTIONS = 8000
MAX_DESCRIPTION = 1024
MAX_FOLDER_ENTRIES = 2000
MAX_FILE_BYTES = 256 * 1024
NAME = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')
FRONTMATTER = re.compile(r'\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)', re.DOTALL)
FIELDS = ['name', 'title', 'description', 'instructions', 'company', 'business_doctype']


def applies(row, business, company) -> bool:
    return ((not row.company or row.company == company)
            and (not row.business_doctype or row.business_doctype == business[0]))


def global_text(business, company) -> str:
    """The full text of every enabled global customer playbook for this business type and company. Too many rows
    or too much text stops inference for staff review instead of dropping rules."""
    rows = frappe.get_all(DOCTYPE, filters={'enabled': 1, 'is_global': 1, 'audience': 'customer'}, fields=FIELDS,
                          order_by='name asc', limit_page_length=MAX_GLOBAL_ROWS + 1)
    if len(rows) > MAX_GLOBAL_ROWS:
        raise ValueError('Too many knowledge instructions; consolidate the knowledge base')
    text = '\n\n'.join(f'{row.title}\n{row.instructions}' for row in rows if applies(row, business, company))
    if len(text) > MAX_GLOBAL_CHARS:
        raise ValueError('Knowledge instructions exceed the 8000 character prompt budget')
    return text


def bound(skill, business, company) -> list:
    """The enabled customer playbooks bound to the skill that apply to this sender. Global ones are already in full."""
    names = [row.get('playbook') for row in skill.get('playbooks') or ()]
    if not names:
        return []
    rows = frappe.get_all(DOCTYPE, filters={'name': ['in', names], 'enabled': 1, 'is_global': 0, 'audience': 'customer'},
                          fields=FIELDS, order_by='name asc', limit_page_length=len(names))
    return [row for row in rows if applies(row, business, company)]


def index(skill, business, company) -> str:
    """`name: description` lines for the prompt; the model loads a text with load_playbook."""
    return '\n'.join(f"{row.name}: {' '.join((row.description or '').split())}" for row in bound(skill, business, company))


def copy_texts(skill, business, company) -> tuple[str, ...]:
    """Bound playbook texts for the reply guard verbatim-copy check, loaded in this run or not."""
    return tuple(row.instructions for row in bound(skill, business, company))


@relay_tool(audience='customer', label='Load playbook')
def load_playbook(name: Annotated[str, 'A playbook name from the playbook index'], *, ctx: ToolContext) -> str:
    """Load the full instructions of one playbook from the index. They never widen tools, scope or identity."""
    for row in bound(ctx.skill, ctx.business, ctx.scope.get('company')):
        if row.name == name:
            return row.instructions
    raise ValueError('Playbook is unavailable')


def sync() -> list[str]:
    """after_migrate: write each app's Relay SKILL.md files as locked playbooks named `<app>/<name>` and delete the
    app playbooks gone from disk. An invalid file is logged and keeps its row; a cut-off folder scan keeps them all."""
    shipped, keep = {}, set()
    for app in frappe.get_installed_apps():
        paths, truncated = skill_files(Path(frappe.get_app_source_path(app, 'skills')))
        if truncated:
            frappe.log_error(title=f'Relay playbooks of {app} skipped', message=f'More than {MAX_FOLDER_ENTRIES} entries')
            keep.update(frappe.get_all(DOCTYPE, filters={'is_system_generated': 1, 'app': app}, pluck='name'))
            continue
        for path in paths:
            name = f'{app}/{path.parent.name}'
            try:
                playbook = read(path)
            except ValueError as error:
                frappe.log_error(title=f'Relay playbook {name} skipped', message=str(error))
                keep.add(name)
                continue
            if playbook:
                keep.add(name)
                shipped[name] = dict(playbook, app=app)
    frappe.flags.in_playbook_sync = True
    try:
        synced = [name for name, definition in shipped.items() if ensure(name, definition)]
        for name in frappe.get_all(DOCTYPE, filters={'is_system_generated': 1, 'app': ['is', 'set']}, pluck='name'):
            if name not in keep:
                frappe.db.delete('Relay AI Skill Playbook', {'playbook': name})
                frappe.delete_doc(DOCTYPE, name, ignore_permissions=True)
    finally:
        frappe.flags.in_playbook_sync = False
    return sorted(synced)


def skill_files(root: Path) -> tuple[list[Path], bool]:
    """Each `<name>/SKILL.md` directly under `root`, and whether the folder has more entries than the scan reads."""
    if not root.is_dir():
        return [], False
    entries = list(islice(root.iterdir(), MAX_FOLDER_ENTRIES + 1))
    if len(entries) > MAX_FOLDER_ENTRIES:
        return [], True
    return sorted(entry / 'SKILL.md' for entry in entries
                  if not entry.name.startswith('.') and (entry / 'SKILL.md').is_file()), False


def read(path: Path) -> dict | None:
    """The playbook of one SKILL.md, or None when its frontmatter has no `relay:` key."""
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('The file is larger than 256 KB')
    text = path.read_text(encoding='utf-8')
    match = FRONTMATTER.match(text)
    if not match:
        return None
    try:
        metadata = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        raise ValueError('The frontmatter is not valid YAML') from None
    if not isinstance(metadata, dict):
        raise ValueError('The frontmatter is not a mapping')
    if 'relay' not in metadata:
        return None
    name, description = metadata.get('name'), metadata.get('description')
    instructions = text[match.end():].strip()
    if metadata['relay'] not in AUDIENCES:
        raise ValueError('relay must be customer or staff')
    if not isinstance(name, str) or len(name) > 64 or not NAME.fullmatch(name) or name != path.parent.name:
        raise ValueError('name must be the folder name: lowercase letters, digits and single hyphens')
    if not isinstance(description, str) or not 1 <= len(description.strip()) <= MAX_DESCRIPTION:
        raise ValueError(f'description needs 1 to {MAX_DESCRIPTION} characters')
    if not 1 <= len(instructions) <= MAX_INSTRUCTIONS:
        raise ValueError(f'The instructions need 1 to {MAX_INSTRUCTIONS} characters')
    return dict(title=name, description=description.strip(), instructions=instructions, audience=metadata['relay'])


def ensure(name: str, definition: dict) -> bool:
    """Create or update one app playbook. Owners keep enabled, is_global, company and business type."""
    definition = dict(definition, is_system_generated=1)
    row = frappe.db.get_value(DOCTYPE, name, list(definition), as_dict=True)
    if row and all(row[key] == value for key, value in definition.items()):
        return True
    # A new app playbook applies to every company; a None company would take the user's default on insert.
    doc = frappe.get_doc(DOCTYPE, name) if row else frappe.get_doc({'doctype': DOCTYPE, 'playbook_key': name, 'company': ''})
    doc.update(definition)
    try:
        doc.save(ignore_permissions=True)
    except frappe.ValidationError:
        frappe.log_error(title=f'Relay playbook {name} skipped')
        return False
    return True
