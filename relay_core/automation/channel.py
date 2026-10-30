"""Ordered channel admission, sharing the existing flow, skill and delivery journals."""
import json
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import frappe
from relay_core.business_access import document_name
from relay_core.permissions import require_access

STEP_FIELDS = ('step', 'enabled', 'ai_skill', 'team', 'user', 'ticket_rule', 'message', 'on_reply')
FIELDS = ('automation_enabled', 'timezone', 'open_time', 'close_time', 'working_days')
KINDS = ('Flow', 'AI skill', 'Assign', 'Ticket', 'Out of hours reply')
DAYS = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
DEFAULT_STEPS = [dict(step='Flow', enabled=1, on_reply='Stop'),
                 dict(step='AI skill', enabled=1, on_reply='Stop')]


def enabled(channel):
    return channel.get('automation_enabled') not in (0, '0', False)


def steps(channel):
    return [{key: row.get(key) for key in STEP_FIELDS} for row in channel.get('automation_steps') or []]


def clock(value):
    if isinstance(value, timedelta):
        return (datetime.min + value).time()
    return value if isinstance(value, time) else time.fromisoformat(str(value))


def working_days(value):
    return [day.strip() for day in (value or '').replace(',', '\n').splitlines() if day.strip()]


def outside_hours(channel, now=None):
    zone = ZoneInfo(channel.get('timezone') or 'UTC')
    local = (now or datetime.now(timezone.utc)).astimezone(zone)
    start, end = clock(channel.get('open_time')), clock(channel.get('close_time'))
    days = working_days(channel.get('working_days'))
    today = DAYS[local.weekday()]
    current = local.time().replace(tzinfo=None)
    if start < end:
        return not (today in days and start <= current < end)
    previous = DAYS[(local.weekday() - 1) % 7]
    return not (today in days and current >= start or previous in days and current < end)


def validate_assignment(team=None, user=None):
    if team is not None and team != "":
        document_name(team)
    from relay_core.teams import validate_agent
    if not (team or user):
        frappe.throw('Choose a team or user')
    if team:
        from relay_core import features
        features.require('teams')
        doc = frappe.get_doc('Relay Team', team)
        doc.check_permission('read')
    if user:
        validate_agent(user)
        if team and not any(row.user == user for row in doc.members):
            frappe.throw('The assigned user must belong to the team')


def assign_conversation(contact, team=None, user=None):
    from relay_core import features
    from relay_core.teams import assign
    if team:
        features.require('teams')
    return assign(contact, team, user)


def validate_skill(name, channel, business=None, *, check_read=True):
    document_name(name)
    skill = frappe.get_doc('Relay AI Skill', name)
    if check_read:
        skill.check_permission('read')
    if not skill.enabled or skill.channel != channel or business and skill.business_doctype != business:
        frappe.throw('Choose an enabled AI skill for this channel and business type')
    return skill


def validate(doc):
    rows = steps(doc)
    if len(rows) > 20:
        frappe.throw('Choose at most 20 automation steps')
    for row in rows:
        if row['step'] not in KINDS or row['on_reply'] not in ('Stop', 'Continue'):
            frappe.throw('Choose a supported step and Stop or Continue')
        if not enabled(doc) or not row['enabled']:
            continue
        if row['step'] == 'AI skill':
            if row['ai_skill']:
                validate_skill(row['ai_skill'], doc.name)
        elif row['step'] == 'Assign':
            validate_assignment(row['team'], row['user'])
        elif row['step'] == 'Ticket' and row['ticket_rule'] not in ('Create if not resolved', 'Always', 'Never'):
            frappe.throw('Choose a ticket rule')
        elif row['step'] == 'Out of hours reply':
            if not isinstance(row['message'], str) or not 1 <= len(row['message'].strip()) <= 2000:
                frappe.throw('Out of hours reply needs 1–2000 characters')
            try:
                ZoneInfo(doc.get('timezone') or 'UTC')
                start, end = clock(doc.get('open_time')), clock(doc.get('close_time'))
                days = working_days(doc.get('working_days'))
                if start == end or not days or set(days) - set(DAYS):
                    raise ValueError()
            except (ValueError, TypeError, ZoneInfoNotFoundError):
                frappe.throw('Choose a valid timezone, different opening and closing times, and working days')


@frappe.whitelist(methods=['GET'])
def read(channel):
    document_name(channel)
    require_access(manage=True)
    doc = frappe.get_doc('Relay Channel', channel)
    doc.check_permission('read')
    values = {key: doc.get(key) for key in FIELDS}
    values['automation_enabled'] = int(enabled(doc))
    for key in ('open_time', 'close_time'):
        if values[key] is not None and values[key] != '':
            values[key] = clock(values[key]).isoformat()
    return dict(name=doc.name, title=doc.title, channel=doc.channel, modified=str(doc.modified),
                **values, address=doc.get('address'), timezone_default='UTC', steps=steps(doc), defaults=DEFAULT_STEPS)


