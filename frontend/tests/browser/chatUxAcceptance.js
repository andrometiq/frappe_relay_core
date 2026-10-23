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
 const rows=Array.from({length:240},(_,i)=>({name:'RELAY-MSG-'+String(i+1).padStart(10,'0'),channel:channels[i%3].value,content:'Fixture message '+(i+1),direction:'Incoming',status:'Sent',creation:'2026-09-24 07:'+String(Math.floor(i/60)).padStart(2,'0')+':'+String(i%60).padStart(2,'0'),provider_context:{provider:labels[i%3],subject:'Fixture email'},sender_endpoint:i%3===2?'fixture@example.invalid':'10001'}));
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
  else if(method==='messaging.pending_messages')result={items:[{name:'pending:RELAY-MA-9999999999',action:'RELAY-MA-9999999999',contact,scope:contact,channel:channels[0].value,provider_context:{provider:'Telegram'},direction:'Outgoing',content:'Recovered uncertain send',status:'Unconfirmed',creation:'2026-09-24 08:00:00',_pending:true},{name:'pending:RELAY-MA-9999999998',action:'RELAY-MA-9999999998',contact,scope:contact,channel:channels[2].value,provider_context:{provider:'Email'},direction:'Outgoing',content:'Durable email fixture',status:'Unconfirmed',creation:'2026-09-24 08:00:00',_pending:true}],next:null};
  else if(method==='messaging.reconcile')result={action:'RELAY-MA-9999999999',status:'Uncertain'};
  else if(method==='messaging.actions')result={items:[{name:'RELAY-MA-9999999997',operation:'email',status:'Rejected',preview:'Retry email fixture',creation:'2026-09-24 08:00:00',can_retry:true}],before:null};
  else if(method==='messaging.retry')result={action:'RELAY-MA-9999999996',status:'Submitted',message:'RELAY-MSG-0000000242'};
  else if(method==='messaging.reply_window')result={open:true};
  else if(method==='email_preferences.read')result={signature:''};
  else if(method==='messaging.canned_replies')result={items:[{name:'fixture',title:'Greeting',language:'English',body:'Hello from a saved reply.'},{name:'location-fixture',title:'Office location',language:'English',reply_type:'Location',latitude:13.0827,longitude:80.2707},{name:'contact-fixture',title:'Support contact',language:'English',reply_type:'Contact',contact_name:'Support desk',phone:'+919000000055'}]};
  else if(method==='messaging.send'){
   await p.waitForTimeout(900);const source=rows.find(r=>r.name===q.message);
   const msg={...source,name:'RELAY-MSG-0000000241',content:q.data.text,direction:'Outgoing',creation:'2026-09-24 08:00:00'};rows.push(msg);
   result={status:'Submitted',message:msg.name,action:'fixture-action'};
  } else if(method==='message_reads.mark')result={marked:JSON.parse(q.messages)};
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
 await p.goto('http://yrp.site:8002/relay#/messages');await p.bringToFront();
 await p.getByRole('button',{name:/Chat UX fixture/}).click();await p.getByRole('tab',{name:/Telegram/}).click();
 await p.getByRole('button',{name:'Check status',exact:true}).click();
 if(requests.filter(r=>r.method==='messaging.reconcile').length!==1 || requests.some(r=>r.method==='messaging.send'))throw Error('Pending recovery re-submitted or did not check receipt');
 const input=()=>p.getByRole('textbox',{name:'Message',exact:true});
 await input().fill('Telegram draft retained');const viewport=p.locator('.message-thread');
 await viewport.evaluate(n=>{n.scrollTop=n.scrollHeight/2;n.dispatchEvent(new Event('scroll'));});await p.waitForTimeout(500);
 const before=await viewport.evaluate(n=>n.scrollTop);
 await p.getByRole('tab',{name:/WhatsApp/}).click();await input().fill('WhatsApp draft retained');
 await p.getByRole('tab',{name:/Telegram/}).click();await p.waitForTimeout(100);
 const after=await viewport.evaluate(n=>n.scrollTop),draft=await input().inputValue();
 await p.getByRole('button',{name:'Saved replies',exact:true}).click();await p.getByRole('button',{name:/Office location/}).click();
 const savedLatitude=await p.getByRole('spinbutton',{name:'Latitude',exact:true}).inputValue();
 if(savedLatitude!=='13.0827')throw Error('Saved location did not prepare composer');
 await p.getByRole('button',{name:'Saved replies',exact:true}).click();await p.getByRole('button',{name:/Support contact/}).click();
 if(await p.getByRole('textbox',{name:'Contact name',exact:true}).inputValue()!=='Support desk')throw Error('Saved contact did not prepare composer');
 if(requests.some(r=>r.method==='messaging.send'))throw Error('Saved reply sent without review');
 await p.getByRole('button',{name:'Saved replies',exact:true}).click();await p.getByRole('button',{name:/Greeting/}).click();const canned=await input().inputValue();
 await input().press('Shift+Enter');const newline=await input().inputValue();
 await input().fill('Fixture Enter send');await input().press('Enter');await p.waitForTimeout(100);
 const sending=await p.getByText('Sending',{exact:true}).count();await p.waitForTimeout(1100);
 const sent=await p.locator('.conversation-bubble').filter({hasText:'Fixture Enter send'}).count();
 await p.getByRole('tab',{name:/Email/}).click();await p.getByRole('textbox',{name:'Email message',exact:true}).fill('Email draft retained');
 await p.getByRole('tab',{name:/Telegram/}).click();await p.getByRole('tab',{name:/Email/}).click();
 const emailDraft=await p.getByRole('textbox',{name:'Email message',exact:true}).inputValue();
 await p.getByRole('combobox',{name:'To',exact:true}).fill('accounts');await p.waitForTimeout(400);
 await p.getByRole('option',{name:'accounts@example.invalid',exact:true}).click();
 if(await p.getByRole('button',{name:'Remove accounts@example.invalid',exact:true}).count()!==1)throw Error('Recipient not selected');
 await p.getByRole('button',{name:'Email options',exact:true}).click();
 await p.getByRole('combobox',{name:'CC',exact:true}).fill('accounts');await p.waitForTimeout(400);
 await p.getByRole('option',{name:'accounts@example.invalid',exact:true}).click();
 await p.getByRole('tab',{name:/Telegram/}).click();await p.getByRole('tab',{name:/Email/}).click();
 if(await p.getByRole('button',{name:'Remove accounts@example.invalid',exact:true}).count()!==2)throw Error('Recipient draft lost on tab switch');
 if(!requests.some(r=>r.method==='email.recipient_options'&&r.query==='accounts'))throw Error('Recipient search did not reach API');

 await p.locator('button[title="Send via"]').click();
 await p.getByText('Telegram',{exact:true}).last().click();
 await p.getByRole('textbox',{name:'Message',exact:true}).fill('Keep this draft when cancelling attachment');
 await p.getByRole('button',{name:'Add attachment',exact:true}).click();
 const chooserPromise=p.waitForEvent('filechooser');
 await p.getByText('Photo',{exact:true}).click();
 const chooser=await chooserPromise;await chooser.setFiles([]);
 const cancelledDraft=await p.getByRole('textbox',{name:'Message',exact:true}).inputValue();
 if(cancelledDraft!=='Keep this draft when cancelling attachment')throw Error('Attachment cancellation lost text composer');

 await p.getByRole('tab',{name:/WhatsApp/}).click();await p.getByRole('button',{name:'Add attachment',exact:true}).click();await p.waitForTimeout(250);
 const whatsAppVoice=await p.getByText('Voice message',{exact:true}).count();await p.keyboard.press('Escape');
 await p.getByRole('button',{name:'Appearance',exact:true}).click();await p.getByText('Dark',{exact:true}).click();
 await p.waitForTimeout(250);await p.screenshot({path:'/tmp/relay-chat-ux-dark.png'});
 const dark=await p.locator('.message-thread').evaluate(n=>getComputedStyle(n).backgroundColor);
 await p.setViewportSize({width:390,height:844});await p.waitForTimeout(100);await p.screenshot({path:'/tmp/relay-chat-ux-mobile.png'});
 const overflow=await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
 await p.setViewportSize({width:1440,height:900});
 await p.getByRole('tab',{name:'Combined',exact:true}).click();
 const paging=[];
 for(let i=0;i<4;i++) {
  await viewport.evaluate(n=>{n.scrollTop=0;n.dispatchEvent(new Event('scroll'));});await p.waitForTimeout(400);
  paging.push(await viewport.evaluate(n=>({count:n.querySelectorAll('[data-message]').length,top:n.scrollTop,first:n.querySelector('[data-message]')?.dataset.message,last:[...n.querySelectorAll('[data-message]')].at(-1)?.dataset.message})));
 }
 const jump=await p.getByRole('button',{name:'Go to latest message',exact:true}).count();
 await viewport.evaluate(n=>{n.scrollTop=n.scrollHeight;n.dispatchEvent(new Event('scroll'));});await p.waitForTimeout(400);
 const newerWindow=await viewport.evaluate(n=>({count:n.querySelectorAll('[data-message]').length,top:n.scrollTop,last:[...n.querySelectorAll('[data-message]')].at(-1)?.dataset.message}));
 if(errors.length || before!==after || draft!=='Telegram draft retained' || !newline.endsWith('\n') || sending!==1 || sent!==1 || emailDraft!=='Email draft retained' || whatsAppVoice!==0 || overflow || requests.filter(r=>r.method==='messaging.send').length!==1 || paging.some(row=>row.count>150) || !jump || newerWindow.last!=='RELAY-MSG-0000000200')throw Error('Chat UX acceptance failed');
 await p.getByRole('tab',{name:/Email/}).click();
 await p.getByRole('textbox',{name:'Email message',exact:true}).fill('Optimistic email fixture');
 await p.getByRole('button',{name:'Send email',exact:true}).click();
 await p.waitForTimeout(100);
 if(!await p.locator('.pending-status').filter({hasText:'Sending'}).count())throw Error('Email sending bubble missing');
 await p.getByRole('tab',{name:/Telegram/}).click();
 await p.getByRole('textbox',{name:'Message',exact:true}).fill('Untouched Telegram draft');
 await p.waitForTimeout(1100);
 if(await p.getByRole('textbox',{name:'Message',exact:true}).inputValue()!=='Untouched Telegram draft')throw Error('Email response overwrote another draft');
 await p.getByRole('tab',{name:/Email/}).click();
 if(await p.getByRole('textbox',{name:'Email message',exact:true}).inputValue()!=='')throw Error('Sent email draft not cleared');
 if(requests.filter(r=>r.method==='email.send').length!==1)throw Error('Email sent more than once');
 await p.getByRole('textbox',{name:'Email message',exact:true}).fill('Uncertain email fixture');
 await p.getByRole('button',{name:'Send email',exact:true}).click();await p.waitForTimeout(150);
 const uncertain=p.locator('.conversation-bubble').filter({hasText:'Uncertain email fixture'});
 await uncertain.getByRole('button',{name:'Check status',exact:true}).click();await p.waitForTimeout(150);
 if(requests.filter(r=>r.method==='email.send').length!==2 || requests.filter(r=>r.method==='email.send_status').length!==1)throw Error('Status check repeated the send');
 if(await p.getByRole('textbox',{name:'Email message',exact:true}).inputValue()!=='Uncertain email fixture')throw Error('Unconfirmed send lost its draft');

 const emailSendsBeforeReload=requests.filter(r=>r.method==='email.send').length;
 await p.reload();await p.getByRole('button',{name:/Chat UX fixture/}).click();
 await p.getByRole('tab',{name:/Email/}).click();
 await p.locator('.conversation-bubble').filter({hasText:'Durable email fixture'}).getByRole('button',{name:'Check status',exact:true}).click();await p.waitForTimeout(150);
 if(requests.filter(r=>r.method==='email.send').length!==emailSendsBeforeReload)throw Error('Reload recovery sent email again');
 await p.locator('button[title="Conversation tools"]').click();
 await p.getByText('Message activity',{exact:true}).click();
 await p.getByRole('button',{name:'Review retry',exact:true}).click();
 await p.getByRole('button',{name:'Retry rejected send',exact:true}).click();await p.waitForTimeout(150);
 if(await p.getByText('Message status: Sent',{exact:true}).count()!==1 || requests.filter(r=>r.method==='messaging.retry').length!==1)throw Error('Reviewed retry did not show sent status');
 if(!requests.some(r=>r.method==='inbox.typing'&&String(r.message).startsWith('RELAY-MSG-')))throw Error('Typing request omitted verified source reference');
 return {typingSource:true,emailRetryReview:true,emailReloadRecovery:true,emailOptimistic:true,cancelledDraft,paging,jump,newerWindow,errors,before,after,draft,canned,newline,sending,sent,emailDraft,whatsAppVoice,dark,overflow,sendCalls:requests.filter(r=>r.method==='messaging.send').length,historyCalls:requests.filter(r=>r.method==='api.messages'),viewWrites:requests.filter(r=>r.method==='inbox.save_view').length};
 } finally {await p.unrouteAll({behavior:'wait'});await ctx.close();}
}
