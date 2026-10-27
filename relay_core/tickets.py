"""Ticket actions shared by Desk/API; all message references checked server-side."""
import hashlib
import json
from contextvars import ContextVar
import frappe
from relay_core import ai_features
from relay_core.permissions import require_access, readable_contact, sees_all_teams
from relay_core.api import validate_reference

_episode_transition = ContextVar('relay_episode_transition', default=None)


def _save_episode(doc, *, new=False):
    """Only server-owned admission may establish or advance episode scope."""
    from relay_core.permissions import require_administrator
    require_administrator()
    token = _episode_transition.set(doc)
    try:
        return doc.insert(ignore_permissions=True) if new else doc.save(ignore_permissions=True)
    finally:
        _episode_transition.reset(token)


def _ownership(doc, *, disabled=True):
    """Caller holds the ticket lock; generations invalidate approvals and old runs."""
    from frappe.utils import now_datetime
    doc.ai_disabled = int(disabled)
    doc.generation = int(doc.get('generation') or 0) + 1
    doc.pending_run = None
    doc.ownership_actor = frappe.session.user
    doc.ownership_at = now_datetime()


def hold_episode(name, *, claim=False):
    """Shared staff/service transition. Assignment alone never calls this."""
    require_access()
    doc = frappe.get_doc('Relay Ticket', name, for_update=True)
    doc.check_permission('write')
    if not doc.get('ai_disabled') or claim and doc.get('ownership_actor') != frappe.session.user:
        _ownership(doc)
        token = _episode_transition.set(doc)
        try:
            doc.save()
        finally:
            _episode_transition.reset(token)
    return doc


@frappe.whitelist(methods=['POST'])
def claim(name):
    validate_reference(name, 'TKT')
    doc = hold_episode(name, claim=True)
    return {'name': doc.name, 'ai_disabled': bool(doc.ai_disabled), 'generation': doc.generation}


@frappe.whitelist(methods=['POST'])
@ai_features.required
def resume_ai(name):
    require_access()
    validate_reference(name, 'TKT')
    doc = frappe.get_doc('Relay Ticket', name, for_update=True)
    doc.check_permission('write')
    if not doc.get('active_scope_key') or doc.status in ('Closed', 'Resolved'):
        frappe.throw('Only an active episode can resume AI')
    _ownership(doc, disabled=False)
    token = _episode_transition.set(doc)
    try:
        doc.save()
    finally:
        _episode_transition.reset(token)
    # No enqueue: only a new inbound message may start fresh work.
    return {'name': doc.name, 'ai_disabled': bool(doc.ai_disabled), 'generation': doc.generation}


@frappe.whitelist(methods=['POST'])
def close_and_release(name):
    require_access()
    validate_reference(name, 'TKT')
    doc = frappe.get_doc('Relay Ticket', name, for_update=True)
    doc.check_permission('write')
    if doc.get('active_scope_key'):
        _ownership(doc)
        doc.status, doc.active_scope_key = 'Closed', None
        token = _episode_transition.set(doc)
        try:
            doc.save()
        finally:
            _episode_transition.reset(token)
    return {'name': doc.name, 'status': doc.status, 'ai_disabled': bool(doc.ai_disabled),
            'generation': doc.generation}


def check_episode(run):
    """Lock only Relay state, fencing each continuation until its commit."""
    if not run.get('ticket'):
        return  # Pre-episode flow/policy recovery keeps its legacy contact fence.
    ticket = frappe.get_doc('Relay Ticket', run.ticket, for_update=True)
    if (ticket.ai_disabled or not ticket.active_scope_key
            or int(ticket.generation or 0) != int(run.get('ownership_generation') or 0)):
        raise ValueError('Episode ownership changed')


def manual_takeover(source):
    """Join the current episode hold to the caller's manual-message journal write."""
    if not source.get('business_name'):
        return
    if not frappe.db.get_value('Relay Channel', source.channel, 'company'):
        return  # Legacy channels cannot admit AI episodes.
    scope, key = _episode_scope(source)
    _lock_episode_routing(source, scope['conversation_key'])
    name = frappe.db.get_value('Relay Ticket', {'active_scope_key': key}, 'name', for_update=True)
    if not name and source.get('name') and not source.get('ticket'):
        source.check_permission('read')
        actor = frappe.session.user
        try:
            frappe.set_user('Administrator')
            name = ensure_episode(source, owner=actor).name
        finally:
            frappe.set_user(actor)
    if name:
        hold_episode(name, claim=True)
        source.ticket = name


