async (page) => {
 const browser=page.context().browser();
 const source=browser.contexts().flatMap(c=>c.pages()).find(p=>p.url().includes('yrp.site:8002/relay#/reports'));
 const ctx=await browser.newContext();await ctx.addCookies(await source.context().cookies('http://yrp.site:8002'));
 const p=await ctx.newPage();let retries=0,sends=0,completed=false;
 try {
  await p.route('**/api/method/relay_core.**',async route=>{
   const req=route.request(),method=req.url().split('relay_core.')[1].split('?')[0];let message={};
   if(method==='telegram.group_chats')message={configured:true,items:[{name:'RELAY-CE-0000000001',chat_id:-100100,label:'Retry fixture',contact:'RELAY-CON-0000000001',channel:'RELAY-CH-0000000001'}]};
   else if(method==='telegram.groups')message={result:{title:'Retry fixture',type:'supergroup'}};
   else if(method==='api.messages')message={items:[],has_more:false};
   else if(method==='telegram_delivery.pending')message={items:[...(!completed?[{action:'RELAY-MA-0000000001',status:'Rejected',error:'Connection rejected',args:{text:'Rejected original',reply_to:12,message_thread_id:7}}]:[]),{action:'RELAY-MA-0000000002',status:'Uncertain',args:{text:'Uncertain original'}}],next:null};
   else if(method==='messaging.retry'){
    retries++;if(req.postDataJSON().action!=='RELAY-MA-0000000001')throw Error('Wrong retry target');
    completed=true;message={action:'RELAY-MA-0000000003',status:'Submitted'};
   } else if(method==='telegram.send')sends++;
   await route.fulfill({json:{message}});
  });
  await p.goto('http://yrp.site:8002/relay#/groups');
  await p.getByRole('tab',{name:'Telegram',exact:true}).click();
  await p.getByLabel('Telegram group',{exact:true}).click();
    await p.getByRole('option').filter({hasText:'Retry fixture'}).click();
  const review=p.getByRole('button',{name:'Review retry',exact:true});await review.waitFor();
  if(await review.count()!==1||await p.getByRole('button',{name:'Check status',exact:true}).count()!==1)throw Error('Retry offered for uncertain action');
  await p.getByLabel('Message',{exact:true}).fill('New unsent draft');
  await review.click();await p.getByRole('button',{name:'Cancel retry',exact:true}).click();
  if(retries)throw Error('Review/cancel performed retry');
  await review.click();await p.getByRole('button',{name:'Retry rejected send',exact:true}).click();
  await p.getByText('Retry sent',{exact:true}).waitFor();
  if(retries!==1||sends||await p.getByLabel('Message',{exact:true}).inputValue()!=='New unsent draft')throw Error('Retry/draft isolation failed');
  if(await review.count())throw Error('Completed original failure still offered retry');
  return {fixture:true,reviewCancelWithoutSend:true,retries,sends,draftPreserved:true,uncertainCheckOnly:true};
 } finally {await p.unrouteAll({behavior:'wait'});await ctx.close();}
}
