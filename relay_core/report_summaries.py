"""Daily evidence-keyed summary reuse for background prepared reports."""
from collections import defaultdict
import hashlib
import frappe
from relay_core import summaries
from relay_core.automation.contracts import canonical


def chunks(rows):
    group=[];size=0
    for row in rows:
        item={'message':row['message'],'time':str(row['message_time']),'direction':row['direction'],'text':row['content']}
        length=len(canonical(item).encode())
        if length>36000:frappe.throw('A message exceeds the summary evidence limit. Use the full-message report for this range.')
        if group and (len(group)>=200 or size+length>36000):yield group;group=[];size=0
        group.append(item);size+=length
    if group:yield group


def daily(contact,channel,day,evidence):
    policy_name=frappe.db.get_value('Relay Automation Policy',{'channel':channel,'enabled':1,'allow_summary':1},'name')
    if not policy_name:frappe.throw('Enable summaries in the channel’s Desk AI policy before requesting a summary report')
    policy=frappe.get_doc('Relay Automation Policy',policy_name)
    key=hashlib.sha256(canonical(['daily-report',frappe.session.user,contact,channel,day,policy.name,str(policy.modified),summaries.digest(evidence)]).encode()).hexdigest()
    with frappe.cache.lock('relay-daily-summary:'+key,timeout=180,blocking_timeout=150):
        name=frappe.db.get_value('Relay Conversation Summary',{'request_key':key},'name')
        if name:
            doc=frappe.get_doc('Relay Conversation Summary',name)
            summaries.authorize(doc)
        else:
            doc=frappe.get_doc({'doctype':'Relay Conversation Summary','relay_contact':contact,'channel':channel,
                'policy':policy.name,'policy_version':str(policy.modified),'requested_by':frappe.session.user,
                'period':'Daily','summary_date':day,'status':'Pending','request_key':key,
                'sources':canonical([row['message'] for row in evidence]),'input_hash':summaries.digest(evidence)})
            summaries.authorize(doc);summaries.save(doc,new=True);frappe.db.commit()
        if doc.status == 'Failed' and (doc.attempts or 0) < 2:
            # A new report request may retry once under the existing budget and
            # permission checks. Never reset the attempt count or ready cache.
            doc.status = 'Pending'
            doc.reason = None
            summaries.save(doc)
            frappe.db.commit()
        if doc.status in ('Pending','Running'):
            summaries.process(doc.name)
        result=summaries.read(doc.name)
        if result['status']!='Ready' or result['stale']:
            frappe.throw('A daily summary could not be completed. Check its Desk AI policy, budget and source access.')
        return doc.name,result['result']


def summarize(rows):
    groups=defaultdict(list)
    for row in rows:groups[(row['relay_contact'],row['channel'],str(row['message_time'])[:10])].append(row)
    output=[]
    for (contact,channel,day),messages in sorted(groups.items(),key=lambda item:(item[0][2],item[0][0],item[0][1])):
        by_name={row['message']:row for row in messages}
        for index,evidence in enumerate(chunks(messages),1):
            name,result=daily(contact,channel,day,evidence)
            text=result['overview']
            if result['action_items']:text+='\n\nAction items:\n'+'\n'.join('• '+item for item in result['action_items'])
            if result['topics']:text+='\n\nTopics:\n'+'\n'.join(item['title']+' — '+', '.join(item['messages']) for item in result['topics'])
            sources=[row['message'] for row in evidence]
            first=by_name[sources[0]]
            output.append({**first,'message_time':day+' 00:00:00','message_type':'daily summary',
                'direction':'Summary','status':'AI generated','content':text,'attachments':'',
                'sources':sources,'source_count':len(sources),'source_references':', '.join(sources),'summary':name,'business_records':'; '.join(sorted({by_name[source]['business_records'] for source in sources})),
                'contact':first['contact']+' · Part '+str(index)+' · '+str(len(sources))+' messages'})
    return output