@frappe.whitelist(methods=['POST'])
def save(channel, values, modified):
    document_name(channel)
    require_access(manage=True)
    values = frappe.parse_json(values) if isinstance(values, str) else values
    if not isinstance(values, dict) or set(values) - {*FIELDS, 'steps'}:
        frappe.throw('Invalid channel automation fields')
    rows = values.get('steps', [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) or set(row) - set(STEP_FIELDS) for row in rows):
        frappe.throw('Invalid automation steps')
    for row in rows:
        if row.get('enabled') not in (0, 1, False, True):
            frappe.throw('Step enabled must be 0 or 1')
        if any(value is not None and not isinstance(value, str) for key, value in row.items() if key != 'enabled'):
            frappe.throw('Step fields must be text')
    doc = frappe.get_doc('Relay Channel', channel, for_update=True)
    doc.check_permission('read')
    if 'steps' in values:
        from relay_core import ai_features
        requested = [{key: row.get(key) for key in STEP_FIELDS} for row in rows if row.get('step') == 'AI skill']
        existing = [row for row in steps(doc) if row['step'] == 'AI skill']
        if requested != existing:
            ai_features.require()
    if str(doc.modified) != modified:
        frappe.throw('Channel changed. Reload before saving.')
    if 'automation_enabled' in values and values['automation_enabled'] not in (0, 1, False, True):
        frappe.throw('Enabled must be 0 or 1')
    doc.update({key: values[key] for key in FIELDS if key in values})
    if 'steps' in values:
        doc.set('automation_steps', rows)
    # Managers may edit only this allowlist, not channel transport configuration.
    doc.save(ignore_permissions=True)
    return read(channel)


@frappe.whitelist(methods=['GET'])
def references(kind, query=''):
    require_access(manage=True)
    if not isinstance(query, str) or len(query) > 80:
        frappe.throw('Invalid reference search')
    if kind == 'ai_skill':
        from relay_core import ai_features
        ai_features.require()
    if kind == 'user':
        from relay_core.teams import agents
        return [dict(value=row.name, label=row.full_name or row.name) for row in agents(query)]
    choices = {'channel': ('Relay Channel', 'title', {}), 'ai_skill': ('Relay AI Skill', 'title', {'enabled': 1}),
               'team': ('Relay Team', 'title', {}), 'contact': ('Relay Contact', 'display_name', {})}
    if kind not in choices:
        frappe.throw('Invalid automation reference')
    doctype, label, filters = choices[kind]
    pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    fields = ['name', label] + (['channel', 'address'] if kind == 'channel' else [])
    rows = frappe.get_list(doctype, filters=filters, or_filters=[[field, 'like', pattern] for field in fields],
                           fields=fields, order_by='name asc', page_length=30)
    if kind == 'channel':
        icons = {'WhatsApp': 'message-circle', 'Email': 'mail', 'Telegram': 'send'}
        return [dict(value=row.name, label=' · '.join(filter(None, [row.channel, row.get(label) or row.name,
                                                                  row.get('address')])),
                     icon=icons.get(row.channel, 'message-square')) for row in rows]
    return [dict(value=row.name, label=row.get(label) or row.name) for row in rows]


def decision(row, *, flow=False, ai=False, outside=False, claimed=False, resolved=False):
    """Shared by runtime and preview; deciding a step has no side effects."""
    if not row.get('enabled'):
        return False, 'Step disabled'
    kind = row['step']
    if claimed and kind in ('Flow', 'AI skill', 'Out of hours reply'):
        return False, 'An earlier step already handles the reply'
    if kind == 'Flow':
        return flow, 'Flow trigger matched' if flow else 'No flow trigger matched'
    if kind == 'AI skill':
        return ai, 'Selected skill will handle this message' if ai else 'AI disabled or skill does not match this business'
    if kind == 'Out of hours reply':
        return outside, 'Outside business hours' if outside else 'Within business hours'
    if kind == 'Ticket':
        rule = row.get('ticket_rule')
        ok = rule != 'Never' and (rule == 'Always' or not resolved)
        return ok, 'Update the conversation ticket' if ok else 'Ticket rule skipped'
    return True, 'Assign the conversation'


