"""Bounded communication reports, scoped to one readable business record."""
from collections import Counter
from html import escape
import frappe
from relay_core.business_inbox import messages


@frappe.whitelist(methods=['GET'])
def preview(doctype, name):
    page = messages(doctype, name, limit=100)
    rows = [{'name':row['name'], 'contact':row['contact_label'], 'channel':row['channel'],
             'direction':row['direction'], 'status':row['status'], 'created':str(row.get('sent_at') or row['creation']),
             'content':(row.get('content') or '')[:1000]} for row in page['items']]
    return {'business_doctype':doctype,'business_name':name,'generated_at':str(frappe.utils.now_datetime()),
            'limit':100,'has_more':page['has_more'],'messages':rows,'count':len(rows),
            'directions':dict(Counter(row['direction'] for row in rows)),
            'statuses':dict(Counter(row['status'] for row in rows))}


def pdf_bytes(report):
    from weasyprint import HTML
    def deny_fetch(url, *args, **kwargs):
        raise ValueError('Report resources must be embedded as plain text')
    esc=lambda value:escape(str(value or ''))
    rows=''.join('<tr>'+''.join('<td>'+esc(row[key])+'</td>' for key in ('created','contact','direction','status','content'))+'</tr>' for row in report['messages'])
    html='''<!doctype html><html><meta charset="utf-8"><style>
    @page {size:A4; margin:16mm} body{font-family:sans-serif;font-size:10pt}
    table{border-collapse:collapse;width:100%;table-layout:fixed}td,th{border:1px solid #ddd;padding:5px;overflow-wrap:anywhere;white-space:pre-wrap}
    th{text-align:left} tr{break-inside:avoid} h1{font-size:18pt}</style><body>'''
    html+='<h1>Communication report</h1><p>'+esc(report['business_doctype'])+' · '+esc(report['business_name'])+'</p>'
    html+='<p>Generated '+esc(report['generated_at'])+'. Latest accessible messages, limited to 100. This is not a complete account total.</p>'
    html+='<p>'+str(report['count'])+' messages in this report'+(' · Earlier messages exist.' if report['has_more'] else '.')+'</p>'
    html+='<table><thead><tr><th>Time</th><th>Contact</th><th>Direction</th><th>Status</th><th>Message</th></tr></thead><tbody>'+rows+'</tbody></table></body></html>'
    return HTML(string=html,url_fetcher=deny_fetch).write_pdf()


@frappe.whitelist(methods=['GET'])
def download(doctype, name):
    # Recompute access at download time; no public/stale report file is stored.
    from werkzeug.wrappers import Response
    return Response(pdf_bytes(preview(doctype,name)),content_type='application/pdf',headers={
        'Content-Disposition':'attachment; filename="relay-communication-report.pdf"',
        'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})


@frappe.whitelist(methods=['GET'])
def from_run(run):
    from relay_core.permissions import require_access
    from relay_core.messaging import readable_source
    require_access(manage=True)
    doc=frappe.get_doc('Relay Automation Run',run);doc.check_permission('read')
    readable_source(doc.message)
    scope=frappe.parse_json(doc.get('report_scope') or '{}')
    if not isinstance(scope,dict) or not scope.get('doctype') or not scope.get('name'):
        frappe.throw('This run has no report')
    return download(scope['doctype'],scope['name'])