def episode_owner_allowed(user, message):
    from relay_core.ai.tools import as_user
    from relay_core.permissions import company_allowed
    if not user or user == 'Guest' or not frappe.db.get_value('User', user, 'enabled'):
        return False
    try:
        with as_user(user):
            require_access()
            message.check_permission('read')
            readable_contact(message.relay_contact)
            company = frappe.db.get_value('Relay Channel', message.channel, 'company')
            return company_allowed(company)
    except (frappe.PermissionError, frappe.DoesNotExistError):
        return False


def _episode_scope(message):
    from relay_core.business_access import reference
    from relay_core.automation.provenance import context_of, conversation_key
    business = reference(message)
    company = frappe.db.get_value('Relay Channel', message.channel, 'company')
    conversation = message.get('conversation_key') or conversation_key(
        message.channel, message.sender_endpoint, context_of(message))
    if not company or not business or not message.sender_endpoint:
        raise ValueError('Episode requires a company and a resolved conversation')
    values = [frappe.local.site, company, message.channel, conversation, message.relay_contact, *business]
    key = hashlib.sha256(json.dumps(values, separators=(',', ':')).encode()).hexdigest()
    return dict(company=company, conversation_key=conversation, business_doctype=business[0],
                business_name=business[1]), key


def _lock_episode_routing(message, conversation):
    """Reuse the routing row as the transaction mutex, including its first insert."""
    from relay_core.automation.service import internal_save
    # Contact before routing, as the drain and projection lock them; the reverse order deadlocks (1213).
    frappe.db.get_value('Relay Contact', message.relay_contact, 'name', for_update=True)
    filters = {'conversation_key': conversation}
    name = frappe.db.get_value('Relay Business Routing', filters, 'name')
    if not name:
        frappe.db.savepoint('episode_routing')
        try:
            row = frappe.get_doc(dict(doctype='Relay Business Routing', **filters,
                relay_contact=message.relay_contact, channel=message.channel, endpoint=message.sender_endpoint))
            internal_save(row, new=True)
            name = row.name
        except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
            frappe.db.rollback(save_point='episode_routing')
            name = frappe.db.get_value('Relay Business Routing', filters, 'name', for_update=True)
    row = frappe.get_doc('Relay Business Routing', name, for_update=True)
    if (row.relay_contact, row.channel, row.endpoint) != (
            message.relay_contact, message.channel, message.sender_endpoint):
        raise ValueError('Conversation routing identity changed')


def triage_owner(channel, message=None):
    """No invented assignee: an unavailable primary must have an eligible backup."""
    from relay_core.ai.tools import as_user
    from relay_core.permissions import company_allowed
    fallback = frappe.get_single('Relay Settings').get('ai_handoff_owner')
    for user in (channel.get('triage_owner'), fallback):
        if not user or user in ('Guest', 'Administrator') or not frappe.db.get_value('User', user, 'enabled'):
            continue
        try:
            with as_user(user):
                require_access()
                if company_allowed(channel.get('company')) and (not message or episode_owner_allowed(user, message)):
                    return user
        except (ValueError, frappe.PermissionError, frappe.DoesNotExistError):
            continue
    return None


def source_episode(channel, row):
    """Stable provider identity survives Hub retries and later enrollment."""
    from relay_core.message_updates import provider_key
    context = row.get('provider_context') or {}
    key = provider_key(channel, row['from'], context.get('message_id') or row['id'])
    action = hashlib.sha256(json.dumps(['triage', frappe.local.site, channel, key]).encode()).hexdigest()
    return key, action


def _ensure_triage(event, channel, row):
    """Keep raw data in the internal Hub event; expose only a company-scoped intent."""
    from relay_core.automation.provenance import conversation_key
    # Serializes duplicate provider messages delivered under different Hub event IDs.
    channel = frappe.get_doc('Relay Channel', channel, for_update=True)
    if channel.account != event.account or not channel.enabled or not channel.get('company'):
        return None
    key, action = source_episode(channel.name, row)
    existing = frappe.db.get_value('Relay Ticket', {'source_action_key': action}, 'name', for_update=True)
    if existing:
        return frappe.get_doc('Relay Ticket', existing)
    owner = triage_owner(channel)
    if not owner:
        return None  # Uncategorized Hub event remains the recoverable intent.
    actor = frappe.session.user
    frappe.db.savepoint('triage_episode')
    try:
        frappe.set_user('Administrator')
        doc = frappe.get_doc(dict(doctype='Relay Ticket', subject='Incoming conversation needs triage',
            brief='Resolve the authenticated sender and business before continuing.', category='Support',
            status='Open', assigned_to=owner, company=channel.company,
            conversation_key=conversation_key(channel.name, row['from'], row.get('provider_context') or {}),
            source_action_key=action, source_hub_event=event.name, source_provider_message_key=key))
        _ownership(doc)
        # Triage holds AI until enrollment, but assignment is not a staff claim.
        doc.ownership_actor = None
        _save_episode(doc, new=True)
    except (frappe.PermissionError, frappe.ValidationError):
        # An owner can lose access between selection and controller validation.
        # Preserve the source intent and retry it through projection recovery.
        frappe.db.rollback(save_point='triage_episode')
        return None
    finally:
        frappe.set_user(actor)
    return doc


