"""Permission-filtered business grouping. Claims never grant document access."""
import hashlib
import json
import frappe
from relay_core.business_inbox import check_type
from relay_core.permissions import require_access


def configuration(doctype):
    check_type(doctype)
    config = frappe.get_doc('Relay Contact Type', {'business_doctype': doctype, 'enabled': 1})
    field = config.get('grouping_field') or ''
    if field:
        meta = frappe.get_meta(doctype).get_field(field)
        if not meta or meta.fieldtype not in ('Link', 'Select', 'Data') or meta.permlevel:
            frappe.throw('Business grouping configuration is invalid')
    return field


def validate_text(value):
    if not isinstance(value, str) or len(value) > 140 or any(ord(c) < 32 for c in value):
        frappe.throw('Invalid group or search value')
    return value


def key(doctype, field, value):
    import json
    return hashlib.sha256(json.dumps([doctype,field,value]).encode()).hexdigest()


def group_filters(field, value):
    if value=='__all__':return []
    if not field:
        if value: frappe.throw('This business type has no grouping field')
        return []
    return [[field, '=', value]] if value else [[field, 'is', 'not set']]


@frappe.whitelist(methods=['GET'])
def directory(doctype, query='', after=None, include_all=0):
    field=configuration(doctype);validate_text(query)
    if after is not None:validate_text(after)
    if str(include_all) not in ('0','1'):frappe.throw('Invalid directory option')
    if not field:return {'field':'','items':[{'value':'','label':'All records'}],'next':None}
    filters=[]
    if query:filters.append([field,'like','%'+query.replace('%','\\%').replace('_','\\_')+'%'])
    if after is not None:filters.append([field,'>',after])
    rows=frappe.get_list(doctype,fields=[field],filters=filters,group_by=field,order_by=field+' asc',page_length=32)
    # MariaDB groups NULL and empty text separately. Relay presents both as one
    # Ungrouped bucket, so normalise before applying the visible page boundary.
    unique=[];seen=set()
    for row in rows:
        value=row.get(field) or ''
        if value in seen:continue
        seen.add(value);unique.append({'value':value,'label':value or 'Ungrouped'})
    page=unique[:30]
    next_cursor=page[-1]['value'] if page and (len(unique)>30 or len(rows)==32) else None
    if str(include_all)=='1' and after is None and not query:page.insert(0,{'value':'__all__','label':'All teams'})
    return {'field':field,'items':page,'next':next_cursor}


@frappe.whitelist(methods=['GET'])
def records(doctype, group='', query='', start=0):
    field=configuration(doctype);validate_text(group);validate_text(query)
    if isinstance(start,bool) or not str(start).isdigit() or not 0<=int(start)<=100000:frappe.throw('Invalid page')
    from frappe.desk.search import search_widget, build_for_autosuggest
    from frappe.utils import strip_html
    from html import unescape
    offset=int(start)
    rows=build_for_autosuggest(search_widget(doctype=doctype,txt=query,filters=group_filters(field,group),page_length=31,start=offset,ignore_user_permissions=False),doctype=doctype)
    linked_more=False
    if query.strip():
        contact_rows=build_for_autosuggest(search_widget(doctype='Contact',txt=query,page_length=31,start=offset,
            ignore_user_permissions=False),doctype='Contact')
        linked_more=len(contact_rows)>30
        contact_rows=contact_rows[:30]
        if contact_rows:
            contact_names=[row['value'] for row in contact_rows]
            labels={row['value']:unescape(strip_html(row.get('label') or row['value'])) for row in contact_rows}
            links=frappe.get_all('Dynamic Link',filters={'parenttype':'Contact','parentfield':'links',
                'parent':['in',contact_names],'link_doctype':doctype},fields=['parent','link_name'],limit_page_length=300)
            by_business={}
            for link in links:by_business.setdefault(link.link_name,[]).append(labels.get(link.parent,link.parent))
            candidates=list(by_business)
            if candidates:
                allowed=frappe.get_list(doctype,filters=group_filters(field,group)+[['name','in',candidates]],
                    fields=['name'],order_by='name asc',page_length=31)
                existing={row['value'] for row in rows}
                for allowed_row in allowed:
                    if allowed_row.name in existing:continue
                    rows.append({'value':allowed_row.name,'label':allowed_row.name,
                        'description':'Contact: '+', '.join(by_business[allowed_row.name][:3])})
    has_more=len(rows)>30 or linked_more
    rows=rows[:30]
    items=[]
    for row in rows[:30]:
        label=unescape(strip_html(row.get('label') or row['value']))
        description=unescape(strip_html(row.get('description') or '')).strip()
        for prefix in (label+', ',row['value']+', '):
            if description.casefold().startswith(prefix.casefold()):
                description=description[len(prefix):].strip();break
        items.append({'name':row['value'],'label':label,'description':description})
    names=[item['name'] for item in items]
    if names:
        activity=frappe.db.sql("""
            SELECT m.business_name,
                   SUM(CASE WHEN m.direction='Incoming' AND (s.last_read IS NULL OR m.name>s.last_read) THEN 1 ELSE 0 END) AS unread,
                   MAX(COALESCE(m.sent_at,m.creation)) AS last_activity
            FROM `tabRelay Message` m
            JOIN `tabRelay Channel` c ON c.name=m.channel AND c.channel='WhatsApp'
            LEFT JOIN `tabRelay Business Conversation State` s
              ON s.business_doctype=m.business_doctype AND s.business_name=m.business_name AND s.user=%(user)s
            WHERE m.business_doctype=%(doctype)s AND m.business_name IN %(names)s
            GROUP BY m.business_name
        """,{'user':frappe.session.user,'doctype':doctype,'names':tuple(names)},as_dict=True)
        latest=frappe.db.sql("""
            WITH ranked AS (
                SELECT m.business_name,m.content,COALESCE(m.sent_at,m.creation) AS last_activity,
                       ROW_NUMBER() OVER(PARTITION BY m.business_name ORDER BY COALESCE(m.sent_at,m.creation) DESC,m.name DESC) AS relay_rank
                FROM `tabRelay Message` m
                JOIN `tabRelay Channel` c ON c.name=m.channel AND c.channel='WhatsApp'
                WHERE m.business_doctype=%(doctype)s AND m.business_name IN %(names)s
            )
            SELECT business_name,content,last_activity FROM ranked WHERE relay_rank=1
        """,{'doctype':doctype,'names':tuple(names)},as_dict=True)
        summaries=frappe.get_all('Relay Conversation Summary',filters={'business_doctype':doctype,
            'business_name':['in',names],'status':'Ready'},fields=['business_name','result','modified'],
            order_by='modified desc',limit_page_length=300)
        activity_by={row.business_name:row for row in activity}
        latest_by={row.business_name:row for row in latest}
        summary_by={}
        for row in summaries:
            if row.business_name in summary_by:continue
            try:summary_by[row.business_name]=(json.loads(row.result) if isinstance(row.result,str) else row.result).get('overview','')
            except (TypeError,ValueError,AttributeError):summary_by[row.business_name]=''
        for item in items:
            current=activity_by.get(item['name'],{});recent=latest_by.get(item['name'],{})
            item.update(unread=int(current.get('unread') or 0),last_activity=str(recent.get('last_activity') or ''),
                last_message=(recent.get('content') or '')[:240],summary=summary_by.get(item['name'],'')[:500])
    claim=frappe.db.get_value('Relay Business Group Claim',key(doctype,field,group),'assigned_to') if items else None
    return {'items':items,'next':offset+30 if has_more else None,'assigned_to':claim,'user':frappe.session.user}


