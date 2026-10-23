"""Real loopback HTTP into Frappe with synthetic API credentials and signed receipts.
No provider or installed-site credentials are used. Records stay in the isolated DB.
"""
import hashlib,hmac,json,os,secrets,threading,time
from pathlib import Path
from unittest.mock import patch
from wsgiref.simple_server import make_server,WSGIRequestHandler
import requests
root=Path(__file__).resolve().parents[1];sites=root/'.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()==sites.resolve()
os.environ['SITES_PATH']=str(sites);os.chdir(sites)
import frappe
import frappe.app
from relay_core import inbound
from relay_core.automation import projection
frappe.init(site='relay-ai-test.local');assert frappe.conf.db_name=='relay_ai_test_20260922' and frappe.conf.db_port==18433
frappe.connect();frappe.set_user('Administrator');frappe.flags.mute_emails=True
stamp=str(time.time_ns());account='http-status-'+stamp;secret=secrets.token_hex(32)
api_key=secrets.token_hex(12);api_secret=secrets.token_hex(24)
user=frappe.get_doc({'doctype':'User','email':'relay-status-'+stamp+'@example.invalid','first_name':'Callback fixture','send_welcome_email':0,'roles':[{'role':'Relay Hub Service'}],'api_key':api_key,'api_secret':api_secret}).insert();frappe.db.commit()
class Quiet(WSGIRequestHandler):
 def log_message(self,*args):pass

def application(environ,start_response):
 environ['HTTP_X_FRAPPE_SITE_NAME']='relay-ai-test.local'
 return frappe.app.application(environ,start_response)
server=make_server('127.0.0.1',0,application,handler_class=Quiet);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
url=f'http://127.0.0.1:{server.server_port}/api/method/relay_core.inbound.receive_channel_statuses'
rows=[{'id':i+1,'delivery_id':i+1,'request_key':'fixture-'+str(i),'operation':'telegram.message','state':'submitted','receipt':{'message_id':i+1,'chat_id':123},'occurred_at':'2026-09-24T10:00:00Z'} for i in range(500)]
def send(data,auth=True,signature=True):
 raw=json.dumps(data,separators=(',',':')).encode();ts=str(int(time.time()));sig=hmac.new(secret.encode(),ts.encode()+b'.'+raw,hashlib.sha256).hexdigest()
 headers={'Content-Type':'application/json','X-Relay-Timestamp':ts,'X-Relay-Signature':sig if signature else '0'*64}
 if auth:headers['Authorization']='token '+api_key+':'+api_secret
 return requests.post(url,data=raw,headers=headers,timeout=20)
try:
 with patch.object(inbound,'connection_value',side_effect=lambda key: {'relay_hub_account':account,'relay_callback_secret':secret}.get(key)),patch.object(projection,'on_event'):
  payload={'account':account,'statuses':rows}
  for _ in range(2):
   response=send(payload)
   assert response.status_code==200,(response.status_code,response.text[:300])
   assert response.json()['message']=={'accepted':500}
  assert frappe.db.count('Relay Hub Event',{'account':account})==1
  for bad,auth,signature in [(payload,False,True),(payload,True,False),({'account':'other','statuses':rows},True,True),({'account':account,'statuses':rows+[dict(rows[-1],id=501)]},True,True)]:
   response=send(bad,auth=auth,signature=signature)
   assert response.status_code in (401,403),response.status_code
  assert frappe.db.count('Relay Hub Event',{'account':account})==1
  print('PASS real HTTP Frappe API-token auth, HMAC, 500-row durable acceptance, replay deduplication and rejection without writes')
finally:
 server.shutdown();server.server_close();thread.join(timeout=5)
 frappe.db.set_value('User',user.name,{'enabled':0,'api_key':None});frappe.db.commit();frappe.destroy()
