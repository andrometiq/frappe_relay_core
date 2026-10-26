"""Installed Relay workspace. Authentication belongs to the hosting Frappe site."""
import json
from pathlib import Path
import frappe
from frappe.sessions import get_csrf_token
from relay_core.api import capabilities
from relay_core.permissions import require_access

no_cache = 1

def get_context(context):
    if frappe.session.user == 'Guest':
        frappe.local.flags.redirect_location = '/login?redirect-to=/relay'
        raise frappe.Redirect
    require_access()
    manifest = Path(frappe.get_app_path('relay_core', 'public', 'relay', '.vite', 'manifest.json'))
    if not manifest.is_file():
        frappe.throw('Build the Relay site frontend with npm run build:site before opening this workspace.')
    assets = json.loads(manifest.read_text())
    entry = assets['site.html']
    styles = entry.get('css', []) or ([assets['style.css']['file']] if 'style.css' in assets else [])
    context.update(no_cache=1, title='Relay Core',
        relay_script='/assets/relay_core/relay/' + entry['file'],
        relay_preloads=['/assets/relay_core/relay/' + assets[name]['file'] for name in entry.get('imports', [])],
        relay_styles=['/assets/relay_core/relay/' + name for name in styles],
        relay_csrf=get_csrf_token(), relay_user=frappe.session.user,
        relay_capabilities=frappe.as_json(capabilities(), indent=None),
        relay_site=frappe.local.site,
        relay_socket_port=frappe.conf.get('socketio_port',9000) if frappe.request and frappe.request.host.rsplit(':',1)[-1] == str(frappe.conf.get('webserver_port',8000)) else '')
    return context