def ensure_episode(message=None, *, owner=None, skill=None, run=None, subject='Conversation needs attention',
                   reason='', event=None, channel=None, row=None):
    """Internal, atomic admission shared by automation paths; caller owns commit.

    A message's stored ticket wins over current active state, even after release.
    New messages reuse the active scope; only a new message reopens a closed hold.
    """
    if message is None:
        return _ensure_triage(event, channel, row)
    from relay_core.permissions import require_administrator
    require_administrator()
    frappe.db.savepoint('ensure_episode')
    try:
        scope, active_key = _episode_scope(message)
        _lock_episode_routing(message, scope['conversation_key'])
        message = frappe.get_doc('Relay Message', message.name, for_update=True)
        if _episode_scope(message) != (scope, active_key):
            raise ValueError('Message scope changed during episode admission')
        if run and (run.message != message.name or (run.get('ticket') and message.get('ticket')
                and run.ticket != message.ticket)):
            raise ValueError('Automation run belongs to another source or episode')
        source = message.get('provider_message_key') or message.get('source_key') or message.name
        episode_key = hashlib.sha256(json.dumps([active_key, source], separators=(',', ':')).encode()).hexdigest()
        linked = message.get('ticket') or (run.get('ticket') if run else None)
        existing = linked or frappe.db.get_value('Relay Ticket', {'source_action_key': episode_key}, 'name', for_update=True)
        existing = existing or frappe.db.get_value('Relay Ticket', {'active_scope_key': active_key}, 'name', for_update=True)
        if existing:
            ticket = frappe.get_doc('Relay Ticket', existing, for_update=True)
            if not episode_owner_allowed(ticket.assigned_to, message):
                raise ValueError('Episode owner is unavailable; an authorized assignment is required')
            if linked and ticket.get('source_hub_event') and not ticket.get('business_name'):
                if (ticket.company != scope['company'] or ticket.conversation_key != scope['conversation_key']
                        or ticket.source_provider_message_key != message.get('provider_message_key')):
                    raise ValueError('Triage source scope changed')
                active = frappe.db.get_value('Relay Ticket', {'active_scope_key': active_key}, 'name', for_update=True)
                if active and active != ticket.name:
                    raise ValueError('Triage conflicts with an existing episode')
                ticket.update(scope)
                ticket.active_scope_key = active_key
                ticket.append('messages', {'message': message.name})
            if linked and not ticket.get('conversation_key'):
                # Recover pre-episode handoffs without replacing their durable key.
                if not ticket.messages or any(_episode_scope(frappe.get_doc('Relay Message', row.message))[0] != scope
                                               for row in ticket.messages):
                    raise ValueError('Legacy ticket scope no longer matches the message')
                ticket.update(scope)
                if not frappe.db.get_value('Relay Ticket', {'active_scope_key': active_key}, 'name', for_update=True):
                    ticket.active_scope_key = active_key
            if any(ticket.get(key) != value for key, value in scope.items()):
                raise ValueError('Episode scope no longer matches the message')
            if not linked and ticket.status in ('Closed', 'Resolved'):
                ticket.status = 'Open'
        else:
            if not episode_owner_allowed(owner, message):
                raise ValueError('Configure an accessible episode owner or fallback owner')
            ticket = frappe.get_doc(dict(doctype='Relay Ticket', **scope, subject=subject,
                brief=reason[:500], category='Support', status='Open', assigned_to=owner,
                source_action_key=episode_key, active_scope_key=active_key,
                source_provider_message_key=message.get('provider_message_key'),
                source_run=run.name if run else None, messages=[{'message': message.name}]))
        if skill and not ticket.get('ai_disabled'):
            ticket.skill = skill.name
            ticket.skill_version = run.get('skill_version') if run else str(skill.modified)
        if reason:
            ticket.handoff_reason = reason[:500]
        _save_episode(ticket, new=not existing)
        if message.get('ticket') != ticket.name:
            # Advance modified so an older loaded message cannot erase this link.
            frappe.db.set_value('Relay Message', message.name, 'ticket', ticket.name)
        if run:
            frappe.db.set_value('Relay Automation Run', run.name, 'ticket', ticket.name, update_modified=False)
            run.ticket = ticket.name
        return ticket
    except frappe.QueryDeadlockError:
        # Frappe already rolled back the entire transaction; the worker retries it.
        raise
    except Exception:
        frappe.db.rollback(save_point='ensure_episode')
        raise


