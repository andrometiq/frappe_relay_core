"""Guarded flow persistence/replay/input/scope checks; all provider sends mocked."""
from site_labels import run_label
import os,time,json
from pathlib import Path
from unittest.mock import patch
import frappe
from relay_core.flows import service as flows
from relay_core import messaging
sites=Path(__file__).resolve().parents[1]/'.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()==sites.resolve()
os.chdir(sites);frappe.init(site='relay-ai-test.local');frappe.connect()
assert frappe.conf.db_name=='relay_ai_test_20260922' and frappe.conf.db_port==18433
frappe.set_user('Administrator');frappe.flags.mute_emails=True
run = run_label();actor='automation-test@example.invalid';business_type='Relay Inbox Simulation Business'
from frappe.permissions import add_permission
add_permission(business_type,'Relay Communication Manager',0);add_permission('Contact','Relay Communication Manager',0)
business=frappe.get_doc({'doctype':business_type,'title':'Flow '+run}).insert()
person=frappe.get_doc({'doctype':'Contact','first_name':'Flow '+run,'links':[{'link_doctype':business_type,'link_name':business.name}]}).insert()
contact=frappe.get_doc({'doctype':'Relay Contact','contact':person.name,'display_name':'Flow '+run}).insert()
channel=frappe.get_doc({'doctype':'Relay Channel','channel':'WhatsApp','account':'flow-'+run,'enabled':1}).insert()
endpoint=frappe.get_doc({'doctype':'Relay Contact Endpoint','channel':channel.name,'relay_contact':contact.name,'endpoint':'123456789','verified':1}).insert()
nodes=[{'id':'age','kind':'input','input_type':'number','variable':'age','text':'Enter your age'},
 {'id':'topic','kind':'topic','title':'Age {{age}}','text':'Collected age {{age}}'},
 {'id':'ticket','kind':'ticket','text':'Age {{age}}','category':'Support'},
 {'id':'reply','kind':'reply','text':'Saved {{age}}'},
 {'id':'handoff','kind':'handoff','text':'An agent will help next'}]
flow=flows.save({'title':'Flow '+run,'command':'/support','channel':channel.name,'execution_user':actor,'business_doctype':business_type,'enabled':0,'nodes':nodes})
flow=flows.publish(flow['name']);first_version=flow['published_version'];flow=flows.publish(flow['name']);assert flow['published_version']!=first_version
flows.save({'enabled':1,'template_button':'retailer_feedback_start'},flow['name']);frappe.db.commit()
queue=patch.object(frappe,'enqueue');queue.start()
sent=[];lose=False
real_send=flows.send

def fake_send(run,event,source,channel,text,key):
 global lose
 sent.append((text,key,source.name))
 if lose:lose=False;raise RuntimeError('Synthetic uncertain response')

def incoming(text):
 context={'provider':'WhatsApp','message_id':'wamid.'+str(time.time_ns())}
 doc=frappe.get_doc({'doctype':'Relay Message','relay_contact':contact.name,'channel':channel.name,'direction':'Incoming','content':text,
  'message_type':'text','status':'Sent','sender_endpoint':'123456789','provider_context':json.dumps(context)}).insert(ignore_permissions=True)
 frappe.db.commit();return doc

