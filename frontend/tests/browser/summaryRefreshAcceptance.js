// Run with the browser tool against an authenticated local review session. All Core APIs are fixtures; no provider send occurs.
async (page) => {
 const browser=page.context().browser();
 const original=browser.contexts().flatMap(c=>c.pages()).filter(p=>p.url().includes('yrp.site:8002/relay')).at(-1);
 const ctx=await browser.newContext({viewport:{width:1440,height:900}});
 await ctx.addCookies(await original.context().cookies());
 const p=await ctx.newPage(),errors=[],requests=[],views={};p.on('pageerror',e=>errors.push(e.message));
 try {
 const contact='RELAY-CON-9999999999',labels=['Telegram','WhatsApp','Email'];
 const channels=labels.map((label,i)=>({value:'RELAY-CH-'+String(i+1).padStart(10,'0'),label,unread:500}));
 const rows=[{name:'RELAY-MSG-0000000001',channel:channels[1].value,content:'Group receipt fixture',direction:'Outgoing',status:'Read',creation:'2026-09-24 07:00:00',provider_context:{provider:'WhatsApp',group_id:'fixture-group'},sender_endpoint:'fixture-group'}];
 await p.route('**/api/method/relay_core.**',async route=>{
  const req=route.request(),method=req.url().split('relay_core.')[1].split('?')[0];
  const q=req.method()==='POST'?req.postDataJSON():Object.fromEntries((req.url().split('?')[1]||'').split('&').filter(Boolean).map(v=>{const [k,...rest]=v.split('=');return [decodeURIComponent(k),decodeURIComponent(rest.join('=').replace(/\+/g,' '))]}));
  requests.push({method,message:q.message,query:q.query,channel:q.channel,after:q.after,before:q.before});let result={};
  if(['inbox.directory','api.contacts'].includes(method))result={items:[{name:contact,display_name:'Chat UX fixture',latest_preview:'Fixture history',unread:1500}],previous:null,next:null};
  else if(method==='api.conversation_channels')result={items:channels};
  else if(['inbox.read','inbox.update'].includes(method))result={unread:1500,assignment:{},can_assign:false};
  else if(method==='inbox.presence')result={users:[]};
  else if(method==='inbox.view_state')result=views[q.channel||'']||{};
  else if(method==='inbox.save_view'){views[q.channel||'']={name:q.message,offset:Number(q.offset),atBottom:!!q.at_bottom,channel:q.channel||''};result={saved:true};}
  else if(method==='api.messages'){
   let filtered=rows.filter(r=>!q.channel||r.channel===q.channel);
   if(q.before)filtered=filtered.filter(r=>r.name<q.before);if(q.after)filtered=filtered.filter(r=>r.name>q.after);
   const limit=Number(q.limit||50),items=q.after?filtered.slice(0,limit):filtered.slice(-limit);
   result={items,has_more:filtered.length>limit,first:items[0]?.name,last:items.at(-1)?.name};
  } else if(method==='api.message_context'){
   const filtered=rows.filter(r=>!q.channel||r.channel===q.channel),index=filtered.findIndex(r=>r.name===q.message),items=filtered.slice(Math.max(0,index-25),index+26);
   result={contact,items,first:items[0]?.name,last:items.at(-1)?.name,has_more:index>25,has_newer:index+26<filtered.length,anchor:q.message};
  } else if(method==='api.message_snapshots')result={items:rows.filter(r=>JSON.parse(q.names).includes(r.name))};
  else if(method==='messaging.pending_messages')result={items:[],next:null};
  else if(method==='unused_pending_fixture')result={items:[{name:'pending:RELAY-MA-9999999999',action:'RELAY-MA-9999999999',contact,scope:contact,channel:channels[0].value,provider_context:{provider:'Telegram'},direction:'Outgoing',content:'Recovered uncertain send',status:'Unconfirmed',creation:'2026-09-24 08:00:00',_pending:true},{name:'pending:RELAY-MA-9999999998',action:'RELAY-MA-9999999998',contact,scope:contact,channel:channels[2].value,provider_context:{provider:'Email'},direction:'Outgoing',content:'Durable email fixture',status:'Unconfirmed',creation:'2026-09-24 08:00:00',_pending:true}],next:null};
  else if(method==='messaging.reconcile')result={action:'RELAY-MA-9999999999',status:'Uncertain'};
  else if(method==='messaging.actions')result={items:[{name:'RELAY-MA-9999999997',operation:'email',status:'Rejected',preview:'Retry email fixture',creation:'2026-09-24 08:00:00',can_retry:true}],before:null};
  else if(method==='messaging.retry')result={action:'RELAY-MA-9999999996',status:'Submitted',message:'RELAY-MSG-0000000242'};
  else if(method==='messaging.reply_window')result={open:true};
  else if(method==='email_preferences.read')result={signature:''};
  else if(method==='messaging.canned_replies')result={items:[{name:'fixture',title:'Greeting',language:'English',body:'Hello from a saved reply.'},{name:'location-fixture',title:'Office location',language:'English',reply_type:'Location',latitude:13.0827,longitude:80.2707},{name:'contact-fixture',title:'Support contact',language:'English',reply_type:'Contact',contact_name:'Support desk',phone:'+919000000055'}]};
  else if(method==='summaries.options')result=[{value:'one',label:'Telegram'},{value:'two',label:'WhatsApp'}];
  else if(method==='summaries.latest')result={summary:{name:'summary',status:'Pending',period:'30',message_count:2,creation:'2026-09-24'}};
  else if(method==='summaries.read')result={name:'summary',status:'Ready',period:'30',message_count:2,creation:'2026-09-24',result:{overview:'Completed summary fixture',action_items:[],topics:[]}};
  else if(method==='messaging.send'){
   await p.waitForTimeout(900);const source=rows.find(r=>r.name===q.message);
   const msg={...source,name:'RELAY-MSG-0000000241',content:q.data.text,direction:'Outgoing',creation:'2026-09-24 08:00:00'};rows.push(msg);
   result={status:'Submitted',message:msg.name,action:'fixture-action'};
  } else if(method==='delivery_receipts.directory')result={items:Array.from({length:q.after?4:50},(_,i)=>({name:String(i),participant:'91900000'+i,status:i?'Delivered':'Read',provider_timestamp:'1790232000'})),next:q.after?null:'a'.repeat(64)};
  else if(method==='message_reads.coverage')result={read_by:[],unread_by:[],read:0};
  else if(method==='message_reads.mark')result={marked:JSON.parse(q.messages)};
  else if(method==='email.send') {
   if(q.body==='Uncertain email fixture'){await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({exception:'Simulated lost response'})});return;}
   await p.waitForTimeout(900);
   const source=rows.find(r=>r.name===q.message),msg={...source,name:'RELAY-MSG-0000000242',content:q.body,direction:'Outgoing'};
   rows.push(msg);result={message:msg.name,sent:true};
  }
  else if(method==='email.send_status')result={status:'Unconfirmed'};
  else if(method==='email.recipient_options')result=[{value:'accounts@example.invalid',label:'accounts@example.invalid'}];
  else if(method==='notifications.list')result={items:[]};
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({message:result})});
 });
 await p.goto('http://yrp.site:8002/relay#/messages');
 await p.getByRole('button',{name:/Chat UX fixture/}).click();
 await p.getByRole('button',{name:'Conversation summary',exact:true}).click();
 const panel=p.getByRole('complementary',{name:'Conversation summary'});
 await panel.getByText('Preparing your summary…',{exact:true}).waitFor();
 await panel.getByLabel('Channel',{exact:true}).selectOption('two');await panel.getByLabel('Period',{exact:true}).selectOption('7');
 await p.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
 await panel.getByText('Completed summary fixture',{exact:true}).waitFor();
 if(await panel.getByLabel('Channel',{exact:true}).inputValue()!=='two'||await panel.getByLabel('Period',{exact:true}).inputValue()!=='7')throw Error('Refresh reset summary choices');
 if(requests.some(r=>r.method==='summaries.generate')||errors.length)throw Error(JSON.stringify({errors,generated:true}));
 const colors=[];for(const dark of [false,true]){await p.evaluate(dark=>document.documentElement.setAttribute('data-theme',dark?'dark':'light'),dark);colors.push(await panel.evaluate(el=>getComputedStyle(el).backgroundColor));}
 if(colors[0]===colors[1])throw Error('Summary theme unchanged');
 return {fixture:true,pendingToReady:true,choicesPreserved:true,generationRequests:0,colors,errors};
 }finally{await p.unrouteAll({behavior:'wait'});await ctx.close();}
}