def validate_ticket(doc, check_assignment=True):
    require_access()
    if not isinstance(doc.subject, str) or not doc.subject.strip() or len(doc.subject) > 140:
        frappe.throw('Ticket subject must contain 1–140 characters')
    if doc.brief and (not isinstance(doc.brief, str) or len(doc.brief) > 4000):
        frappe.throw('Ticket brief must contain at most 4000 characters')
    if doc.category not in ('Query', 'Payment evidence', 'Support', 'Other'):
        frappe.throw('Invalid ticket category')
    if doc.status not in ('Open', 'In progress', 'Resolved', 'Closed'):
        frappe.throw('Invalid ticket status')
    previous = doc.get_doc_before_save()
    if any(record and any(record.get(key) for key in
            ('company', 'conversation_key', 'active_scope_key', 'source_hub_event'))
            for record in (doc, previous)):
        protected = ('company', 'conversation_key', 'source_hub_event', 'source_provider_message_key',
                     'source_action_key', 'business_doctype', 'business_name', 'active_scope_key',
                     'source_run', 'skill', 'skill_version', 'ai_disabled', 'generation', 'pending_run',
                     'ownership_actor', 'ownership_at')
        if _episode_transition.get() is not doc and (not previous or any(
                doc.get(key) != previous.get(key) for key in protected)):
            frappe.throw('Episode scope can only be changed by an internal transition', frappe.PermissionError)
    if (not doc.messages and not (doc.get('source_hub_event') and doc.get('source_provider_message_key')
            and doc.get('company') and doc.get('conversation_key'))) or len(doc.messages) > 50:
        frappe.throw('Link between 1 and 50 messages')
    if doc.get('active_scope_key') == '':
        doc.active_scope_key = None
    seen = set()
    for row in doc.messages:
        validate_reference(row.message, 'MSG')
        if row.message in seen:
            frappe.throw('A message can only be linked once per ticket')
        seen.add(row.message)
        message = frappe.get_doc('Relay Message', row.message)
        message.check_permission('read')
        readable_contact(message.relay_contact)
        if doc.get('conversation_key'):
            scope, _ = _episode_scope(message)
            if any(doc.get(key) != value for key, value in scope.items()):
                frappe.throw('Ticket scope must match its conversation')
        if doc.get('business_doctype') or doc.get('business_name'):
            from relay_core.business_access import reference
            if reference(message) != (doc.get('business_doctype'), doc.get('business_name')):
                frappe.throw('Ticket business must match its conversation')
    if not check_assignment:
        return
    if check_assignment and (doc.get('assigned_to') or '') != ((previous.get('assigned_to') or '') if previous else ''):
        require_access(manage=True)
        if doc.assigned_to:
            if not frappe.db.get_value('User', doc.assigned_to, 'enabled'):
                frappe.throw('Choose an enabled agent')
            actor = frappe.session.user
            try:
                frappe.set_user(doc.assigned_to)
                require_access()
                if doc.get('company'):
                    from relay_core.permissions import company_allowed
                    if not company_allowed(doc.company):
                        frappe.throw('Ticket company is not accessible', frappe.PermissionError)
                for row in doc.messages:
                    message = frappe.get_doc('Relay Message', row.message)
                    message.check_permission('read')
                    readable_contact(message.relay_contact)
            finally:
                frappe.set_user(actor)

    if (previous and doc.get('conversation_key') and doc.status != previous.status
            and doc.status in ('In progress', 'Closed', 'Resolved') and _episode_transition.get() is not doc):
        doc.check_permission('write')
        current = frappe.get_doc('Relay Ticket', doc.name, for_update=True)
        if int(current.generation or 0) != int(previous.generation or 0):
            frappe.throw('Episode ownership changed; reload the ticket')
        _ownership(doc)


@frappe.whitelist(methods=['POST'])
def create(subject, messages, brief='', category='Query'):
    require_access()
    if isinstance(messages, str):
        messages = frappe.parse_json(messages)
    if not isinstance(messages, list) or not 1 <= len(messages) <= 50 or any(not isinstance(m, str) for m in messages):
        frappe.throw('Messages must be a list of 1–50 references')
    doc = frappe.get_doc({'doctype': 'Relay Ticket', 'subject': subject, 'brief': brief,
                          'category': category, 'status': 'Open',
                          'messages': [{'message': name} for name in messages]})
    # insert runs the controller validation and Frappe create permissions.
    doc.insert()
    return {'name': doc.name, 'status': doc.status}