def evaluate(row, message, channel, *, claimed=False, resolved=False, preview=False):
    kind = row['step']
    if not row.get('enabled') or claimed and kind in ('Flow', 'AI skill', 'Out of hours reply'):
        return decision(row, claimed=claimed)
    from relay_core import features, ai_features
    from relay_core.flows.service import claims, matching
    flow = features.is_enabled('flows') and (bool(matching(message)) if preview else claims(message)) if kind == 'Flow' else False
    ai = False
    if kind == 'AI skill':
        ai = ai_available(message, row) if not preview else bool(frappe.conf.get('relay_automation_enabled') and ai_features.is_enabled())
    return decision(row, flow=flow, ai=ai if kind == 'AI skill' else False,
                    outside=outside_hours(channel) if kind == 'Out of hours reply' else False,
                    claimed=claimed, resolved=resolved)


def identity(message, channel):
    from relay_core.identity import authenticated_sender
    from relay_core.business_access import reference, candidates
    authenticated_sender(message, channel)
    business = reference(message)
    if not business or business not in candidates(message.relay_contact):
        raise ValueError('Business identity is missing or ambiguous')
    return business


def owns_reply(message):
    from relay_core import features
    from relay_core.flows.service import active, route
    if not features.is_enabled('flows'):
        return False
    key = route(message)
    return bool(active(key) or frappe.db.exists('Relay Flow Event', {'conversation_key': key, 'status': 'Pending'}))


def ai_available(message, row):
    from relay_core import ai_features
    if not (frappe.conf.get('relay_automation_enabled') and ai_features.is_enabled()):
        return False
    if message.get('message_type') not in ('text', '', None, 'photo', 'image', 'voice', 'audio'):
        return False
    if not row.get('ai_skill'):
        return True
    skill = frappe.get_doc('Relay AI Skill', row['ai_skill'])
    return bool(skill.enabled and skill.channel == message.channel and skill.business_doctype == message.get('business_doctype'))


def delivery_scope(run, message):
    from relay_core.automation.service import lock_contact, latest_message, message_hash
    from relay_core.ai.service import Superseded
    from relay_core.tickets import check_episode
    channel = frappe.get_doc('Relay Channel', message.channel)
    if not channel.enabled or not enabled(channel):
        raise Superseded('Channel automation is disabled')
    identity(message, channel)
    contact = lock_contact(message.relay_contact)
    try:
        check_episode(run)
    except ValueError as exc:
        raise Superseded(str(exc)) from exc
    if contact.automation_paused or int(contact.automation_generation or 0) != int(run.generation):
        raise Superseded('Conversation is owned by staff')
    if message_hash(message) != run.message_hash or not latest_message(message):
        raise Superseded('Message changed or was superseded')
    message.check_permission('read')
    return channel


def ticket_resolved(name):
    from relay_core.ticket_settings import is_closed
    return bool(name and is_closed(frappe.get_doc('Relay Ticket', name)))


def process(run):
    from relay_core.automation.queue import QUEUE
    from relay_core.automation.service import internal_save, outgoing_run, triage
    from relay_core.flows.service import create_event
    from relay_core.ai.tools import as_user
    from relay_core.ai.service import Superseded
    message = frappe.get_doc('Relay Message', run.message)
    state = json.loads(run.pipeline_state)
    try:
        with as_user(run.execution_user):
            rows = state['steps']
            while state['index'] < len(rows):
                channel = delivery_scope(run, message)
                row = rows[state['index']]
                kind = row['step']
                allowed, _ = (True, 'Resume delivery') if state.get('inflight') == state['index'] else evaluate(
                    row, message, channel, claimed=bool(state.get('responder')), resolved=ticket_resolved(run.ticket))
                if allowed:
                    if kind == 'Assign':
                        assign_conversation(message.relay_contact, row.get('team'), row.get('user'))
                    elif kind == 'Ticket':
                        from relay_core.flows.service import flow_ticket
                        flow_ticket(message, message.content or 'Conversation needs attention')
                    elif kind == 'Flow':
                        create_event(message)
                        state['responder'] = 'Flow'
                    elif kind == 'AI skill':
                        state['responder'], state['skill'] = 'AI skill', row.get('ai_skill')
                    else:
                        from relay_core.ai.service import send_reply
                        state['inflight'] = state['index']
                        run.pipeline_state = json.dumps(state)
                        internal_save(run)
                        token = outgoing_run.set(run.name)
                        try:
                            result = send_reply(message, row['message'])
                        finally:
                            outgoing_run.reset(token)
                        if result['status'] != 'Submitted':
                            if result['status'] == 'Rejected':
                                raise ValueError('Out of hours reply rejected')
                            return  # Recovery reuses the message-action key.
                        state['responder'] = kind
                state.pop('inflight', None)
                state['index'] += 1
                if allowed and row['on_reply'] == 'Stop':
                    state['index'] = len(rows)
                run.pipeline_state = json.dumps(state)
                internal_save(run)
                frappe.db.commit()
            if state.get('responder') == 'AI skill':
                delivery_scope(run, message)
                from relay_core.ai.service import select_skill
                if state.get('skill'):
                    from relay_core.ai.service import continue_search
                    if not continue_search(run, message):
                        select_skill(run, message, state['skill'])
                else:
                    run.stage = 'Matching'
                internal_save(run)
                frappe.enqueue('relay_core.automation.service.process', name=run.name, queue=QUEUE, enqueue_after_commit=True)
            else:
                run.status = 'Completed'
                internal_save(run)
            frappe.db.commit()
    except Superseded as error:
        frappe.db.rollback()
        run.reload()
        run.status, run.reason = 'Cancelled', str(error)
        internal_save(run)
        frappe.db.commit()
    except (ValueError, frappe.PermissionError, frappe.ValidationError):
        frappe.db.rollback()
        run.reload()
        triage(run, message, 'Channel automation requires review')
        frappe.db.commit()


