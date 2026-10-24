"""Explicit identity/business mapping and restricted history triage."""
import hashlib
import json

import frappe
from relay_core import legacy_bundle as bundles
from relay_core.permissions import require_access, sequential_name


def direct_document(doctype, values, name=None):
    """History only; bypass notifications, integrations and controller side effects."""
    doc = frappe.get_doc(dict(doctype=doctype, **values))
    if name: doc.name = name
    else:
        from frappe.model.naming import set_new_name
        set_new_name(doc)
    now = frappe.utils.now_datetime()
    doc.owner = values.get('owner') or frappe.session.user
    doc.creation = values.get('creation') or now
    doc.modified = now; doc.modified_by = frappe.session.user
    doc.db_insert()
    return doc


def validate_mapping(job, manifest):
    if bool(job.business_doctype) != bool(job.business_name):
        frappe.throw('Choose both business DocType and record, or leave both in triage')
    if job.business_name:
        from relay_core.business_access import candidates
        if (job.business_doctype, job.business_name) not in candidates(job.relay_contact):
            frappe.throw('Explicit business mapping must be configured and linked to this Contact')
        frappe.get_doc(job.business_doctype, job.business_name).check_permission('read')
    # A different source sending number must not accidentally merge into this channel.
    for other in frappe.get_all('Relay Legacy Import', filters={'channel': job.channel, 'status': ['!=', 'Draft']},
                                fields=['source_site', 'source_channel', 'source_metadata'], limit_page_length=1):
        old = json.loads(other.source_metadata or '{}').get('channel', {})
        current = manifest.get('metadata', {}).get('channel', {})
        if old.get('phone_number_id') and current.get('phone_number_id') and old['phone_number_id'] != current['phone_number_id']:
            frappe.throw('This Relay channel is already mapped to another sending number')
    # Never allow an imported endpoint to implicitly replace an enrolled identity.
    existing = frappe.db.get_value('Relay Contact Endpoint', {'channel': job.channel, 'endpoint': manifest['endpoint']},
                                    ['name', 'relay_contact'], as_dict=True)
    if existing and existing.relay_contact != job.relay_contact:
        frappe.throw('Source endpoint is already mapped to another Relay contact')
    if not existing:
        direct_document('Relay Contact Endpoint', dict(channel=job.channel, endpoint=manifest['endpoint'],
            relay_contact=job.relay_contact, verified=0, endpoint_key=hashlib.sha256((job.channel + ':' + manifest['endpoint']).encode()).hexdigest()))


def prepare_import(manifest, channel, *, source_bundle=None, business=None, user_map=None, team_map=None):
    """Create/reuse an unverified archive identity. Business targets must be explicit.

    Identical source identity names on different sites remain separate. Matching
    phone numbers never establish verification or infer a business association.
    """
    require_access(configure=True)
    from relay_core.legacy import source_key
    identity = manifest.get('metadata', {}).get('identity', {})
    identity_name = identity.get('name') or manifest['source_conversation']
    key = source_key(manifest['source_site'], 'identity:' + identity_name)
    contact_name = 'relay-archive-' + key
    relay = frappe.db.get_value('Relay Contact', {'contact': contact_name}, 'name')
    if not relay:
        if not frappe.db.exists('Contact', contact_name):
            direct_document('Contact', {'first_name': identity.get('display_value') or manifest['endpoint'],
                'full_name': identity.get('display_value') or manifest['endpoint']}, contact_name)
        relay = direct_document('Relay Contact', {'contact': contact_name,
            'display_name': identity.get('display_value') or manifest['endpoint'], 'automation_paused': 1}, sequential_name('contact')).name
    if business:
        doctype, name = business
        frappe.get_doc(doctype, name).check_permission('read')
        if not frappe.db.exists('Dynamic Link', {'parent': contact_name, 'parenttype': 'Contact', 'link_doctype': doctype, 'link_name': name}):
            direct_document('Dynamic Link', {'parent': contact_name, 'parenttype': 'Contact', 'parentfield': 'links',
                'link_doctype': doctype, 'link_name': name, 'idx': 1}, frappe.generate_hash(length=10))
    return frappe.get_doc(dict(doctype='Relay Legacy Import', source_site=manifest['source_site'],
        source_conversation=manifest['source_conversation'], source_channel=manifest['source_channel'],
        source_bundle=source_bundle, channel=channel, relay_contact=relay,
        business_doctype=business[0] if business else None, business_name=business[1] if business else None,
        user_mapping=bundles.canonical(user_map or {}), team_mapping=bundles.canonical(team_map or {}))).insert()


def previous_projections(job, manifest):
    from relay_core.legacy import object_value
    previous = frappe.get_all('Relay Legacy Import', filters={
        'source_site': manifest['source_site'], 'source_conversation': manifest['source_conversation'],
        'relay_contact': job.relay_contact, 'channel': job.channel, 'status': 'Completed'},
        fields=['reconcile_report'], order_by='modified desc, name desc', limit_page_length=1)
    return object_value(previous[0].reconcile_report).get('collaboration_projections', {}) if previous else {}