def event(message):return frappe.db.get_value('Relay Flow Event',{'message':message.name},'name')
try:
 with patch.object(messaging,'connection_value',return_value=channel.account),patch.object(flows,'send',side_effect=fake_send):
  source=incoming('/support');first=event(source);assert first
  button=frappe._dict(source.as_dict());button.content='Give feedback';button.message_data=json.dumps({'selection_id':'retailer_feedback_start','selection_type':'template_button'});button.provider_context=json.dumps({'provider':'WhatsApp','original_message_type':'button'})
  assert flows.matching(button)==flow['name']
  button.provider_context=json.dumps({'provider':'WhatsApp'});assert flows.matching(button) is None
  button.content='retailer_feedback_start';assert flows.matching(button) is None
  flows.process(first);flows.process(first)
  flow_run=frappe.db.get_value('Relay Flow Event',first,'run');assert frappe.db.get_value('Relay Flow Run',flow_run,'status')=='Waiting'
  assert len(sent)==1 and sent[0][0]=='Enter your age'
  bad=incoming('NaN');flows.process(event(bad));assert frappe.db.get_value('Relay Flow Run',flow_run,'step')==0
  valid=incoming('24');lose=True;flows.process(event(valid))
  assert frappe.db.get_value('Relay Flow Event',event(valid),'status')=='Pending'
  frappe.db.set_value('Relay Flow Event',event(valid),'next_attempt',frappe.utils.add_to_date(frappe.utils.now_datetime(),seconds=-1));frappe.db.commit()
  flows.process(event(valid));flows.process(event(valid))
  assert frappe.db.get_value('Relay Flow Run',flow_run,'status')=='Handoff'
  assert frappe.db.get_value('Relay Contact',contact.name,'automation_paused')==1
  assert len(frappe.get_all('Relay Ticket',filters={'source_action_key':flows.digest('flow-'+flow_run+'-ticket')},pluck='name'))==1
  topic=frappe.get_doc('Relay Conversation Topic',frappe.db.get_value('Relay Conversation Topic',{'relay_contact':contact.name},'name'))
  assert topic.title=='Age 24' and json.loads(topic.messages)==[source.name,valid.name]
  assert frappe.db.count('Relay Conversation Topic',{'relay_contact':contact.name})==1
  attempts=[row for row in sent if row[0]=='Saved 24'];assert len(attempts)==2 and attempts[0][1]==attempts[1][1]
  assert flows.responses(flow_run)['responses']==[{'field':'age','question':'Enter your age','answer':'24'}]
  print('PASS published versions, slash trigger, validated input, journal replay, idempotent ticket, collected response review and handoff')
  from relay_core.automation.service import takeover
  takeover(contact.name,paused=0);frappe.db.commit()
  source=incoming('/support');flows.process(event(source));flow_run=frappe.db.get_value('Relay Flow Event',event(source),'run')
  changed=incoming('31');flows.publish(flow['name']);frappe.db.commit();count=len(sent);flows.process(event(changed))
  assert len(sent)==count and frappe.db.get_value('Relay Flow Run',flow_run,'status')=='Cancelled'
  print('PASS republishing invalidates stale waiting runs before effects')
  source=incoming('/support');flows.process(event(source))
  revoked=incoming('42');frappe.db.set_value('Relay Contact Endpoint',endpoint.name,'verified',0);frappe.db.commit();count=len(sent)
  flows.process(event(revoked));assert len(sent)==count and frappe.db.get_value('Relay Flow Event',event(revoked),'status')=='Rejected'
  print('PASS WhatsApp endpoint revocation before effects')
  frappe.db.set_value('Relay Contact Endpoint',endpoint.name,'verified',1);frappe.db.commit()
  branching=[{'id':'age','kind':'input','input_type':'number','variable':'age','text':'Age for branch?'},
   {'id':'branch','kind':'condition','variable':'age','operator':'gte','value':'18','then':'delay','otherwise':'minor'},
   {'id':'delay','kind':'wait','seconds':60},{'id':'adult','kind':'reply','text':'Adult branch'},
   {'id':'done','kind':'end'},{'id':'minor','kind':'reply','text':'Minor branch'},{'id':'minor_done','kind':'end'}]
  flows.save({'nodes':branching},flow['name']);flows.publish(flow['name']);frappe.db.commit()
  start=incoming('/support');flows.process(event(start));answer=incoming('21');count=len(sent);flows.process(event(answer))
  pending=event(answer);assert frappe.db.get_value('Relay Flow Event',pending,'next_attempt')
  flows.process(pending);assert len(sent)==count,'A delayed step ran early'
  frappe.db.set_value('Relay Flow Event',pending,'next_attempt',frappe.utils.add_to_date(frappe.utils.now_datetime(),seconds=-1));frappe.db.commit()
  flows.process(pending);flows.process(pending)
  assert [item[0] for item in sent[count:]]==['Adult branch']
  start=incoming('/support');flows.process(event(start));answer=incoming('12');count=len(sent);flows.process(event(answer))
  assert [item[0] for item in sent[count:]]==['Minor branch']
  print('PASS answer branches, persisted delay, early-resume denial and terminal branch isolation')
  start=incoming('/support');flows.process(event(start));answer=incoming('21');flows.process(event(answer));old_run=frappe.db.get_value('Relay Flow Event',event(answer),'run')
  restart=incoming('/support');flows.process(event(restart));assert frappe.db.get_value('Relay Flow Run',old_run,'status')=='Cancelled'
  answer=incoming('12');count=len(sent);flows.process(event(answer));assert [item[0] for item in sent[count:]]==['Minor branch']
  print('PASS a new command cancels a delayed run without blocking the replacement conversation')
  bounded=[{'id':'quantity','kind':'input','input_type':'number','variable':'quantity','text':'How many?','minimum':1,'maximum':5,'integer_only':True},
   {'id':'colors','kind':'input','input_type':'multi_choice','variable':'colors','text':'Choose colors','choices':[{'label':'Red','value':'red'},{'label':'Blue','value':'blue'},{'label':'Green','value':'green'}]},
   {'id':'summary','kind':'reply','text':'Requested {{quantity}} in {{colors}}'},{'id':'end','kind':'end'}]
  flows.save({'nodes':bounded},flow['name']);flows.publish(flow['name']);frappe.db.commit()
  start=incoming('/support');flows.process(event(start));bad=incoming('6');flows.process(event(bad));current=frappe.db.get_value('Relay Flow Event',event(start),'run');assert frappe.db.get_value('Relay Flow Run',current,'step')==0
  answer=incoming('2');flows.process(event(answer));choices=incoming('1,3');flows.process(event(choices));assert sent[-1][0]=='Requested 2 in red, green'
  assert flows.responses(current)['responses'][1]['answer']==['red','green']
  print('PASS numeric bounds, whole-number validation, multiple choices and persisted response review')
  from relay_core.flows import actions
  handler_calls=[]
  def business_handler(**kwargs):
   handler_calls.append(kwargs)
   return {'saved':True}
  registered={'fixture.follow_up':{'method':'fixture.actions.follow_up','parameters':{'type':'object','properties':{'answer':{'type':'string'}},'required':['answer']},'replay_safe':True}}
  original_get_attr=frappe.get_attr
  def get_handler(path):
   return business_handler if path=='fixture.actions.follow_up' else original_get_attr(path)
  hook_values={**registered,'unsafe':dict(registered['fixture.follow_up'],replay_safe=False),'broken':dict(registered['fixture.follow_up'],parameters={'type':'object','required':['missing']}),'bad_path':dict(registered['fixture.follow_up'],method='os.system()')}
  with patch.object(frappe,'get_hooks',return_value=hook_values):
   assert set(actions.definitions())=={'fixture.follow_up'}
  with patch.object(actions,'definitions',return_value=registered),patch.object(frappe,'get_attr',side_effect=get_handler):
   action_nodes=[{'id':'answer','kind':'input','input_type':'text','variable':'answer','text':'Request?'},
    {'id':'business','kind':'action','action':'fixture.follow_up','arguments':{'answer':{'var':'answer'}}},
    {'id':'done','kind':'end'}]
   flows.save({'nodes':action_nodes},flow['name']);flows.publish(flow['name']);frappe.db.commit()
   start=incoming('/support');flows.process(event(start));answer=incoming('Catalogue');flows.process(event(answer));flows.process(event(answer))
   current=frappe.db.get_value('Relay Flow Event',event(start),'run')
   assert frappe.db.get_value('Relay Flow Run',current,'status')=='Completed'
   action_run=frappe.get_doc('Relay Flow Run',current)
   replay=actions.execute(action_run,action_nodes[1],{'answer':'Catalogue'},'flow-'+current+'-business')
   assert replay=={'saved':True} and len(handler_calls)==1
   assert handler_calls[0]['action_input']=={'answer':'Catalogue'} and handler_calls[0]['relay_contact']==contact.name
   try:actions.execute(action_run,action_nodes[1],{'answer':'Changed'},'flow-'+current+'-business')
   except ValueError:pass
   else:raise AssertionError('Changed replay accepted')
  print('PASS registered business action scope, typed input, durable result replay and changed-input rejection')
  joining=[{'id':'answer','kind':'input','variable':'answer','input_type':'text','text':'Join test?'},
   {'id':'branch','kind':'condition','variable':'answer','operator':'eq','value':'yes','then':'yes','otherwise':'no'},
   {'id':'yes','kind':'reply','text':'Yes branch','next':'finish'},
   {'id':'no','kind':'reply','text':'No branch'},
   {'id':'finish','kind':'end','text':'Thank you'}]
  flows.save({'nodes':joining},flow['name']);flows.publish(flow['name']);frappe.db.commit()
  start=incoming('/support');flows.process(event(start));answer=incoming('yes');count=len(sent);flows.process(event(answer));flows.process(event(answer))
  assert [row[0] for row in sent[count:]]==['Yes branch','Thank you']
  print('PASS explicit branch join skips unrelated steps and terminal message sends once')
  from essdee_partners_api.whatsapp_core_adapter.retailer_feedback_flow import feedback_graph
  from relay_core.flows.legacy_graph import convert
  from relay_core.flows.retailer import install_case_types
  install_case_types();frappe.db.commit()
  imported=convert(feedback_graph())
  flows.save({'nodes':imported['nodes']},flow['name']);flows.publish(flow['name']);frappe.db.commit()
  start=incoming('/support');flows.process(event(start));import_run=frappe.db.get_value('Relay Flow Event',event(start),'run')
  for reply in ['HAAN, SHURU KAREIN','A','4','5','3','1,2','HAAN','Synthetic retailer feedback','HAAN']:
   answer=incoming(reply)
   for attempt in range(4):
    flows.process(event(answer))
    if frappe.db.get_value('Relay Flow Event',event(answer),'status')!='Pending':break
  completed=frappe.get_doc('Relay Flow Run',import_run)
  assert completed.status=='Completed',completed.reason
  followups=frappe.get_all('Relay Case',filters={'source_flow':import_run},fields=['name','field_values','priority'])
  assert len(followups)==2
  assert all(json.loads(c.field_values)['categories']==['gym_vest','innerwear'] for c in followups)
  assert {c.priority for c in followups}=={'Normal','High'}
  topic=frappe.get_doc('Relay Conversation Topic',frappe.db.get_value('Relay Conversation Topic',{'relay_contact':contact.name,'title':'Retailer product feedback'},'name'))
  assert topic.status=='Resolved' and len(json.loads(topic.messages))==10
  assert sent[-1][0]=='Dhanyavaad. Aapka feedback record ho gaya hai.'
  print('PASS full converted26step retailer flow: consent, ratings, stable multichoice,2cases,topic10messages and finalreply')
  for replies,expected_cases,expected_topic in [(['stop'],0,None),(['later'],0,'Deferred retailer feedback'),(['yes','C','yes'],1,'Retailer stocking interest')]:
   start=incoming('/support');flows.process(event(start));branch_run=frappe.db.get_value('Relay Flow Event',event(start),'run')
   for reply in replies:
    answer=incoming(reply)
    for attempt in range(4):
     flows.process(event(answer))
     if frappe.db.get_value('Relay Flow Event',event(answer),'status')!='Pending':break
   assert frappe.db.get_value('Relay Flow Run',branch_run,'status')=='Completed'
   assert frappe.db.count('Relay Case',{'source_flow':branch_run})==expected_cases
   if expected_topic:
    found=frappe.db.get_value('Relay Conversation Topic',{'relay_contact':contact.name,'title':expected_topic},'name');assert found
    assert len(json.loads(frappe.get_doc('Relay Conversation Topic',found).messages))==len(replies)+1
  print('PASS converted retailer decline/defer/stocking branches complete with exactly their expected cases and topics')







finally:
 queue.stop();frappe.db.rollback();frappe.destroy()