@frappe.whitelist(methods=['POST'])
def update_status(name, status):
    require_access()
    validate_reference(name, 'TKT')
    doc = frappe.get_doc('Relay Ticket', name, for_update=True)
    doc.check_permission('write')
    doc.status = status
    doc.save()
    return {'name': doc.name, 'status': doc.status}


@frappe.whitelist(methods=['GET'])
def read(name):
    require_access()
    validate_reference(name, 'TKT')
    doc = frappe.get_doc('Relay Ticket', name)
    doc.check_permission('read')
    links = []
    for row in doc.messages:
        message = frappe.get_doc('Relay Message', row.message)
        message.check_permission('read')
        readable_contact(message.relay_contact)
        links.append({'message': message.name, 'contact': message.relay_contact,
                      'channel': message.channel})
    drafts = []
    for row in frappe.get_all('Relay Flow Action', filters={'ticket': doc.name, 'status': 'Completed',
            'target_doctype': ['is', 'set'], 'target_name': ['is', 'set']},
            fields=['target_doctype', 'target_name'], order_by='creation asc', limit_page_length=100):
        try:
            target = frappe.get_doc(row.target_doctype, row.target_name)
            target.check_permission('read')
            if not any(target.get(f.fieldname) == doc.company for f in target.meta.fields
                    if f.fieldtype == 'Link' and f.options == 'Company'):
                continue
            if not any(target.get(f.fieldname) == doc.business_name for f in target.meta.fields
                    if f.fieldtype == 'Link' and f.options == doc.business_doctype
                    or f.fieldtype == 'Dynamic Link' and target.get(f.options) == doc.business_doctype):
                continue
            # No snapshot of accounting fields is disclosed through the ticket.
            drafts.append(dict(doctype=target.doctype, name=target.name, docstatus=int(target.docstatus)))
        except (frappe.PermissionError, frappe.DoesNotExistError):
            continue
    return {'name': doc.name, 'subject': doc.subject, 'brief': doc.brief, 'linked_drafts': drafts,
            'category': doc.category, 'status': doc.status, 'messages': links, 'creation': doc.creation,
            'assigned_to': doc.get('assigned_to'),
            'business_doctype': doc.get('business_doctype'), 'business_name': doc.get('business_name'),
            'handoff_reason': doc.get('handoff_reason'), 'source_run': doc.get('source_run'),
            'company': doc.get('company'), 'conversation_key': doc.get('conversation_key'),
            'skill': doc.get('skill'), 'skill_version': doc.get('skill_version'),
            'ai_disabled': bool(doc.get('ai_disabled')), 'generation': doc.get('generation') or 0,
            'ownership_actor': doc.get('ownership_actor'), 'ownership_at': doc.get('ownership_at'),
            'can_resume': bool(doc.get('active_scope_key') and doc.get('ai_disabled')
                and doc.status not in ('Closed', 'Resolved') and doc.has_permission('write')),
            'can_release': bool(doc.get('active_scope_key') and doc.has_permission('write')),
            'can_take_over': bool(not _legacy_ticket(doc) and doc.has_permission('write')),
            'can_assign': frappe.has_permission('Relay Conversation Assignment', 'write')}


def _legacy_ticket(ticket):
    # Evidence tickets created before episodes have no complete scope snapshot.
    return not (ticket.get('conversation_key') and ticket.get('company'))


def _read_message(name):
    message = frappe.get_doc('Relay Message', name)
    message.check_permission('read')
    readable_contact(message.relay_contact)
    channel = frappe.get_doc('Relay Channel', message.channel)
    channel.check_permission('read')
    return message, channel


def _episode_message(ticket, name):
    message, channel = _read_message(name)
    if (message.get('ticket') != ticket.name or channel.get('company') != ticket.get('company')
            or any(message.get(key) != ticket.get(key)
                   for key in ('conversation_key', 'business_doctype', 'business_name'))):
        frappe.throw('Transcript scope changed', frappe.PermissionError)
    message.apply_fieldlevel_read_permissions()
    return message


def _history_json(value):
    try:
        value = json.loads(value or '{}')
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


