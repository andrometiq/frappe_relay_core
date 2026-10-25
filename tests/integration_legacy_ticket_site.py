"""Legacy evidence tickets through real yrp.site HTTP; shared harness removes all fixtures."""
import json
from integration_ai_actions_site import main


def exercise(*, raw, actor, company, event, source, request, stamp, **kwargs):
    import frappe
    first, second, unrelated = [source(text) for text in (
        'Sim legacy order quantity 25, amount 1250', 'Sim legacy payment amount 250', 'Sim unrelated private amount 7500')]
    # Legacy tickets can link messages from different conversations, without
    # owning those messages' episode backlinks or carrying a company/business.
    frappe.db.set_value('Relay Message', second.name, 'conversation_key', 'sim-other-'+stamp)
    ticket = frappe.get_doc(dict(doctype='Relay Ticket', subject='Notification 1792867625249477656',
        category='Query', status='Open', assigned_to=actor.name,
        messages=[{'message':first.name}, {'message':second.name}])).insert()
    frappe.db.set_value('Relay Message', second.name, 'ticket', ticket.name)
    raw('Relay Automation Run', 'Legacy Run', event_key='sim-legacy-'+stamp, ticket=ticket.name,
        message=second.name, status='Completed', decision=json.dumps({'reply':'Sim private legacy journal'}))
    def get(method, **values):
        response=request('tickets.'+method, dict(name=ticket.name, **values), verb='GET')
        assert response.status_code == 200, (method,response.status_code,response.json.get('exc_type'))
        return response.json['message']
    detail=get('read')
    assert detail['subject']==ticket.subject and not detail['can_take_over']
    assert {row['message'] for row in detail['messages']}=={first.name,second.name}
    assert not detail['linked_drafts']
    page=get('transcript',limit=1)
    assert set(page)=={'items','next'} and page['next']
    next_page=get('transcript',limit=1,**page['next'])
    assert next_page['next'] is None
    items=page['items']+next_page['items']
    assert [item['name'] for item in items]==[first.name,second.name]
    assert [item['content'] for item in items]==[first.content,second.content]
    assert set(items[0])=={'name','content','direction','status','creation','sent_at','message_type','channel'}
    for method in ('ai_history','deliveries'):
        assert get(method)=={'items':[],'next':None}
    assert request('tickets.transcript',dict(name=ticket.name,after=unrelated.name),verb='GET').status_code==403
    for method in ('read','transcript','ai_history','deliveries'):
        response=request('tickets.'+method,dict(name=ticket.name),verb='GET',authenticated=False)
        assert response.status_code in (401,403) and response.json['exc_type']=='PermissionError'
        assert request('tickets.'+method,dict(name=ticket.name)).status_code==403
    for value in (0,101,'bad'):
        assert request('tickets.transcript',dict(name=ticket.name,limit=value),verb='GET').status_code==417
    # Business permission is checked on each linked message even though the
    # legacy ticket itself has no business field.
    other=raw('Supplier','Legacy Other Supplier',supplier_name='Sim Legacy Other Supplier '+stamp, supplier_type='Company')
    restriction=frappe.get_doc(dict(doctype='User Permission',user=actor.name,allow='Supplier',
        for_value=other.name,apply_to_all_doctypes=1)).insert()
    frappe.clear_cache(user=actor.name)
    for method in ('read','transcript','ai_history','deliveries'):
        response=request('tickets.'+method,dict(name=ticket.name),verb='GET')
        assert response.status_code==403 and response.json['exc_type']=='PermissionError', (method,response.status_code)
    frappe.delete_doc('User Permission',restriction.name);frappe.clear_cache(user=actor.name)
    # A partial historical scope also uses explicit evidence, never a broad
    # query for messages with a matching conversation or ticket backlink.
    frappe.db.set_value('Relay Ticket',ticket.name,'conversation_key',first.conversation_key)
    assert [item['name'] for item in get('transcript')['items']]==[first.name,second.name]
    assert not get('read')['can_take_over']
    assert not frappe.db.get_value('Relay Message',first.name,'ticket')
    # Check both configured titles and legacy account-derived fallback over HTTP.
    records=json.dumps([{'doctype':'Relay Channel','name':event.channel}])
    for title, expected in [('', 'WhatsApp'), ('WhatsApp Sim Action '+stamp, 'WhatsApp'),
                            ('Sim Human support', 'Sim Human support')]:
        frappe.db.set_value('Relay Channel',event.channel,'title',title)
        response=request('display.titles',dict(records=records),verb='GET')
        assert response.status_code==200 and response.json['message']=={'items':[
            {'doctype':'Relay Channel','name':event.channel,'title':expected}]}
    assert request('display.titles',dict(records=records),verb='GET',authenticated=False).status_code in (401,403)
    frappe.db.set_value('Relay Channel',event.channel,'title','')
    actor.append('roles',{'role':'System Manager'});actor.save()
    title='Local Legacy event 1792867625249477656'
    frappe.db.set_value('Relay AI Skill',event.name,dict(title=title,enabled=0,execution_policy='Ticket only'))
    event.reload();ticket.reload()
    response=request('tickets.directory',dict(assigned_to=actor.name),verb='GET')
    assert response.status_code==200 and ticket.name in [row['name'] for row in response.json['message']['items']], ('legacy directory',response.status_code)
    from integration_ticket_history_site import browser_site
    browser_site(actor,event,ticket,script='legacyTicketSite.mjs')
    assert frappe.db.get_value('Relay AI Skill',event.name,'title')==title

    print('PASS legacy HTTP detail/transcript/history/deliveries status and exact shape; linked-only mixed scopes; guest, method, limit, cursor and real business denial')


if __name__=='__main__':
    main(exercise)
