"""Bounded, permission-filtered recent workspace activity; no provider requests."""
from collections import Counter
import frappe
from relay_core.permissions import require_access, readable_contact, can_configure


@frappe.whitelist(methods=['GET'])
def read():
    require_access()
    from relay_core.timeline import page_query
    from pypika.functions import Coalesce
    cutoff=frappe.utils.get_datetime(frappe.utils.add_days(frappe.utils.today(),-6))
    message=frappe.qb.DocType('Relay Message')
    query=page_query(['name','relay_contact','channel','direction','status','sent_at','creation'],{'legacy_source':['is','not set']},501)
    rows=query.where(Coalesce(message.sent_at,message.creation)>=cutoff).run(as_dict=True)
    visible=[];contacts={};channels={}
    for row in rows[:500]:
        if row.relay_contact not in contacts:
            try:readable_contact(row.relay_contact);contacts[row.relay_contact]=True
            except frappe.PermissionError:contacts[row.relay_contact]=False
        if row.channel not in channels:channels[row.channel]=frappe.get_doc('Relay Channel',row.channel).has_permission('read')
        if contacts[row.relay_contact] and channels[row.channel]:visible.append(row)
    dates=[str(frappe.utils.add_days(frappe.utils.today(),-i)) for i in reversed(range(7))]
    daily={date:{'incoming':0,'outgoing':0} for date in dates}
    for row in visible:
        date=str(row.sent_at or row.creation)[:10]
        if date in daily:daily[date][row.direction.lower()]+=1
    operations=None
    recovery=None
    if can_configure():
        from relay_core.operations import recovery_status
        recovery=recovery_status()
        from relay_core.settings import value
        def bounded(doctype,filters):
            names=frappe.get_all(doctype,filters=filters,pluck='name',limit_page_length=1001)
            return {'count':min(len(names),1000),'more':len(names)>1000}
        operations={
            'unlinked':bounded('Relay Hub Event',{'account':value('relay_hub_account'),'projection_status':'Uncategorized'}),
            'failed_events':bounded('Relay Hub Event',{'account':value('relay_hub_account'),'projection_status':'Failed'}),
            'uncertain':bounded('Relay Message Action',{'status':'Uncertain'}),
            'campaigns':bounded('Relay Campaign',{'status':['in',['Running','Paused','Cancelling']]}),
        }
    return {'generated_at':str(frappe.utils.now_datetime()),'days':7,'limit':500,'has_more':len(rows)>500,
            'count':len(visible),'failed_outgoing':sum(row.direction=='Outgoing' and row.status=='Failed' for row in visible),'conversations':len({row.relay_contact for row in visible}),
            'directions':dict(Counter(row.direction for row in visible)), 'statuses':dict(Counter(row.status for row in visible)),
            'daily':[{'date':date,**daily[date]} for date in dates],'operations':operations,'recovery':recovery}