@frappe.whitelist(methods=['GET'])
@ai_features.required
def ai_history(name, before=None, limit=20):
    """Operational evidence only. Internal journals never become public documents."""
    require_access()
    validate_reference(name, 'TKT')
    if isinstance(limit, bool) or not isinstance(limit, (str, int)) or not str(limit).isdigit() or not 1 <= int(limit) <= 50:
        frappe.throw('Limit must be between 1 and 50')
    ticket = frappe.get_doc('Relay Ticket', name)
    ticket.check_permission('read')
    if _legacy_ticket(ticket):
        if before:
            frappe.throw('History cursor requires an episode', frappe.PermissionError)
        return {'items': [], 'next': None}
    filters = {'ticket': name}
    if before:
        validate_reference(before, 'AR')
        anchor = frappe.get_doc('Relay Automation Run', before)
        if anchor.ticket != name:
            frappe.throw('History cursor belongs to another episode', frappe.PermissionError)
        _episode_message(ticket, anchor.message)
        filters['name'] = ['<', before]
    rows = frappe.get_all('Relay Automation Run', filters=filters,
        fields=['name', 'message', 'skill', 'skill_version', 'status', 'stage', 'creation',
                'search_plan', 'decision', 'ownership_generation'],
        order_by='name desc', limit_page_length=int(limit) + 1)
    items = []
    for run in rows[:int(limit)]:
        _episode_message(ticket, run.message)
        plan = _history_json(run.search_plan)
        search = plan.get('plan')
        # Purpose/reference are the declared announcement; never return filters,
        # returned records, model reasoning, typed action inputs or scope snapshots.
        announcement = None
        if isinstance(search, dict):
            announcement = dict(reference=str(search.get('reference') or '')[:140],
                purpose=str(search.get('purpose') or '')[:500],
                confirmed=bool(plan.get('confirmed_by') or plan.get('consumed_by')))
        reads = _history_json(run.decision).get('reads')
        actions = []
        for action in frappe.get_all('Relay Flow Action', filters={'automation_run': run.name, 'ticket': name},
                fields=['name', 'action', 'step', 'status', 'approval_evidence'],
                order_by='step asc', limit_page_length=4):
            stale = (action.status != 'Completed' and (ticket.get('ai_disabled')
                or int(run.ownership_generation or 0) != int(ticket.get('generation') or 0)))
            actions.append(dict(name=action.name, action=action.action, step=action.step + 1,
                status='Stopped' if stale else action.status,
                approval='Invalidated' if stale else 'Recorded' if action.approval_evidence else None))
        deliveries = []
        for delivery in frappe.get_all('Relay Message Action', filters={'source_message': run.message},
                fields=['name', 'status', 'payload'], order_by='creation asc', limit_page_length=20):
            if _history_json(delivery.payload).get('automation_run') == run.name:
                deliveries.append(dict(name=delivery.name, status=delivery.status))
        items.append(dict(name=run.name, creation=run.creation, status=run.status,
            event=frappe.db.get_value('Relay AI Skill', run.skill, 'title') if run.skill else None,
            event_version=run.skill_version, stage=run.stage, search=announcement,
            read_count=len(reads) if isinstance(reads, list) else 0,
            actions=actions, deliveries=deliveries))
    return {'items': items, 'next': {'before': rows[int(limit)-1].name} if len(rows) > int(limit) else None}


def _delivery_rows(name, *, before=None, before_created=None, exact=None, limit=51):
    # Journals already carry immutable episode snapshots. Include older anchored
    # flow replies through their source message; never expose journal payloads.
    return frappe.db.sql("""
        SELECT * FROM (
            SELECT a.name, a.status, a.creation, a.source_message, a.target_channel AS channel,
                'Message' AS kind, NULL AS source_doctype, NULL AS source_name,
                NULL AS business_doctype, NULL AS business_name
            FROM `tabRelay Message Action` a
            LEFT JOIN `tabRelay Message` m ON m.name = a.source_message
            WHERE m.ticket = %(ticket)s OR JSON_UNQUOTE(JSON_EXTRACT(a.payload, '$.ticket')) = %(ticket)s
                OR JSON_SEARCH(a.payload, 'one', %(ticket)s, NULL, '$.delivery_episodes[*][0]') IS NOT NULL
            UNION ALL
            SELECT d.name, d.status, d.creation, NULL AS source_message, d.channel,
                'Lifecycle notice' AS kind, d.source_doctype, d.source_name, d.business_doctype, d.business_name
            FROM `tabRelay Business Event Delivery` d
            WHERE JSON_SEARCH(d.payload, 'one', %(ticket)s, NULL, '$.delivery_episodes[*][0]') IS NOT NULL
        ) deliveries
        WHERE (%(before)s IS NULL OR creation < %(before_created)s
            OR (creation = %(before_created)s AND name < %(before)s))
          AND (%(exact)s IS NULL OR name = %(exact)s)
        ORDER BY creation DESC, name DESC LIMIT %(limit)s
    """, dict(ticket=name, before=before, before_created=before_created, exact=exact, limit=limit), as_dict=True)


