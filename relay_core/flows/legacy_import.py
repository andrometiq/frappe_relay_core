"""Copy WhatsApp Core flow definitions and their versions into Relay flows.

Imported flows stay disabled: an owner reviews the steps, registers any business actions and enables the flow.
A re-run never changes a flow that already exists; it only adds versions that are still missing.
"""
import json
import re

import frappe
from relay_core.automation.service import internal_save
from relay_core.flows.contracts import definition
from relay_core.flows.legacy_graph import convert
from relay_core.flows.service import COMMAND, digest, missing_actions

FLOW = 'tabWhatsApp Core Flow'
VERSION = 'tabWhatsApp Core Flow Version'


def triggers(rows):
    """Old graph triggers as Relay flow fields: one command, keywords and one template button."""
    commands = [row['match'] for row in rows if row.get('type') == 'command']
    buttons = [row['match'] for row in rows if row.get('type') == 'template_button']
    words = [row['match'] for row in rows if row.get('type') == 'inbound_pattern']
    other = [row.get('type') for row in rows if row.get('type') not in ('command', 'template_button', 'inbound_pattern')]
    if other or len(commands) > 1 or len(buttons) > 1 or any(not isinstance(value, str) for value in commands + buttons + words):
        raise ValueError('Triggers need manual setup: ' + ', '.join(map(str, other or commands + buttons)))
    if commands and not re.fullmatch(COMMAND, commands[0]):
        raise ValueError('Command ' + commands[0] + ' is not a Relay slash command')
    if any(set(word) & set('*?[]') for word in words):
        raise ValueError('Pattern keywords need manual setup')
    return {'command': commands[0] if commands else None, 'keywords': '\n'.join(words), 'template_button': buttons[0] if buttons else ''}


def only(doctype, filters, field, option):
    rows = frappe.get_all(doctype, filters=filters, pluck=field, limit_page_length=2)
    if len(rows) != 1:
        frappe.throw(f'Choose {option}: this site has {len(rows) or "no"} matching {doctype} records')
    return rows[0]


class FlowImporter:
    def __init__(self, source, site_label, channel=None, execution_user=None, business_doctype=None, dry_run=False):
        self.source, self.site_label, self.dry_run = source, site_label, dry_run
        self.channel = channel or only('Relay Channel', {'channel': 'WhatsApp', 'enabled': 1}, 'name', '--channel')
        self.business_doctype = business_doctype or only('Relay Contact Type', {'enabled': 1}, 'business_doctype', '--business-doctype')
        if not execution_user:
            frappe.throw('Choose --execution-user: a Relay Communication Manager who is not a System Manager')
        self.execution_user = execution_user
        self.result = {'flows': [], 'failures': []}

    def run(self):
        rows = self.source.sql(f'SELECT name, title, status, enabled, active_version, draft_graph FROM `{FLOW}` ORDER BY creation, name')
        for flow in rows:
            try:
                self.result['flows'].append(self.import_flow(flow))
                frappe.db.commit()
            except Exception as exc:
                frappe.db.rollback()
                self.result['failures'].append({'flow': flow.name, 'title': flow.title, 'error': f'{type(exc).__name__}: {exc}'})
        return self.result

    def versions(self, flow):
        rows = self.source.sql(f'SELECT name, version_number, status, graph FROM `{VERSION}` WHERE flow=%s ORDER BY version_number, name', (flow.name,))
        converted, skipped = [], []
        for row in rows:
            try:
                converted.append((row, convert(json.loads(row.graph))))
            except (ValueError, TypeError) as exc:
                if row.name == flow.active_version:
                    raise
                skipped.append({'version': row.version_number, 'error': str(exc)})
        return converted, skipped

    def import_flow(self, flow):
        key = self.site_label + ':' + flow.name
        versions, skipped = self.versions(flow)
        current = next((graph for row, graph in versions if row.name == flow.active_version), None)
        if current is None:
            current = convert(json.loads(flow.draft_graph or '{}'))
        fields = triggers(current['triggers'])
        report = {'flow': flow.name, 'title': flow.title, 'source_status': flow.status, 'versions': len(versions),
                  'skipped_versions': skipped, 'missing_actions': missing_actions(current['nodes']), **fields}
        name = frappe.db.get_value('Relay Flow', {'legacy_key': key}, 'name')
        report['status'] = 'exists' if name else 'new'
        if self.dry_run:
            return report
        doc = frappe.get_doc('Relay Flow', name) if name else self.create(flow, key, current, fields)
        added = {row.name: self.add_version(doc, key, row, graph) for row, graph in versions}
        published = added.get(flow.active_version)
        if published and not doc.published_version:
            doc.published_version = published[0]
            internal_save(doc)
        report.update(relay_flow=doc.name, versions_added=sum(created for _, created in added.values()))
        return report

    def create(self, flow, key, current, fields):
        doc = frappe.get_doc({'doctype': 'Relay Flow', 'title': (flow.title or flow.name)[:140], 'channel': self.channel,
                              'execution_user': self.execution_user, 'business_doctype': self.business_doctype,
                              'enabled': 0, 'nodes': json.dumps(definition(current['nodes'])), 'legacy_key': key, **fields})
        return internal_save(doc, new=True)

    def add_version(self, doc, key, row, graph):
        """(Relay version name, whether this run created it)."""
        legacy = key + ':v' + str(row.version_number)
        existing = frappe.db.get_value('Relay Flow Version', {'legacy_version': legacy}, 'name')
        if existing:
            return existing, False
        data = {'nodes': json.dumps(graph['nodes']), 'channel': doc.channel, 'execution_user': doc.execution_user,
                'business_doctype': doc.business_doctype, 'template_button': doc.template_button}
        version = frappe.get_doc({'doctype': 'Relay Flow Version', 'flow': doc.name, 'legacy_version': legacy,
                                  'definition_hash': digest(json.dumps(data, sort_keys=True)), **data})
        return internal_save(version, new=True).name, True