@frappe.whitelist(methods=['GET'])
def dry_run(channel, text, contact=None):
    document_name(channel)
    require_access(manage=True)
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000:
        frappe.throw('Enter a message of 1–4000 characters')
    config = frappe.get_doc('Relay Channel', channel)
    config.check_permission('read')
    message = frappe._dict(direction='Incoming', content=text, message_type='text', channel=channel,
                          provider_context=json.dumps({'provider': config.channel}))
    trace = []
    if contact:
        from relay_core.permissions import readable_contact
        readable_contact(contact)
        sources = frappe.get_list('Relay Message', filters={'relay_contact': contact, 'channel': channel, 'direction': 'Incoming'},
                                  pluck='name', order_by='name desc', page_length=1)
        if not sources:
            return dict(trace=[dict(step='Pre-checks', runs=False, reason='No readable incoming conversation for this contact')])
        message = frappe.get_doc('Relay Message', sources[0])
        message.content, message.message_type = text, 'text'
        message.message_data = '{}'
        context = json.loads(message.provider_context or '{}')
        context.pop('original_message_type', None)
        message.provider_context = json.dumps(context)
    from relay_core.opt_out import is_keyword
    from relay_core.ai.matching import human_request
    reason = None
    if is_keyword(message):
        reason = 'Consent keyword: opt-out/opt-in takes precedence; no automatic reply'
    elif not config.enabled or not enabled(config):
        reason = 'Channel automation is disabled'
    elif contact:
        try:
            identity(message, config)
        except (ValueError, frappe.PermissionError):
            reason = 'Identity is missing or ambiguous'
        from relay_core.automation.service import staff_owned
        person = frappe.get_doc('Relay Contact', contact)
        if not reason and staff_owned(person, message=message):
            reason = 'Conversation is owned by staff'
    if not reason and human_request(text):
        reason = 'Sender requested a person; handoff before all steps'
    if reason:
        return dict(trace=[dict(step='Pre-checks', runs=False, reason=reason)])
    trace.append(dict(step='Pre-checks', runs=True, reason='Identity and ownership checked; a new message is assumed' if contact
                      else 'Preview only: identity, ownership and deduplication require a real incoming message'))
    if contact and owns_reply(message):
        return dict(trace=trace + [dict(step='Flow', runs=True, reason='Waiting flow owns follow-up replies')])
    from relay_core.ai.service import pending_search
    confirmation = contact and ai_available(message, {}) and pending_search(message, message.get('ticket'), lock=False)
    if confirmation and not steps(config):
        return dict(trace=trace + [dict(step='AI skill', runs=True, reason='Continue the search the customer confirmed; access is checked again')])
    claimed = False
    rows = steps(config) or DEFAULT_STEPS
    for index, row in enumerate(rows):
        kind = row['step']
        allowed, why = evaluate(row, message, config, claimed=claimed,
                                resolved=ticket_resolved(message.get('ticket')), preview=not contact)
        if kind == 'AI skill' and confirmation and allowed:
            why = 'Continue the search the customer confirmed; access is checked again'
        if kind == 'AI skill' and not contact and allowed:
            why = 'Requires a verified contact and matching business before execution'
        trace.append(dict(index=index, step=kind, runs=allowed, reason=why))
        if allowed:
            claimed = claimed or kind in ('Flow', 'AI skill', 'Out of hours reply')
            if row['on_reply'] == 'Stop':
                break
    return dict(trace=trace)