def merge_projection(doctype, current, baseline, values):
    updates = {}; conflicts = []
    for field, value in values.items():
        live = current.get(field)
        if field not in baseline or bundles.canonical(live) != bundles.canonical(baseline[field]):
            if bundles.canonical(live) != bundles.canonical(value): conflicts.append(field)
            continue
        if doctype == 'Relay Conversation State' and field in ('last_read', 'last_seen'):
            if live and (not value or str(live) > str(value)):
                conflicts.append(field); continue
        updates[field] = value
    return updates, conflicts


def import_metadata(job, manifest, report):
    from relay_core.legacy import source_key, object_value, source_datetime
    metadata = manifest.get('metadata', {})
    users = object_value(job.user_mapping); teams = object_value(job.team_mapping)
    site = manifest['source_site']; contact = job.relay_contact
    report['related_counts'] = {key: len(metadata.get(key, [])) for key in
        ('identity_links', 'party_bindings', 'staff_reads', 'conversation_reads', 'notes', 'topics', 'topic_messages')}
    projections = report.setdefault('collaboration_projections', previous_projections(job, manifest))
    if not job.business_name:
        report['business_mapping'] = 'Restricted triage: explicit business mapping required'
        return
    report['business_mapping'] = [job.business_doctype, job.business_name]

    def mismatch(kind, row, detail):
        item = {'source': row.get('name'), 'kind': kind, 'detail': detail}
        if item not in report['mismatches']: report['mismatches'].append(item)

    def user(name, row):
        target = users.get(name)
        if target and frappe.db.exists('User', target): return target
        mismatch('user_mapping', row, 'Unmapped staff user: ' + str(name))

    def message(name):
        return frappe.db.get_value('Relay Message', {'source_key': source_key(site, name)}, 'name') if name else None

    def upsert(doctype, key, values, row, *, owner=None):
        identity = 'relay-history-' + source_key(site, doctype + ':' + str(row['name']))
        name = identity
        baseline = projections.get(identity, {})
        existing = frappe.db.get_value(doctype, key, 'name') if key else frappe.db.exists(doctype, name)
        collaboration = doctype in ('Relay Internal Comment', 'Relay Conversation Topic')
        if not existing:
            if baseline:
                mismatch('collaboration_conflict', row, doctype + ': locally removed record retained')
                return None
            name = direct_document(doctype, dict(values, owner=owner or frappe.session.user, creation=source_datetime(row.get('creation'), metadata.get('timezone'))),
                None if collaboration else name).name
            projections[identity] = {
                'name': name, 'fields': frappe.db.get_value(doctype, name, list(values), as_dict=True)}
        else:
            current = frappe.db.get_value(doctype, existing, list(values), as_dict=True, for_update=True)
            fields = baseline.get('fields', {}) if baseline.get('name') == existing else {}
            if collaboration and baseline.get('name') == existing and not current.get('business_doctype') and not current.get('business_name'):
                # This source-key baseline proves ownership of pre-scope imports.
                for field in ('business_doctype', 'business_name'):
                    if field in values and field not in fields:
                        fields[field] = current.get(field)
            updates, conflicts = merge_projection(doctype, current, fields, values)
            if updates:
                frappe.db.set_value(doctype, existing, updates, update_modified=False)
                fields.update(frappe.db.get_value(doctype, existing, list(updates), as_dict=True))
            if conflicts:
                mismatch('collaboration_conflict', row, doctype + ': local fields retained: ' + ', '.join(conflicts))
        return existing or name

    for row in metadata.get('staff_reads', []):
        reader = user(row.get('user'), row); target = message(row.get('message'))
        if not target:
            mismatch('staff_read', row, 'Message not imported in this segment; replay metadata after all segments'); continue
        if reader:
            key = hashlib.sha256((reader + ':' + target).encode()).hexdigest()
            upsert('Relay Message Read', {'read_key': key}, dict(user=reader, message=target, relay_contact=contact, read_key=key),
                dict(row, creation=row.get('read_at') or row.get('creation')), owner=reader)
    for row in metadata.get('conversation_reads', []):
        reader = user(row.get('user'), row); target = message(row.get('last_read_message'))
        if reader:
            from relay_core.inbox import state_key
            key = state_key(contact, reader)
            upsert('Relay Conversation State', {'state_key': key}, dict(state_key=key, user=reader, relay_contact=contact,
                last_read=target, last_seen=source_datetime(row.get('last_opened_at'), metadata.get('timezone')), exact_reads=1), row, owner=reader)
    old = metadata.get('conversation', {})
    assigned = user(old['assigned_user'], old) if old.get('assigned_user') else None
    team = teams.get(old.get('assigned_team'))
    if old.get('assigned_team') and (not team or not frappe.db.exists('Relay Team', team)):
        team = None; mismatch('team_mapping', old, 'Unmapped staff team')
    if assigned or team or ('relay-history-' + source_key(site, 'Relay Conversation Assignment:' + str(old.get('name')))) in projections:
        upsert('Relay Conversation Assignment', {'relay_contact': contact},
            dict(relay_contact=contact, assigned_to=assigned, team=team), old)
    # Notes/topics retain complete source rows on the restricted import record as well.
    note_names = {}
    for row in metadata.get('notes', []):
        author = user(row.get('user') or row.get('owner'), row)
        if not author: continue
        refs = row.get('message_references') or '[]'
        if isinstance(refs, str):
            try: refs = json.loads(refs)
            except ValueError: refs = []
        mapped = [message(ref) for ref in refs if isinstance(ref, str)] if isinstance(refs, list) else []
        note_key = source_key(site, 'note:' + row['name'])
        note_names[row['name']] = upsert('Relay Internal Comment', {'request_key': note_key}, dict(relay_contact=contact, business_doctype=job.business_doctype, business_name=job.business_name, body=row.get('content'),
            messages=bundles.canonical([m for m in mapped if m]),
            request_key=note_key, assigned_to=user(row['assigned_to'], row) if row.get('assigned_to') else None,
            task_status='Done' if row.get('status') == 'Resolved' else 'Open', mentions='[]'), row, owner=author)
    for row in metadata.get('notes', []):
        if note_names.get(row['name']):
            parent = note_names.get(row.get('parent_comment'))
            if row.get('parent_comment') and not parent:
                mismatch('note_parent', row, 'Unmapped parent note'); continue
            key = 'relay-history-' + source_key(site, 'Relay Internal Comment:' + row['name'])
            baseline = projections.get(key, {})
            if baseline and 'reply_to' not in baseline['fields']:
                baseline['fields']['reply_to'] = None
            upsert('Relay Internal Comment', {'request_key': source_key(site, 'note:' + row['name'])},
                {'reply_to': parent}, row)
    for row in metadata.get('topics', []):
        refs = [message(r['message']) for r in metadata.get('topic_messages', []) if r.get('topic') == row['name']]
        topic_key = source_key(site, 'topic:' + row['name'])
        upsert('Relay Conversation Topic', {'topic_key': topic_key}, dict(relay_contact=contact, business_doctype=job.business_doctype, business_name=job.business_name, topic_key=topic_key,
            title=row.get('title'), summary=row.get('summary'), category=row.get('category'), status=row.get('status'), source='Import',
            messages=bundles.canonical([m for m in refs if m]), attributes=bundles.canonical({'legacy': row})), row)


