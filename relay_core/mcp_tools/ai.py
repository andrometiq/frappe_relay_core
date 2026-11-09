"""The site's own AI setup: events, knowledge and skills, saved through the same APIs and checks as the AI screens.

Events and knowledge work while the Enable AI features switch is off: external agents use them too. Skills need the
switch, as their screen does. Writes need write access to the record type, as on the screens."""
import json
from functools import wraps

from relay_core.mcp_tools.registry import CONFIRM, CURSOR, FLAG, NAME_FIELD, READ, WRITE, ToolError, obj, tool
from relay_core.permissions import permitted_document

EVENT, SKILL = 'Relay AI Event', 'Relay AI Skill'
AI_OFF = ('AI features are turned off. Ask a System Manager to turn on Enable AI features in Relay Settings (Features), '
          'then retry.')
MEMORY_OFF = 'AI features are off, so the Relay AI does not read events into memory. The event text is still in use.'
LIVE = 'This makes a live skill that answers customers; pass confirm: true after the user agreed.'
DATE = {'type': 'string', 'pattern': '^[0-9]{4}-[0-9]{2}-[0-9]{2}$', 'description': 'YYYY-MM-DD; empty to clear.'}
TEXT = {'type': 'string', 'maxLength': 8000}
PAGE = obj({'after': CURSOR})
NAMED = obj({'name': NAME_FIELD}, ('name',))
EVENT_VALUES = obj({'title': NAME_FIELD, 'enabled': FLAG, 'company': {'type': 'string', 'maxLength': 140},
                    'description': {'type': 'string', 'maxLength': 10000}, 'event_starts_on': DATE, 'event_ends_on': DATE,
                    'available_from': DATE, 'available_to': DATE,
                    'audience': {'type': 'array', 'items': NAME_FIELD, 'minItems': 1, 'maxItems': 20}}, ('audience',))
KNOWLEDGE_VALUES = obj({'title': NAME_FIELD, 'enabled': FLAG, 'company': {'type': 'string', 'maxLength': 140},
                        'business_doctype': {'type': 'string', 'maxLength': 140}, 'instructions': TEXT | {'minLength': 1}})
SKILL_VALUES = obj({
    'title': NAME_FIELD, 'enabled': FLAG, 'channel': {'type': 'string', 'maxLength': 140}, 'business_doctype': NAME_FIELD,
    'ai_model': {'type': 'string', 'maxLength': 140}, 'run_as_user': {'type': 'string', 'maxLength': 140},
    'handoff_owner': {'type': 'string', 'maxLength': 140},
    'mode': {'type': 'string', 'enum': ['Shadow', 'Automatic'], 'description': 'Shadow drafts only; Automatic is Live.'},
    'daily_limit': {'type': 'integer', 'minimum': 1, 'maximum': 1000}, 'daily_spend_cap_usd': {'type': 'number', 'minimum': 0},
    'target': {'type': 'string', 'maxLength': 2000}, 'instructions': TEXT, 'reply_style': {'type': 'string', 'maxLength': 2000},
    'exact_trigger': {'type': 'string', 'maxLength': 140},
    'search_confirmation': {'type': 'string', 'enum': ['Always', 'When required']},
    'execution_policy': {'type': 'string', 'enum': ['Ticket only', 'Execute']},
    'max_tool_calls': {'type': 'integer', 'minimum': 1, 'maximum': 6, 'description': 'Tool calls per reply; 4 by default.'},
    'memory_enabled': FLAG,
    'allowed_tools': {'type': 'array', 'maxItems': 12, 'items': obj({'capability': NAME_FIELD}, ('capability',)),
                      'description': 'Read capabilities from skills_options kind report.'},
    'allowed_actions': {'type': 'array', 'maxItems': 4, 'items': obj({'action': NAME_FIELD, 'doctype': NAME_FIELD,
                                                                      'fields': {'type': 'array', 'items': NAME_FIELD, 'maxItems': 20}},
                                                                     ('action',)),
                        'description': 'Ordered actions from skills_options kind action; only with execution_policy Execute.'}})
