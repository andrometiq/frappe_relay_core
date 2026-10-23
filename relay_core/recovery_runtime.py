"""Opt-in Relay-only scheduler for a bench whose general scheduler is paused."""
import argparse
import json
import os
from pathlib import Path
import re
import time

import frappe
from relay_core.operations import JOBS

HEARTBEAT = 'relay-scoped-recovery-heartbeat'


def tick():
    if not frappe.conf.get('relay_scoped_recovery_enabled'):
        return {'state':'disabled'}
    if frappe.conf.get('maintenance_mode'):
        return {'state':'maintenance'}
    result={'state':'running','checked_at':str(frappe.utils.now_datetime()),'enqueued':0,'missing':0,'stopped':0,'errors':0}
    with frappe.cache.lock('relay-scoped-recovery-tick',timeout=55,blocking_timeout=1):
        rows=frappe.get_all('Scheduled Job Type',filters={'method':['in',list(JOBS)]},fields=['name','method','stopped'],limit_page_length=100)
        indexed={row.method:row for row in rows}
        for method in JOBS:
            row=indexed.get(method)
            if not row:result['missing']+=1;continue
            if row.stopped:result['stopped']+=1;continue
            try:
                if frappe.get_doc('Scheduled Job Type',row.name).enqueue():result['enqueued']+=1
                frappe.db.commit()
            except Exception:
                frappe.db.rollback();result['errors']+=1
        if result['missing'] or result['stopped'] or result['errors']:result['state']='attention'
        frappe.cache.set_value(HEARTBEAT,result,expires_in_sec=180)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sites-path',type=Path,required=True)
    parser.add_argument('--site',required=True)
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,139}',args.site):parser.error('Invalid site name')
    sites=args.sites_path.resolve()
    if not (sites/args.site/'site_config.json').is_file():parser.error('Site configuration not found')
    os.chdir(sites)
    while True:
        try:
            frappe.init(site=args.site);frappe.connect();frappe.set_user('Administrator')
            result=tick()
        except Exception:
            result={'state':'error'}
        finally:
            frappe.destroy()
        # No credentials, customer content or exception tracebacks in process logs.
        print(json.dumps(result),flush=True)
        if args.once:return 0 if result['state']=='running' else 1
        time.sleep(60)


if __name__=='__main__':
    raise SystemExit(main())
