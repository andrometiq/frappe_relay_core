"""Read-only recovery readiness; a recent start is not a successful execution."""
import frappe
from relay_core.permissions import require_access

JOBS = {
 'relay_core.automation.service.recover':'AI reply recovery',
 'relay_core.automation.projection.recover':'Incoming event recovery',
 'relay_core.ticket_notifications.recover':'Ticket notification recovery',
 'relay_core.flows.service.recover':'Conversation flow recovery',
 'relay_core.messaging.recover':'Message receipt recovery',
 'relay_core.learning.service.recover':'Learning evaluation recovery',
 'relay_core.summaries.recover':'Summary recovery',
 'relay_core.campaigns.recover':'Campaign recovery',
 'relay_core.translations.recover':'Translation recovery',
}

@frappe.whitelist(methods=['GET'])
def recovery_status():
    require_access(manage=True)
    from frappe.utils.scheduler import is_scheduler_inactive
    inactive=bool(is_scheduler_inactive(verbose=False))
    reasons=[]
    for field,label in [('maintenance_mode','Site maintenance mode is enabled'),('pause_scheduler','Scheduler is paused'),('disable_scheduler','Scheduler is disabled in site configuration')]:
        if frappe.conf.get(field):reasons.append(label)
    if not frappe.get_system_settings('enable_scheduler'):reasons.append('Scheduler is disabled in System Settings')
    rows=frappe.get_all('Scheduled Job Type',filters={'method':['in',list(JOBS)]},fields=['name','method','stopped','last_execution'],limit_page_length=100)
    by_method={row.method:row for row in rows};items=[]
    now=frappe.utils.now_datetime()
    for method,label in JOBS.items():
        row=by_method.get(method)
        state='Missing'
        last=None
        if row:
            last=row.last_execution
            state='Stopped' if row.stopped else 'Never started' if not last else 'Overdue' if (now-frappe.utils.get_datetime(last)).total_seconds()>300 else 'Recently started'
            if last and not row.stopped:
                logs=frappe.get_all('Scheduled Job Log',filters={'scheduled_job_type':row.name},fields=['status','modified'],order_by='creation desc',limit_page_length=1)
                if logs and frappe.utils.get_datetime(logs[0].modified)>=frappe.utils.get_datetime(last):
                    if logs[0].status=='Failed':state='Failed'
                    elif logs[0].status=='Complete' and state=='Recently started':state='Completed recently'
        items.append({'label':label,'state':state,'last_started':str(last) if last else None})
    mode='Frappe scheduler'
    scoped=None
    if frappe.conf.get('relay_scoped_recovery_enabled'):
        mode='Relay-only recovery'
        scoped=frappe.cache.get_value('relay-scoped-recovery-heartbeat')
        inactive=not scoped or bool(frappe.conf.get('maintenance_mode'))
        reasons=[]
        if frappe.conf.get('maintenance_mode'):reasons.append('Site maintenance mode is enabled')
        elif not scoped:reasons.append('Relay recovery process has no recent heartbeat')
        elif scoped.get('state')!='running':reasons.append('Some Relay jobs need attention; check the job states below')
    return {'inactive':inactive,'mode':mode,'runtime':scoped,'reasons':reasons,'items':items,'checked_at':str(now)}