SKILL_LISTS = ('allowed_tools', 'allowed_actions')
OPTION_KINDS = ('business_doctype', 'channel', 'model', 'user', 'report', 'action', 'draft_doctype', 'draft_field', 'company_record')


def ai_tool(name, safety, schema, doc, **options):
    """Register a skills tool that refuses with AI_OFF while the site's AI switch is off."""
    def register(handler):
        @wraps(handler)
        def guarded(**arguments):
            from relay_core import ai_features
            if not ai_features.is_enabled():
                raise ToolError(AI_OFF)
            return handler(**arguments)
        tool(name, safety, schema, doc, **options)(guarded)
        return handler
    return register


def record(doctype, name, fields):
    doc = permitted_document(doctype, name)
    return {'name': doc.name, **{field: doc.get(field) for field in fields}}


def require_key(name, request_key):
    if not name and not request_key:
        raise ToolError('request_key is required to create; reuse it to retry without a second record')


def skill_row(row):
    """A skill with its JSON lists as arrays."""
    return {**row, **{field: json.loads(row.get(field) or '[]') for field in SKILL_LISTS}}


def skill_values(values):
    """MCP skill values with the lists as the JSON text the Skills screen sends."""
    return {**values, **{field: json.dumps(values[field]) for field in SKILL_LISTS if field in values}}


@tool('events_list', READ, PAGE, {
    'summary': 'List the business events (offers, seasons, dated facts), 30 per page. They work while AI features are off.',
    'use_when': 'the user talks about an event, offer or campaign; check whether it exists before events_save.',
    'avoid_when': 'you know the event name; use events_read.',
    'returns': '{items: [{name, title, enabled, company, description, event_starts_on, event_ends_on, available_from, '
               'available_to, memory_status, audience: [business type]}], next}.',
    'errors': '"Not permitted" without read access to events.'})
def events_list(after=None):
    from relay_core.ai import events
    return events.directory(after)


@tool('events_read', READ, NAMED, {
    'summary': 'Read one event with its audience, links and attached files.',
    'use_when': 'before you change an event or add sources to it.',
    'avoid_when': 'you need the built AI memory; use events_status.',
    'returns': '{name, title, enabled, company, description, dates, memory_status, audience, links: [{url, note}], '
               'files: [{name, file_name, file_size}]}.',
    'errors': '"Not found"; "Not permitted".'})
def events_read(name):
    from relay_core.ai import events
    return events.read(name)


@tool('events_save', WRITE, obj({'values': EVENT_VALUES, 'name': NAME_FIELD}, ('values',)), {
    'summary': 'Create or change a business event. reply_context and the Relay AI use it for contacts of the audience '
               'business types while it is enabled and inside available_from to available_to. With AI features on, saving '
               'rebuilds the event memory.',
    'use_when': 'the user describes an event, offer or season the AI must know; without name it creates one with title, '
                'description and audience.',
    'avoid_when': 'the text is a standing rule for every reply; use knowledge_save.',
    'returns': '{name}. With AI features on, follow the memory build with events_status.',
    'errors': '"Choose 1–20 audience business types" (audience replaces the saved list; copy it from events_read); '
              '"Enable these contact types first: X"; "The event ends before it starts"; "Invalid event fields".'},
    once=True)
def events_save(values, name=None, request_key=None):
    from relay_core.ai import events
    require_key(name, request_key)
    return events.save(values, name)


@tool('events_attach', WRITE, obj({'name': NAME_FIELD, 'url': {'type': 'string', 'maxLength': 1000},
                                      'note': {'type': 'string', 'maxLength': 140},
                                      'filename': {'type': 'string', 'minLength': 1, 'maxLength': 120},
                                      'content_base64': {'type': 'string', 'minLength': 1}}, ('name', 'request_key')), {
    'summary': 'Add one link or one file (txt, md, csv, json, html, pdf, docx, jpg, png or webp) to an event. With AI '
               'features on, the Relay AI reads it into the event memory. At most 10 links and 10 files; a file within the '
               'Relay Settings AI file size (4 MB by default) and a request of at most 7 MB.',
    'use_when': 'the user gives a catalog, price list, poster or web page for an event.',
    'avoid_when': 'the text fits the event description; use events_save.',
    'returns': 'the event as events_read returns it.',
    'errors': '"Give either a link or a file"; "Use an http or https address"; "Add at most 10 links"; "The file must be at '
              'most N MB"; "Invalid file data"; "Attach one of these file types"; "The PDF could not be read". Files and '
              'links need an event memory model in Relay Settings, else events_status shows Failed.'}, large=True, once=True)
