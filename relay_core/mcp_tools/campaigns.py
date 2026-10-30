"""Bulk WhatsApp campaigns. Creating never sends; start, schedule, resume and retry need confirm."""
from relay_core.mcp_tools.registry import CONFIRM, CURSOR, NAME_FIELD, READ, SEND, WRITE, ToolError, obj, tool
from relay_core.mcp_tools.send import CHANNEL

ROWS = {'type': 'array', 'items': {'type': 'object'}, 'minItems': 1, 'maxItems': 5000,
        'description': 'One object per recipient: column -> value, with a phone column and the template fields.'}
RECIPIENT_STATUS = {'type': 'string', 'enum': ['Pending', 'Skipped', 'Queued', 'Sent', 'Delivered', 'Read', 'Failed', 'Uncertain',
                                               'Cancelled']}
ACTIONS = ('start', 'schedule', 'unschedule', 'pause', 'resume', 'cancel')
CONFIRMED = ('start', 'schedule', 'resume')
COUNTED = ('start', 'schedule')


@tool('campaigns_list', READ, obj({'query': {'type': 'string', 'maxLength': 140}, 'after': CURSOR,
                                   'status': {'type': 'string', 'enum': ['Draft', 'Scheduled', 'Running', 'Paused', 'Cancelling',
                                                                         'Completed', 'Cancelled']}}), {
    'summary': 'List campaigns with status and counts, 30 per page. Communication managers only.',
    'use_when': 'finding a campaign by title or status.',
    'avoid_when': 'you know the campaign name; use campaigns_read.',
    'returns': '{items: [{name, title, status, template_name, total_count, sent_count, replied_count}], next}.',
    'errors': '"Not permitted" for users without the manager role.'})
def campaigns_list(query='', after=None, status=None):
    from relay_core.campaigns import directory
    return directory(after=after, query=query, status=status)


@tool('campaigns_read', READ, obj({'name': NAME_FIELD, 'after': {'type': 'integer', 'minimum': 0}, 'status': RECIPIENT_STATUS}, ('name',)), {
    'summary': "Read one campaign's status, counts, issues and a page of 50 recipients.",
    'use_when': 'following a running campaign or checking its results.',
    'avoid_when': 'you are about to start it; use campaigns_validate.',
    'returns': '{name, status, counts: {total, skipped, queued, sent, delivered, read, failed, replied}, issues, recipients, next}.',
    'errors': '"Not found" for an unknown name; "This is not a WhatsApp bulk campaign".'})
def campaigns_read(name, after=None, status=None):
    from relay_core.bulk_campaigns import read
    return read(name, after=after, status=status)


@tool('campaigns_create', WRITE, obj({'title': {'type': 'string', 'minLength': 3, 'maxLength': 100}, 'channel': CHANNEL, 'rows': ROWS,
                                      'template_name': NAME_FIELD, 'language': NAME_FIELD,
                                      'message': {'type': 'object', 'description': 'Instead of a template: {kind: text, body} or '
                                                  '{kind: photo|video|document, caption?}; text and media reach only numbers inside '
                                                  'the 24-hour window.'},
                                      'mapping': {'type': 'object', 'description': 'Optional {phone: column, fields: {template '
                                                  'field: column}, fixed: {field: value}}. Without it the phone column is found '
                                                  'by name (phone, mobile, whatsapp, number) and template values by column name '
                                                  'or left to right.'}, 'reply_window_hours': {'type': 'integer', 'minimum': 1, 'maximum': 720}},
                                     ('title', 'channel', 'rows')), {
    'summary': 'Create a Draft campaign from up to 5000 rows with an approved template (or a text/media message). It never sends.',
    'use_when': 'the user wants to message many numbers.',
    'avoid_when': 'you message one person; use chat_send_template.',
    'returns': 'the campaign as campaigns_read returns it, status Draft. Its name is the title. Counts fill in a moment later; '
               'use campaigns_validate for the recipient count.',
    'errors': '"A campaign with this title already exists"; "Template is not approved"; mapping problems name the column.'})
