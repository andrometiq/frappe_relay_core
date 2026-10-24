"""Local-only fixtures for the channel recovery site tests."""
import os
from pathlib import Path
from unittest.mock import patch

import frappe


def init():
    root = Path(__file__).resolve().parents[1]
    sites = Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()
    site = os.environ.get('RELAY_TEST_SITE', 'relay-ai-test.local')
    if site == 'yrp.site':
        assert sites == Path('/home/sakthi/development/pilot/benches/version_16/sites')
    else:
        assert site == 'relay-ai-test.local' and sites == root / '.runtime/automation-bench/sites'
    os.chdir(sites)
    frappe.init(site=site, sites_path=str(sites))
    if site != 'yrp.site':
        assert frappe.conf.db_name == 'relay_ai_test_20260922' and frappe.conf.db_port == 18433
    frappe.connect(); frappe.set_user('Administrator')
    frappe.flags.mute_emails = True
    frappe.conf.relay_automation_enabled = 0
    # All jobs and provider sends stay in this process under explicit test control.
    patch.object(frappe, 'enqueue').start()
    patch.object(frappe, 'publish_realtime').start()
    from relay_core import whatsapp
    patch.object(whatsapp, 'client', side_effect=AssertionError('Unexpected external Hub call')).start()
    return site


def user(email, manager=False):
    if not frappe.db.exists('User', email):
        roles = ['Relay Communication User', 'Sales User']
        if manager: roles.append('Relay Communication Manager')
        assert email.endswith('@example.invalid')
        # Repeated isolated site runs may exceed Frappe's hourly signup limit.
        # Bypass only fixture provisioning; all Relay permission checks stay real.
        with patch('frappe.core.doctype.user.user.throttle_user_creation'):
            frappe.get_doc({'doctype':'User', 'email':email, 'first_name':'Local channel fixture',
                'send_welcome_email':0, 'roles':[{'role':role} for role in roles]}).insert()
    return email


def business(title):
    if frappe.local.site != 'yrp.site':
        return frappe.get_doc({'doctype':'Relay Inbox Simulation Business','title':title}).insert()
    return frappe.get_doc({'doctype':'Customer', 'customer_name':'Local Relay C1 '+title,
        'customer_type':'Company',
        'customer_group':frappe.db.get_value('Customer Group', {'is_group':0}, 'name'),
        'territory':frappe.db.get_value('Territory', {'is_group':0}, 'name')}).insert()


def push_status(account, rows):
    """Exercise signed ingress and the real projection job, with no live HTTP."""
    import hashlib
    import hmac
    import json
    import time
    from types import SimpleNamespace
    from relay_core import inbound, channel_statuses
    from relay_core.automation import projection
    actor = frappe.session.user
    secret = 'local-channel-fixture-signing-secret'
    try:
        frappe.set_user('Administrator')
        for row in rows:
            payload = {'account':account, 'statuses':[row]}
            raw = json.dumps(payload).encode(); timestamp = str(int(time.time()))
            signature = hmac.new(secret.encode(), timestamp.encode()+b'.'+raw, hashlib.sha256).hexdigest()
            request = SimpleNamespace(get_data=lambda:raw, headers={'X-Relay-Timestamp':timestamp,'X-Relay-Signature':signature})
            settings = lambda key: {'relay_hub_account':account,'relay_callback_secret':secret}.get(key)
            with patch.object(inbound,'connection_value',side_effect=settings), patch.object(frappe,'request',request):
                assert inbound.receive_channel_statuses()['accepted'] == 1
            key = 'channel-statuses:'+hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            name = frappe.db.get_value('Relay Hub Event', {'event_key':key}, 'name')
            frappe.db.commit()
            with patch.object(channel_statuses,'connection_value',return_value=account):
                projection.project(name)
            frappe.db.commit()
            assert frappe.db.get_value('Relay Hub Event',name,'projection_status') == 'Projected'
    finally:
        frappe.set_user(actor)


def check_business_lifecycle(doc):
    from frappe.model.delete_doc import get_linked_docs, get_dynamic_linked_docs
    from relay_core.business_references import allow_cancel
    actor = frappe.session.user
    try:
        frappe.set_user('Administrator');doc.reload()
        field = 'customer_details' if doc.doctype == 'Customer' else 'title'
        doc.set(field, 'Local Relay C1 lifecycle check quantity 25');doc.save();frappe.db.commit()
        for method in ('Delete','Cancel'):
            if method == 'Cancel':allow_cancel(doc)
            links = get_linked_docs(doc,method) + get_dynamic_linked_docs(doc,method)
            assert not any(link['reference_doctype'].startswith('Relay ') for link in links)
    finally:
        frappe.set_user(actor)