def events_attach(name, request_key, url=None, note=None, filename=None, content_base64=None):
    from relay_core.ai import events
    return events.attach(name, url=url, note=note, filename=filename, content_base64=content_base64)


@tool('events_status', READ, NAMED, {
    'summary': 'Read the memory build of an event: its state, the published memory text the AI uses and the sources read.',
    'use_when': 'after events_save or events_attach, to check what the AI will know.',
    'avoid_when': 'you need the event fields; use events_read.',
    'returns': '{memory_status (Pending, Building, Ready, Partial or Failed), memory_built_at, memory_error, memory, '
               'memory_revision, memory_build, sources: [{id, kind, label, status, reason}]}. While AI features are off: '
               '{name, memory_status: "AI off", note}.',
    'errors': '"Not found"; "Not permitted".'})
def events_status(name):
    from relay_core import ai_features
    if not ai_features.is_enabled():
        return {**record(EVENT, name, ()), 'memory_status': 'AI off', 'note': MEMORY_OFF}
    status = record(EVENT, name, ('memory_status', 'memory_built_at', 'memory_error', 'memory', 'memory_revision',
                                  'memory_build'))
    build = permitted_document('Relay AI Event Build', status['memory_build']) if status['memory_build'] else None
    return {**status, 'sources': json.loads(build.sources or '[]') if build else []}


@tool('knowledge_list', READ, PAGE, {
    'summary': 'List the knowledge base: standing business rules that every reply of their scope follows, by you and by '
               'the Relay AI. They work while AI features are off. App and skill playbooks are managed in Desk and are not listed.',
    'use_when': 'before knowledge_save, to change an existing entry instead of adding a duplicate.',
    'avoid_when': 'you look for events; use events_list.',
    'returns': '{items: [{name, title, enabled, company, business_doctype, instructions}], next}.',
    'errors': '"Not permitted" without read access to knowledge.'})
def knowledge_list(after=None):
    from relay_core.ai import knowledge
    return knowledge.directory(after)


@tool('knowledge_read', READ, NAMED, {
    'summary': 'Read one knowledge entry.',
    'use_when': 'before you change it.',
    'avoid_when': 'you need all entries; use knowledge_list.',
    'returns': '{name, title, enabled, company, business_doctype, instructions}.',
    'errors': '"Not found"; "Not permitted".'})
def knowledge_read(name):
    from relay_core.ai.knowledge import DOCTYPE, FIELDS
    return record(DOCTYPE, name, FIELDS)


@tool('knowledge_save', WRITE, obj({'values': KNOWLEDGE_VALUES, 'name': NAME_FIELD}, ('values',)), {
    'summary': 'Create or change a standing instruction. Blank company and business_doctype apply to every reply. '
               'Keep entries short: more than 100 enabled entries, or more than 8000 characters for one reply, stop the AI.',
    'use_when': 'the user states a lasting business rule, policy or fact the AI must always follow.',
    'avoid_when': 'it is about one dated event; use events_save.',
    'returns': '{name}.',
    'errors': '"Use 1–8000 instruction characters"; "Edit this playbook in Relay AI Playbook" for an app or skill playbook; '
              '"Invalid knowledge fields"; "Not permitted".'}, once=True)
def knowledge_save(values, name=None, request_key=None):
    from relay_core.ai import knowledge
    require_key(name, request_key)
    return knowledge.save(values, name)


@ai_tool('skills_list', READ, PAGE, {
    'summary': 'List AI skills: what the Relay AI answers on which channel and business type, with its limits.',
    'use_when': 'before skills_save, to change an existing skill instead of adding a duplicate.',
    'avoid_when': 'you know the skill name; use skills_read.',
    'returns': '{items: [{name, sample_key, title, enabled, mode, channel, business_doctype, ..., allowed_tools, '
               'allowed_actions}], next}. Mode Automatic is Live in the UI.',
    'errors': 'AI features off; "Not permitted".'})
