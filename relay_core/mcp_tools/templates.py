"""WhatsApp message templates. Create, update and delete go to Meta at once; there is no local draft."""
from relay_core.mcp_tools.registry import CONFIRM, READ, SEND, WRITE, obj, tool
from relay_core.mcp_tools.send import CHANNEL

TEMPLATE_NAME = {'type': 'string', 'pattern': '^[a-z0-9_]{1,512}$', 'description': 'Lowercase letters, digits and _.'}
LANGUAGE = {'type': 'string', 'pattern': '^[a-z]{2,3}(_[A-Z]{2})?$', 'description': 'Meta language code, such as en or en_US.'}
COMPONENTS = {'type': 'array', 'minItems': 1, 'maxItems': 10, 'items': {'type': 'object'},
              'description': 'Meta template components: HEADER, BODY, FOOTER, BUTTONS.'}
TEMPLATE_FIELDS = {'channel': CHANNEL, 'name': TEMPLATE_NAME, 'language': LANGUAGE,
                   'category': {'type': 'string', 'enum': ['MARKETING', 'UTILITY', 'AUTHENTICATION']},
                   'parameter_format': {'type': 'string', 'enum': ['named', 'positional']}, 'components': COMPONENTS}


def execute(operation, channel, arguments):
    from relay_core.whatsapp import execute as whatsapp_execute
    return whatsapp_execute(operation, arguments, channel=channel)


@tool('templates_list', READ, obj({'channel': CHANNEL, 'status': {'type': 'string', 'enum': ['APPROVED', 'PENDING', 'REJECTED', 'PAUSED', 'DISABLED']}}), {
    'summary': 'List WhatsApp templates with their Meta approval status, quality and rejection reason.',
    'use_when': 'choosing a template to send, or checking if a submitted template was approved.',
    'avoid_when': 'you need a chat; templates are not messages.',
    'returns': '{data: [{id, name, language, category, status, quality_score, rejected_reason, components}], sync: {synced_at, '
               'templates (count of the last sync), syncing}}. A list older than a minute starts a background sync.',
    'errors': '"Not permitted" without a Relay role.'})
def templates_list(channel=None, status=None):
    from relay_core.whatsapp_templates import directory
    page = directory(channel)
    if status:
        page['data'] = [row for row in page['data'] if row.get('status') == status]
    return page


@tool('templates_create', SEND, obj(TEMPLATE_FIELDS, ('channel', 'name', 'language', 'category', 'components')), {
    'summary': "Create a WhatsApp template on the channel's WhatsApp Business Account. It is submitted to Meta for review at once.",
    'use_when': 'the user approved the final text and wants a new template.',
    'avoid_when': 'you only want a draft; there is none, so show the text to the user first.',
    'returns': '{id, status: PENDING, category}. The template shows in templates_list after the next sync, about a minute later.',
    'errors': '"Hub rejected this operation: <Meta reason>" for invalid components; "Not permitted" without template write access.'})
def templates_create(channel, name, language, category, components, parameter_format='positional'):
    return execute('templates.create', channel, {'name': name, 'language': language, 'category': category,
                                                 'parameter_format': parameter_format, 'components': components})


@tool('templates_update', SEND, obj({'channel': CHANNEL, 'id': {'type': 'string', 'pattern': '^[0-9]{1,100}$'},
                                     'components': COMPONENTS, 'category': TEMPLATE_FIELDS['category']}, ('channel', 'id', 'components')), {
    'summary': 'Change the components of an existing template. Meta reviews it again.',
    'use_when': 'the user wants to fix a rejected or old template.',
    'avoid_when': 'the template is new; use templates_create.',
    'returns': "Meta's update result.",
    'errors': '"Hub rejected this operation: <Meta reason>"; Meta limits how often an approved template can change.'})
def templates_update(channel, id, components, category=None):
    return execute('templates.update', channel, {'id': id, 'components': components, **({'category': category} if category else {})})


@tool('templates_delete', SEND, obj({'channel': CHANNEL, 'name': TEMPLATE_NAME, 'id': {'type': 'string', 'pattern': '^[0-9]{1,100}$'},
                                     'confirm': CONFIRM}, ('channel', 'name', 'confirm')), {
    'summary': 'Delete a template from Meta. Without id every language of that name is deleted.',
    'use_when': 'the user explicitly asked to delete this template.',
    'avoid_when': 'a running campaign uses it.',
    'returns': "Meta's delete result.",
    'errors': '"arguments.confirm must be true"; "Hub rejected this operation".'})
def templates_delete(channel, name, confirm, id=None):
    return execute('templates.delete', channel, {'name': name, **({'id': id} if id else {})})


@tool('templates_media_upload', WRITE, obj({'channel': CHANNEL, 'media_type': {'type': 'string', 'enum': ['image', 'video', 'document']},
                                            'filename': {'type': 'string', 'minLength': 1, 'maxLength': 240},
                                            'content_base64': {'type': 'string', 'minLength': 1}},
                                           ('channel', 'media_type', 'filename', 'content_base64')), {
    'summary': 'Upload a header image, video or document for a template or template send. Requests up to 7 MB.',
    'use_when': 'a template has a media header.',
    'avoid_when': 'the file is reachable by HTTPS; chat_send_template takes header_media_url.',
    'returns': '{id: media handle for the header component}.',
    'errors': '"This file type is not accepted for this <kind> header"; "The file must be at most <size>".'}, large=True)
def templates_media_upload(channel, media_type, filename, content_base64):
    from relay_core.template_media import upload
    return upload(channel, media_type, filename, content_base64)