def _read_delivery(ticket, row):
    channel = frappe.get_doc('Relay Channel', row.channel)
    channel.check_permission('read')
    if channel.get('company') != ticket.company:
        frappe.throw('Delivery company changed', frappe.PermissionError)
    if row.source_message:
        _episode_message(ticket, row.source_message)
    if row.kind == 'Lifecycle notice':
        if (row.business_doctype, row.business_name) != (ticket.business_doctype, ticket.business_name):
            frappe.throw('Delivery business changed', frappe.PermissionError)
        frappe.get_doc(row.source_doctype, row.source_name).check_permission('read')
    return {key: row.get(key) for key in ('name', 'status', 'creation', 'kind')}


@frappe.whitelist(methods=['GET'])
def deliveries(name, before=None, limit=50):
    """Permission-checked delivery states, including flow and suppressed notices."""
    require_access()
    validate_reference(name, 'TKT')
    if isinstance(limit, bool) or not isinstance(limit, (str, int)) or not str(limit).isdigit() or not 1 <= int(limit) <= 100:
        frappe.throw('Limit must be between 1 and 100')
    ticket = frappe.get_doc('Relay Ticket', name)
    ticket.check_permission('read')
    if _legacy_ticket(ticket):
        if before:
            frappe.throw('History cursor requires an episode', frappe.PermissionError)
        return {'items': [], 'next': None}
    if before:
        if not isinstance(before, str) or len(before) > 140:
            frappe.throw('Invalid delivery cursor')
        anchor = _delivery_rows(name, exact=before, limit=1)
        if not anchor:
            frappe.throw('Delivery cursor belongs to another episode', frappe.PermissionError)
        _read_delivery(ticket, anchor[0])
    rows = _delivery_rows(name, before=before, before_created=anchor[0].creation if before else None,
        limit=int(limit) + 1)
    return {'items': [_read_delivery(ticket, row) for row in rows[:int(limit)]],
            'next': {'before': rows[int(limit)-1].name} if len(rows) > int(limit) else None}


@frappe.whitelist(methods=['GET'])
def transcript(name, after=None, limit=50):
    """Bounded transcript pages are independent of the selected evidence table."""
    require_access()
    validate_reference(name, 'TKT')
    if isinstance(limit, bool) or not isinstance(limit, (str, int)) or not str(limit).isdigit() or not 1 <= int(limit) <= 100:
        frappe.throw('Limit must be between 1 and 100')
    ticket = frappe.get_doc('Relay Ticket', name)
    ticket.check_permission('read')
    legacy = _legacy_ticket(ticket)
    linked = {row.message for row in ticket.messages} if legacy else set()
    if legacy and not linked:
        if after:
            frappe.throw('Transcript cursor is not linked to this ticket', frappe.PermissionError)
        return {'items': [], 'next': None}
    filters = {'name': ['in', sorted(linked)]} if legacy else {'ticket': name}
    if after:
        validate_reference(after, 'MSG')
        if legacy:
            if after not in linked:
                frappe.throw('Transcript cursor is not linked to this ticket', frappe.PermissionError)
            _read_message(after)
            filters['name'] = ['in', sorted(item for item in linked if item > after)]
        else:
            _episode_message(ticket, after)
            filters['name'] = ['>', after]
    rows = frappe.get_list('Relay Message', filters=filters, fields=['name'], order_by='name asc', page_length=int(limit)+1)
    items = []
    fields = ('name', 'content', 'direction', 'status', 'creation', 'sent_at', 'message_type', 'channel')
    for row in rows[:int(limit)]:
        if legacy:
            if row.name not in linked:
                frappe.throw('Message is not linked to this ticket', frappe.PermissionError)
            message, _ = _read_message(row.name)
            message.apply_fieldlevel_read_permissions()
        else:
            message = _episode_message(ticket, row.name)
        items.append({key: message.get(key) for key in fields})
    return {'items': items, 'next': {'after': rows[int(limit)-1].name} if len(rows) > int(limit) else None}


@frappe.whitelist(methods=['POST'])
def assign(name, user=''):
    require_access(manage=True)
    validate_reference(name, 'TKT')
    doc = frappe.get_doc('Relay Ticket', name)
    doc.check_permission('write')
    doc.assigned_to = user or None
    doc.save()
    return read(name)