def campaigns_create(title, channel, rows, template_name=None, language=None, message=None, mapping=None, reply_window_hours=72):
    from relay_core.bulk_campaigns import create_with_rows
    return create_with_rows(title, rows, message=message, template_name=template_name, language=language, mapping=mapping,
                            start=0, channel=channel, reply_window_hours=reply_window_hours)


@tool('campaigns_append', WRITE, obj({'name': NAME_FIELD, 'rows': ROWS}, ('name', 'rows')), {
    'summary': 'Add up to 5000 more rows to a Draft campaign made with campaigns_create.',
    'use_when': 'the audience has more than 5000 rows.',
    'avoid_when': 'the campaign is not Draft.',
    'returns': 'the campaign as campaigns_read returns it.',
    'errors': '"Campaign is Running"; "A campaign supports at most <n> rows".'})
def campaigns_append(name, rows):
    from relay_core.bulk_campaigns import append_rows
    return append_rows(name, rows)


@tool('campaigns_validate', READ, obj({'name': NAME_FIELD}, ('name',)), {
    'summary': 'Check a campaign before sending: how many recipients will be sent, skipped rows and their reasons, and '
               'for text or media how many numbers are inside the 24-hour window.',
    'use_when': 'always right before campaigns_control start; show the result to the user.',
    'avoid_when': 'the campaign is already running; use campaigns_read.',
    'returns': '{name, status, ready, recipients (pass as expected_recipients), skipped, issues, error_rows, window}.',
    'errors': '"Not found"; "Not permitted" for non-managers.'})
def campaigns_validate(name):
    from relay_core.bulk_campaigns import read, window
    campaign = read(name)
    counts = campaign['counts']
    recipients = counts['total'] - counts['skipped']
    open_window = window(name) if campaign['operation'] != 'templates.send' else None
    return {'name': campaign['name'], 'status': campaign['status'], 'recipients': recipients, 'skipped': counts['skipped'],
            'ready': bool(campaign['validated'] and recipients and not campaign['last_error']), 'issues': campaign['issues'],
            'error_rows': campaign['error_rows'], 'window': open_window, 'last_error': campaign['last_error']}


@tool('campaigns_control', SEND, obj({'name': NAME_FIELD, 'action': {'type': 'string', 'enum': list(ACTIONS)},
                                      'scheduled_at': {'type': 'string', 'maxLength': 40}, 'confirm': CONFIRM,
                                      'expected_recipients': {'type': 'integer', 'minimum': 1}}, ('name', 'action')), {
    'summary': 'Start, schedule, unschedule, pause, resume or cancel a campaign. Start and schedule send to real people.',
    'use_when': 'the user agreed to the count from campaigns_validate. start/schedule need confirm: true and '
                'expected_recipients; resume needs confirm: true.',
    'avoid_when': 'you have not run campaigns_validate just before.',
    'returns': 'the campaign as campaigns_read returns it.',
    'errors': '"Recipient count changed" when expected_recipients differs; "Campaign is <status>" for a wrong transition; '
              '"Validate recipients before sending".'})
def campaigns_control(name, action, scheduled_at=None, confirm=None, expected_recipients=None):
    from relay_core.bulk_campaigns import control
    if action in CONFIRMED and confirm is not True:
        raise ToolError(f'{action} sends to real people: pass confirm: true after the user agreed')
    if action in COUNTED:
        recipients = campaigns_validate(name)['recipients']
        if expected_recipients != recipients:
            raise ToolError(f'Recipient count changed: the campaign now has {recipients} recipients, not '
                            f'{expected_recipients}. Run campaigns_validate and confirm again.')
    return control(name, action, scheduled_at=scheduled_at)


@tool('campaigns_retry_failed', SEND, obj({'name': NAME_FIELD, 'confirm': CONFIRM}, ('name', 'confirm')), {
    'summary': 'Send the failed rows of a Completed campaign again. A repeat call changes nothing.',
    'use_when': 'campaigns_read shows failed rows and the user wants them sent again.',
    'avoid_when': 'the campaign is still running.',
    'returns': 'the campaign as campaigns_read returns it.',
    'errors': '"arguments.confirm must be true".'})
def campaigns_retry_failed(name, confirm):
    from relay_core.bulk_campaigns import retry_failed
    return retry_failed(name)