@frappe.whitelist(methods=['POST'])
def claim(doctype, group='', release=False):
    require_access();field=configuration(doctype);validate_text(group)
    if group=='__all__':frappe.throw('Choose one business team')
    if not frappe.get_list(doctype,filters=group_filters(field,group),fields=['name'],page_length=1):
        frappe.throw('No accessible records in this group',frappe.PermissionError)
    name=key(doctype,field,group)
    # The unique claim identity makes concurrent creation safe; row lock serialises transitions.
    if not frappe.db.exists('Relay Business Group Claim',name):
        frappe.db.savepoint('relay_group_create')
        try:
            frappe.get_doc({'doctype':'Relay Business Group Claim','claim_key':name,'business_doctype':doctype,'grouping_field':field,'group_value':group}).insert(ignore_permissions=True)
        except frappe.DuplicateEntryError:
            frappe.db.rollback(save_point='relay_group_create')
    owner=frappe.db.get_value('Relay Business Group Claim',name,'assigned_to',for_update=True)
    if owner and owner!=frappe.session.user:
        frappe.throw('This group is already handled by another user')
    if release not in (False,True,0,1):frappe.throw('Invalid release action')
    frappe.db.set_value('Relay Business Group Claim',name,'assigned_to',None if release else frappe.session.user)
    return {'assigned_to':None if release else frappe.session.user}


def responsible(contact,user):
    from relay_core.business_access import candidates
    for dt,name in candidates(contact):
        field=frappe.db.get_value('Relay Contact Type',{'business_doctype':dt,'enabled':1},'grouping_field') or ''
        value=frappe.db.get_value(dt,name,field) if field else ''
        if frappe.db.get_value('Relay Business Group Claim',key(dt,field,value or ''),'assigned_to')==user:return True
    return False


def responsibility_condition(user,contact_expression):
    clauses=[]
    for config in frappe.get_all('Relay Contact Type',filters={'enabled':1},fields=['business_doctype','grouping_field'],limit_page_length=200):
        dt=config.business_doctype;field=config.grouping_field or ''
        meta=frappe.get_meta(dt)
        if field and (not meta.get_field(field) or meta.get_field(field).fieldtype not in ('Link','Select','Data')):continue
        business=frappe.qb.DocType(dt);link=frappe.qb.DocType('Dynamic Link');relay=frappe.qb.DocType('Relay Contact');claim=frappe.qb.DocType('Relay Business Group Claim')
        from pypika.functions import Coalesce
        query=(frappe.qb.from_(relay).join(link).on((link.parent==relay.contact)&(link.parenttype=='Contact')&(link.parentfield=='links'))
            .join(business).on((business.name==link.link_name)&(link.link_doctype==dt))
            .join(claim).on((claim.business_doctype==dt)&(claim.grouping_field==field)&(claim.group_value==(Coalesce(business[field],'') if field else '')))
            .select(relay.name).where(claim.assigned_to==user))
        clauses.append(contact_expression+' IN ('+query.get_sql()+')')
    return '('+' OR '.join(clauses)+')' if clauses else '1=0'