def permission(doc, user=None, permission_type=None):
    from relay_core.permissions import can_read_contact_as, company_allowed
    from relay_core.business_access import allowed, reference
    user = user or frappe.session.user
    if user == 'Administrator': return True
    if not (user in (doc.owner, doc.get('assigned_to')) or sees_all_teams(user) or doc.messages):
        return False
    if doc.get('company') and not company_allowed(doc.company, user): return False
    if doc.get('business_doctype') or doc.get('business_name'):
        if not (doc.get('business_doctype') and doc.get('business_name')) or not allowed(doc, user):
            return False
    if not doc.messages:
        return bool(doc.get('source_hub_event') and doc.get('source_provider_message_key')
                    and doc.get('company') and doc.get('conversation_key') and not doc.get('business_name'))
    try:
        for row in doc.messages:
            message = frappe.get_doc('Relay Message', row.message)
            if not message.has_permission('read', user=user) or not can_read_contact_as(message.relay_contact, user):
                return False
            if doc.get('business_name') and reference(message) != (doc.business_doctype, doc.business_name):
                return False
        return True
    except frappe.DoesNotExistError:
        return False


def query_condition(user=None):
    from relay_core.business_access import explicit_condition
    from relay_core.permissions import company_condition
    user = user or frappe.session.user
    if user == 'Administrator': return ''
    quoted = frappe.db.escape(user)
    # Ticket messages follow the conversation row rule; a ticket without messages needs ownership.
    gate = '1=1' if sees_all_teams(user) else (
        f"(`tabRelay Ticket`.owner={quoted} OR `tabRelay Ticket`.assigned_to={quoted} OR EXISTS "
        f"(SELECT 1 FROM `tabRelay Ticket Message` o WHERE o.parent=`tabRelay Ticket`.name AND o.parenttype='Relay Ticket'))")
    messages = frappe.qb.get_query('Relay Message', fields=['name'], ignore_permissions=False,
                                   user=user, order_by='').get_sql()
    contacts = frappe.qb.get_query('Relay Contact', fields=['name'], ignore_permissions=False,
                                   user=user, order_by='').get_sql()
    links = "t.parent=`tabRelay Ticket`.name AND t.parenttype='Relay Ticket'"
    return f"""({gate}) AND ({company_condition('Relay Ticket', user)}) AND ({explicit_condition('Relay Ticket', user, allow_empty=True)})
        AND (EXISTS (SELECT 1 FROM `tabRelay Ticket Message` t WHERE {links}) OR
             (COALESCE(`tabRelay Ticket`.source_hub_event,'')!=''
              AND COALESCE(`tabRelay Ticket`.source_provider_message_key,'')!=''
              AND COALESCE(`tabRelay Ticket`.company,'')!=''
              AND COALESCE(`tabRelay Ticket`.conversation_key,'')!=''
              AND COALESCE(`tabRelay Ticket`.business_name,'')=''))
        AND NOT EXISTS (SELECT 1 FROM `tabRelay Ticket Message` t WHERE {links}
          AND NOT EXISTS (SELECT 1 FROM `tabRelay Message` m WHERE m.name=t.message
            AND m.name IN ({messages}) AND m.relay_contact IN ({contacts})
            AND (COALESCE(`tabRelay Ticket`.business_name,'')='' OR
                 (m.business_doctype=`tabRelay Ticket`.business_doctype AND m.business_name=`tabRelay Ticket`.business_name))))"""


@frappe.whitelist(methods=['GET'])
def directory(query='', before=None, after=None, status=None, business_doctype=None, business_name=None, assigned_to=None, category=None):
    require_access()
    if not isinstance(query,str) or len(query)>80 or before and after: frappe.throw('Invalid ticket search')
    filters={}
    for key, value in dict(business_doctype=business_doctype, business_name=business_name, assigned_to=assigned_to, category=category).items():
        if value:
            if not isinstance(value, str) or len(value) > 140: frappe.throw('Invalid ticket filter')
            filters[key] = value
    if status:
        if status not in ('Open','In progress','Resolved','Closed'): frappe.throw('Invalid ticket status')
        filters['status']=status
    if before or after:
        validate_reference(before or after,'TKT');filters['name']=['<' if before else '>',before or after]
    if query:filters['subject']=['like','%'+query.replace('%','\\%').replace('_','\\_')+'%']
    rows=frappe.get_list('Relay Ticket',filters=filters,fields=['name'],order_by='name desc' if before else 'name asc',page_length=31)
    more=len(rows)>30;page=rows[:30]
    if before:page.reverse()
    items=[]
    for row in page:
        try:ticket=read(row.name)
        except frappe.PermissionError:continue
        items.append(dict(ticket,id=ticket['name']))
    return {'items':items,'previous':{'before':page[0].name} if page and (more if before else bool(after)) else None,
        'next':{'after':page[-1].name} if page and (bool(before) if before else more) else None}