def project_reactions(job, report):
    from relay_core.legacy import object_value, reaction_timestamp
    from relay_core.message_updates import provider_key
    rows = frappe.get_all('Relay Message', filters={'relay_contact': job.relay_contact, 'channel': job.channel,
        'legacy_source': ['is', 'set'], 'message_type': 'reaction'}, fields=['name', 'message_data', 'sender_endpoint', 'legacy_author', 'direction', 'sent_at'],
        order_by='sent_at asc, name asc', limit_page_length=0)
    for row in rows:
        reaction = object_value(row.message_data).get('reaction', {})
        target_id = reaction.get('message_id')
        target = frappe.db.get_value('Relay Message', {'provider_message_key': provider_key(job.channel, row.sender_endpoint, target_id)},
                                    ['name', 'reactions', 'message_updates'], as_dict=True, for_update=True) if target_id else None
        if not target:
            report['mismatches'].append({'source': row.name, 'kind': 'reaction', 'detail': 'Reaction target unavailable'}); continue
        state = object_value(target.reactions)
        actor = str(object_value(row.message_data).get('reaction_actor') or row.sender_endpoint)
        history = object_value(target.message_updates)
        key = 'reaction:' + actor
        timestamp = object_value(row.message_data).get('reaction_timestamp')
        if timestamp is None: timestamp = reaction_timestamp(row.sent_at)
        previous = history.get(key)
        # Remove the obsolete importer-only actor alias, including after live removal.
        alias = row.direction + ':' + actor
        changed = alias in state
        state.pop(alias, None)
        previous_time = int(previous.get('timestamp', 0)) if previous else -1
        later_history = (previous_time == timestamp and str(previous.get('event_id', '')).startswith('legacy:')
            and previous['event_id'] < 'legacy:' + row.name)
        if previous_time < timestamp or later_history:
            state[actor] = [{'type': 'emoji', 'emoji': reaction['emoji']}] if reaction.get('emoji') else []
            history[key] = {'event_id': 'legacy:' + row.name, 'timestamp': timestamp, 'sequence': 0}
            changed = True
        if changed:
            frappe.db.set_value('Relay Message', target.name, dict(reactions=bundles.canonical(state),
                message_updates=bundles.canonical(history)), update_modified=False)
