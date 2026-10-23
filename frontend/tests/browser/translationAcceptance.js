// Run with the browser tool against an authenticated local review session. All Core APIs are fixtures; no provider send occurs.
async (page) => {
 const browser=page.context().browser();
 const original=browser.contexts().flatMap(c=>c.pages()).filter(p=>p.url().includes('yrp.site:8002/relay')).at(-1);
 const ctx=await browser.newContext({viewport:{width:1440,height:900}});
 await ctx.addCookies(await original.context().cookies());
 const p=await ctx.newPage(),errors=[],requests=[],views={};p.on('pageerror',e=>errors.push(e.message));
 try {
 const contact='RELAY-CON-9999999999',labels=['Telegram','WhatsApp','Email'];
 const channels=labels.map((label,i)=>({value:'RELAY-CH-'+String(i+1).padStart(10,'0'),label,unread:500,translation_enabled:true}));
 const rows=Array.from({length:240},(_,i)=>({name:'RELAY-MSG-'+String(i+1).padStart(10,'0'),channel:channels[i%3].value,content:i===237?'வணக்கம் original':'Fixture message '+(i+1),direction:'Incoming',status:'Sent',creation:'2026-09-24 07:'+String(Math.floor(i/60)).padStart(2,'0')+':'+String(i%60).padStart(2,'0'),provider_context:{provider:labels[i%3],subject:'Fixture email'},sender_endpoint:i%3===2?'fixture@example.invalid':'10001'}));
 await p.route('**/api/method/relay_core.**',async route=>{
  const req=route.request(),method=req.url().split('relay_core.')[1].split('?')[0];
  const q=req.method()==='POST'?req.postDataJSON():Object.fromEntries((req.url().split('?')[1]||'').split('&').filter(Boolean).map(v=>{const [k,...rest]=v.split('=');return [decodeURIComponent(k),decodeURIComponent(rest.join('=').replace(/\+/g,' '))]}));
  requests.push({method,channel:q.channel,after:q.after,before:q.before});let result={};
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
  else if(method==='message_derivatives.translation')result={available:true,status:'completed',text:'Hello <script>literal text</script>',language:'ta',target_language:'en',provenance:{provider:'Fixture provider',model:'fixture-model',created_at:'2026-09-24 11:00:00'}};
  else if(method==='messaging.reply_window')result={open:true};
  else if(method==='email_preferences.read')result={signature:''};
  else if(method==='messaging.canned_replies')result={items:[{name:'fixture',title:'Greeting',language:'English',body:'Hello from a saved reply.'}]};
  else if(method==='messaging.send'){
   await p.waitForTimeout(900);const source=rows.find(r=>r.name===q.message);
   const msg={...source,name:'RELAY-MSG-0000000241',content:q.data.text,direction:'Outgoing',creation:'2026-09-24 08:00:00'};rows.push(msg);
   result={status:'Submitted',message:msg.name,action:'fixture-action'};
  } else if(method==='message_reads.mark')result={marked:JSON.parse(q.messages)};
  else if(method==='notifications.list')result={items:[]};
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({message:result})});
 });
 await p.goto('http://yrp.site:8002/relay#/messages');await p.bringToFront();
 await p.getByRole('button',{name:/Chat UX fixture/}).click();await p.getByRole('tab',{name:/Telegram/}).click();
 const input=()=>p.getByRole('textbox',{name:'Message',exact:true});
 const message=p.locator('[data-message="RELAY-MSG-0000000238"]');
 await message.getByRole('button',{name:'View in English',exact:true}).click();
 const panel=message.getByRole('region',{name:'English translation'});
 await panel.waitFor();await p.waitForTimeout(150);
 const text=await panel.innerText(),originalHidden=await message.getByText('வணக்கம் original',{exact:true}).count()===0;
 const scripts=await panel.locator('script').count();
 await message.getByRole('button',{name:'View original',exact:true}).click();
 const restored=await message.getByText('வணக்கம் original',{exact:true}).count();
 if(errors.length||!text.includes('Hello <script>literal text</script>')||!originalHidden||scripts||restored!==1)throw Error('Translation view acceptance failed');
 return {errors,text,originalHidden,scripts,restored,apiCalls:requests.filter(r=>r.method==='message_derivatives.translation').length};
 } finally {await ctx.close();}
}
