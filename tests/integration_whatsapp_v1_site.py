"""Populated WhatsApp v1 acceptance on the isolated fixture database only.

Requires migrated Core metadata and the existing Relay Test Business fixture.
No migration, configuration writes, cleanup or external delivery is performed.
"""
from site_labels import run_label
import hashlib
import hmac
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT / '.runtime/automation-bench/sites')
import frappe
from relay_core import api, conversation_start, enrollment, inbound, messaging, whatsapp
from relay_core.automation import projection
from relay_core.message_updates import provider_key

frappe.init(site='relay-ai-test.local')
assert frappe.conf.db_name == 'relay_ai_test_20260922'
assert frappe.conf.db_host == '127.0.0.1' and int(frappe.conf.db_port) == 18433
frappe.connect()
frappe.db.sql('select 1')
frappe.set_user('Administrator')
frappe.flags.mute_emails = True
frappe.conf.relay_automation_enabled = 0
stamp = run_label()
account, secret = 'wa-v1-' + stamp, 'local-only-callback-secret-' + stamp
connection = lambda key: {'relay_hub_account':account,'relay_callback_secret':secret}.get(key)
patches = [patch.object(module,'connection_value',side_effect=connection)
           for module in (inbound,whatsapp,messaging,conversation_start,enrollment)]
from relay_core import channel_statuses, whatsapp_templates
patches += [patch.object(channel_statuses,'connection_value',side_effect=connection),
            patch.object(whatsapp_templates,'connection_value',side_effect=connection),
            patch.object(frappe,'enqueue'),patch.object(frappe,'publish_realtime')]
for boundary in patches: boundary.start()


def callback(method, values):
    raw = json.dumps(dict(values, account=account)).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), timestamp.encode()+b'.'+raw, hashlib.sha256).hexdigest()
    request = SimpleNamespace(get_data=lambda:raw,headers={'X-Relay-Timestamp':timestamp,'X-Relay-Signature':signature})
    with patch.object(frappe,'request',request):
        method()
    frappe.db.commit()


def drain():
    for name in frappe.get_all('Relay Hub Event',filters={'account':account,'projection_status':['in',['Pending','Uncategorized']]},pluck='name'):
        projection.project(name)
    frappe.db.commit()


def event(identifier, message):
    callback(inbound.receive, {'events':[{'id':identifier,'payload':{'entry':[{'changes':[{'field':'messages','value':{'messages':[message]}}]}]}}]})
    drain()