def skills_list(after=None):
    from relay_core.ai import configuration
    page = configuration.directory(after)
    return {**page, 'items': [skill_row(row) for row in page['items']]}


@ai_tool('skills_read', READ, NAMED, {
    'summary': 'Read one AI skill.',
    'use_when': 'before you change it.',
    'avoid_when': 'you need all skills; use skills_list.',
    'returns': 'the skill fields; allowed_tools and allowed_actions as arrays.',
    'errors': '"Not found"; "Not permitted".'})
def skills_read(name):
    from relay_core.ai.configuration import FIELDS
    return skill_row(record(SKILL, name, ('sample_key', *FIELDS)))


@ai_tool('skills_options', READ, obj({'kind': {'type': 'string', 'enum': list(OPTION_KINDS)},
                                      'query': {'type': 'string', 'maxLength': 80}, 'business_doctype': NAME_FIELD,
                                      'action': NAME_FIELD, 'doctype': NAME_FIELD, 'skill': NAME_FIELD}, ('kind',)), {
    'summary': 'The values a skill field accepts: business types, channels, AI models, users, read capabilities (report, '
               'needs business_doctype), actions, draft DocTypes (needs action) and draft fields (needs action and doctype).',
    'use_when': 'before skills_validate, to fill channel, ai_model, run_as_user, handoff_owner, allowed_tools and allowed_actions.',
    'avoid_when': 'you already have the values from skills_read.',
    'returns': '{items: [{value, label, ...}]}; model gives read_only: true when the user cannot read AI models.',
    'errors': '"Choose a registered draft action"; "Not permitted".'})
def skills_options(kind, query='', business_doctype=None, action=None, doctype=None, skill=None):
    if kind == 'channel':
        from relay_core.api import channel_options
        return {'items': [{'value': row.name, 'label': ' · '.join(filter(None, (row.channel, row.label, row.address))),
                           'enabled': row.enabled} for row in channel_options()['items']]}
    from relay_core.ai.configuration import editor_options
    return editor_options(kind, query=query, doctype=doctype, business_doctype=business_doctype, action=action, skill=skill)


@ai_tool('skills_validate', READ, obj({'values': SKILL_VALUES, 'name': NAME_FIELD}, ('values',)), {
    'summary': 'Check a skill with the same rules as the Skills screen, without saving it.',
    'use_when': 'before skills_save, and after a save to confirm the skill is complete.',
    'avoid_when': 'you need the saved skill; use skills_read.',
    'returns': '{valid, problems: [text]}.',
    'errors': '"Invalid skill fields"; "Not found" for an unknown name; "Not permitted".'})
def skills_validate(values, name=None):
    from relay_core.ai import configuration
    return configuration.validate_draft(skill_values(values), name)


@ai_tool('skills_save', WRITE, obj({'values': SKILL_VALUES, 'name': NAME_FIELD, 'confirm': CONFIRM}, ('values',)), {
    'summary': 'Create or change an AI skill through the Skills screen checks. A new skill is disabled and in Shadow mode '
               'unless values say otherwise. Shadow drafts replies for staff; enabled Automatic (Live) answers customers.',
    'use_when': 'skills_validate passed and the user wants the skill kept.',
    'avoid_when': 'you only want to check it; use skills_validate.',
    'returns': '{name}.',
    'errors': '"' + LIVE + '"; "Choose a channel and AI Model before enabling the event"; "Choose read capabilities for '
              'the skill business type"; "Ticket only events cannot declare actions"; "Invalid skill fields"; "Not permitted".'},
    once=True)
def skills_save(values, name=None, confirm=False, request_key=None):
    from relay_core.ai import configuration
    require_key(name, request_key)
    stored = permitted_document(SKILL, name) if name else None
    current = {'enabled': stored.enabled, 'mode': stored.mode} if stored else {'enabled': 0, 'mode': 'Shadow'}
    merged = {**current, **values}
    if merged['enabled'] and merged['mode'] == 'Automatic' and not confirm:
        raise ToolError(LIVE)
    return configuration.save(skill_values(values), name)
