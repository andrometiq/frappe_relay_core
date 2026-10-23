"""Direct REST handlers against the existing isolated fixture; never reload schema.

Run with bench Python and RELAY_AUTOMATION_TEST_SITES pointing at the prepared
relay-ai-test.local sites directory. All fixture writes are rolled back.
"""
import json
import os
from pathlib import Path
import sys
import uuid
from unittest.mock import patch


def confine_writes(event, args):
    paths = []
    if event == 'open' and isinstance(args[0], (str, bytes)) and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
        paths = [args[0]]
    elif event in {'os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.rename'}:
        paths = args[:2] if event == 'os.rename' else args[:1]
    root = Path(__file__).resolve().parents[1]
    for path in paths:
        resolved = Path(os.fsdecode(path)).resolve()
        if not (resolved.is_relative_to(root) or resolved.is_relative_to('/tmp')):
            raise PermissionError('Test refuses filesystem writes outside this worktree and /tmp')


def main():
    sites = os.environ.get('RELAY_AUTOMATION_TEST_SITES')
    if not sites:
        raise SystemExit('Set RELAY_AUTOMATION_TEST_SITES to the prepared isolated fixture')
    sys.addaudithook(confine_writes)
    os.environ['FRAPPE_STREAM_LOGGING'] = '1'
    import frappe
    import relay_core
    assert Path(relay_core.__file__).resolve().parents[1] == Path(__file__).resolve().parents[1], 'Run with this worktree on PYTHONPATH'
    from frappe.api.v1 import read_doc, document_list
    frappe.init(site='relay-ai-test.local', sites_path=sites)
    assert frappe.conf.db_name == 'relay_ai_test_20260922', 'Refusing a non-test database'
    assert frappe.conf.db_host in ('127.0.0.1', 'localhost'), 'Refusing a remote database'
    frappe.connect()
    try:
        frappe.set_user('Administrator')
        frappe.flags.mute_emails = True
        for dt in ('Relay Test Business', 'Relay Business Event Delivery', 'Relay Automation Run'):
            assert frappe.db.exists('DocType', dt), f'Fixture needs orchestrator-installed {dt}'
        suffix = uuid.uuid4().hex[:12]
        user = f'local-ai-permissions-{suffix}@example.invalid'
        # No hooks or notifications for synthetic source/internal rows.
        def fixture(doctype, name, **values):
            doc = frappe.get_doc(dict(doctype=doctype, name=name, **values))
            doc.db_insert()
            return doc
        with patch.object(frappe, 'enqueue'), patch.object(frappe.db, 'commit', side_effect=AssertionError('Test must roll back')):
            frappe.get_doc(dict(doctype='User', email=user, first_name='Local AI permission test',
                send_welcome_email=0, roles=[dict(role='Relay Communication Manager')])).insert()
            own = fixture('Relay Test Business', f'Local AI own {suffix}', title=f'Local AI own {suffix}')
            other = fixture('Relay Test Business', f'Local AI other {suffix}', title=f'Local AI other {suffix}')
            frappe.get_doc(dict(doctype='User Permission', user=user, allow=own.doctype,
                for_value=own.name, apply_to_all_doctypes=1)).insert()
            source = fixture('Relay Message', f'RELAY-MSG-AIPERM-{suffix}', content='Balance request',
                business_doctype=other.doctype, business_name=other.name, direction='Incoming')
            run = fixture('Relay Automation Run', f'RELAY-AR-AIPERM-{suffix}', event_key=f'ai-perm-run-{suffix}',
                message=source.name, execution_user=user, status='Completed',
                decision=json.dumps({'reply': 'Other business balance is 4500'}))
            event = fixture('Relay Business Event Delivery', f'RELAY-BED-AIPERM-{suffix}',
                event_key=f'ai-perm-event-{suffix}', source_doctype=other.doctype, source_name=other.name,
                business_doctype=other.doctype, business_name=other.name,
                payload=json.dumps({'amount': 4500, 'business': other.name}))
            for actor in (user, 'Administrator'):
                frappe.set_user(actor)
                if actor == user:
                    assert own.has_permission('read'), 'Fixture manager must read their own business'
                    assert not other.has_permission('read'), 'Fixture manager must be denied the other business'
                for doc, field in ((run, 'decision'), (event, 'payload')):
                    frappe.local.form_dict = frappe._dict()
                    try:
                        result = read_doc(doc.doctype, doc.name)
                    except frappe.PermissionError:
                        assert actor == user
                    else:
                        assert actor == 'Administrator' and result.get(field) == doc.get(field)
                    frappe.local.form_dict = frappe._dict(fields=json.dumps(['name', field]),
                        filters=json.dumps({'name': doc.name}))
                    try:
                        rows = document_list(doc.doctype)
                    except frappe.PermissionError:
                        assert actor == user
                    else:
                        if actor == user:
                            assert rows == []
                        else:
                            assert len(rows) == 1 and rows[0][field] == doc.get(field)
            print('PASS direct REST GET/list deny the other-business manager; administrator reads non-zero fixtures')
    finally:
        frappe.db.rollback()
        frappe.destroy()


if __name__ == '__main__':
    main()