try:
    for dt in ('Relay Test Business','Relay Pending Receipt','Relay WhatsApp Template'):
        assert frappe.db.exists('DocType',dt), 'Fixture metadata is missing: '+dt
    if not frappe.db.exists('Relay Contact Type',{'business_doctype':'Relay Test Business'}):
        frappe.get_doc({'doctype':'Relay Contact Type','business_doctype':'Relay Test Business','enabled':1}).insert()
    businesses=[frappe.get_doc({'doctype':'Relay Test Business','title':'WA v1 local '+stamp+' '+str(i)}).insert() for i in range(2)]
    person=frappe.get_doc({'doctype':'Contact','first_name':'WA v1 local '+stamp,
        'phone_nos':[{'phone':'15550000001','is_primary_mobile_no':1}],
        'links':[{'link_doctype':b.doctype,'link_name':b.name} for b in businesses]}).insert()
    contact=frappe.get_doc({'doctype':'Relay Contact','contact':person.name,'display_name':'WA v1 local '+stamp}).insert()
    channel=frappe.get_doc({'doctype':'Relay Channel','channel':'WhatsApp','account':account,'enabled':1}).insert()
    frappe.get_doc({'doctype':'Relay Contact Endpoint','relay_contact':contact.name,'channel':channel.name,'endpoint':'15550000001','verified':1}).insert()
    frappe.db.commit()
    incoming={'id':'in-'+stamp,'from':'15550000001','type':'text','timestamp':str(int(time.time())),'text':{'body':'Order quantity 25'}}
    event(1,incoming)
    pending=enrollment.pending()['items']
    assert len(pending)==1 and pending[0]['ambiguous']
    assert not frappe.db.exists('Relay Message',{'provider_id':incoming['id']})
    enrollment.bind(pending[0]['event'],incoming['id'],contact.name,businesses[0].doctype,businesses[0].name)
    source=frappe.db.get_value('Relay Message',{'provider_id':incoming['id']},'name')
    assert source
    try:
        frappe.get_doc({'doctype':'Relay Hub Event','event_key':'forged-'+stamp,'account':account,'hub_event_id':'999','payload':'{}','flags':{'relay_authenticated_callback':True}}).insert(ignore_permissions=True)
        raise AssertionError('REST-style event insertion bypassed authentication')
    except frappe.PermissionError:
        frappe.db.rollback()
    print('PASS callback guard and manager ambiguity resolution',flush=True)

    hub=Mock()
    hub.call_tool.return_value={'delivery':{'state':'queued'}}
    with patch.object(whatsapp,'client',return_value=hub):
        result=whatsapp.send({'key':'first-'+stamp,'operation':'templates.send','arguments':{'name':'welcome','language':'en_US'},
            'contact':person.name,'business_doctype':businesses[1].doctype,'business_name':businesses[1].name})
    action=frappe.get_doc('Relay Message Action',result['action'])
    assert result['status']=='Queued' and json.loads(action.payload)['start']['business_name']==businesses[1].name
    provider='out-'+stamp
    receipt={'event_id':2,'position':0,'message_id':provider,'recipient':'15550000001','status':'read','timestamp':int(time.time())}
    callback(inbound.receive_statuses,{'statuses':[receipt]});drain()
    assert frappe.db.exists('Relay Pending Receipt',provider_key(channel.name,'15550000001',provider))
    callback(inbound.receive_channel_statuses,{'statuses':[{'id':3,'delivery_id':1,'request_key':action.request_key,
        'operation':'whatsapp.execute','state':'submitted','receipt':{'messages':[{'id':provider}]},'occurred_at':'2026-10-24T10:00:00Z'}]})
    drain();action.reload()
    outgoing=frappe.get_doc('Relay Message',action.outbound_message)
    assert action.status=='Submitted' and outgoing.status=='Read' and outgoing.business_name==businesses[1].name
    drain()
    assert frappe.db.count('Relay Message',{'source_key':action.request_key})==1
    print('PASS durable send, pushed outcome, early read receipt and replay deduplication',flush=True)

    cursor=api.messages(contact.name)['ingestion_cursor']
    reply=dict(incoming,id='reply-'+stamp,timestamp='100',context={'id':provider})
    event(4,reply)
    discovered=api.messages(contact.name,since=cursor)['items']
    assert len(discovered)==1 and discovered[0].provider_id==reply['id']
    assert frappe.db.get_value('Relay Message',discovered[0].name,'business_name')==businesses[1].name
    print('PASS verified reply ownership and late provider timestamp catch-up',flush=True)

    rows=[]
    for number in range(500):
        provider_id='burst-'+stamp+'-'+str(number)
        doc=frappe.get_doc({'doctype':'Relay Message','relay_contact':contact.name,'channel':channel.name,
            'business_doctype':businesses[0].doctype,'business_name':businesses[0].name,'direction':'Outgoing','status':'Sent',
            'content':'Local receipt load quantity '+str(number+1),'message_type':'text','sender_endpoint':'15550000001',
            'provider_id':provider_id,'provider_message_key':provider_key(channel.name,'15550000001',provider_id)}).insert(ignore_permissions=True)
        rows.append((doc.name,provider_id))
    frappe.db.commit()
    for batch in range(3):
        count=251 if batch==2 else 500
        statuses=[dict(receipt,event_id=10+batch,position=i,message_id=rows[i%500][1],status='read' if batch==2 else 'delivered') for i in range(count)]
        callback(inbound.receive_statuses,{'statuses':statuses});drain()
    states=frappe.get_all('Relay Message',filters={'name':['in',[row[0] for row in rows]]},pluck='status')
    assert states.count('Read')==251 and states.count('Delivered')==249
    print('PASS 1251 receipts in 500/500/251 batches across 500 messages',flush=True)
finally:
    frappe.db.rollback()
    for boundary in reversed(patches): boundary.stop()
    frappe.destroy()
