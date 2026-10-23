// UI-only fixture acceptance. No provider messages or site records are created.
async(page)=>{
 const browser=page.context().browser(),origin=browser.contexts().flatMap(c=>c.pages()).filter(p=>p.url().includes('yrp.site:8002/relay')).at(-1);
 const ctx=await browser.newContext({viewport:{width:1440,height:900}});await ctx.addCookies(await origin.context().cookies());
 const p=await ctx.newPage(),errors=[],creates=[];let draft;
 p.on('pageerror',e=>errors.push(e.message));
 try {
 await p.route('**/api/method/relay_core.**',async route=>{
  const r=route.request(),method=r.url().split('relay_core.')[1].split('?')[0];let result={};
  if(method==='api.capabilities')result={manage:true,configure:true};
  else if(method==='campaigns.directory')result={items:[],next:null};
  else if(method==='campaigns.channels')result=['WhatsApp','Telegram','Email'].map((channel,i)=>({name:'channel-'+i,channel,account:'fixture'}));
  else if(method==='api.business_types')result=['Customer'];
  else if(method==='api.business_records')result=[{name:'CUSTOMER-FIXTURE',label:'Campaign customer'}];
  else if(method==='campaigns.create'){const q=r.postDataJSON();creates.push(q);draft={...q,name:'RELAY-CAM-9999999999',status:'Draft',recipients:[],counts:{}};result={name:draft.name};}
  else if(method==='campaigns.read')result=draft;
  else if(method==='whatsapp.business_contacts')result={contacts:[],has_more:false};
  else if(method==='notifications.list')result={items:[]};
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({message:result})});
 });
 await p.goto('http://yrp.site:8002/relay#/campaigns');
 for(const [provider,id] of [['Telegram','channel-1'],['Email','channel-2']]){
  await p.getByRole('button',{name:'New campaign',exact:true}).click();
  await p.getByRole('textbox',{name:'Campaign title',exact:true}).fill(provider+' fixture');
  await p.getByRole('combobox',{name:'Channel',exact:true}).selectOption(id);
  await p.getByRole('combobox',{name:'Business record',exact:true}).fill('Campaign');
  await p.getByRole('option',{name:'Campaign customer',exact:false}).click();
  await p.getByRole('textbox',{name:'Message',exact:true}).fill(provider+' campaign body');
  if(provider==='Email')await p.getByRole('textbox',{name:'Subject',exact:true}).fill('Email subject');
  if(await p.getByRole('button',{name:'Load approved templates',exact:true}).count())throw Error('Non-WhatsApp campaign shows template controls');
  await p.locator('form button[type=submit]').click();
  await p.getByRole('heading',{name:provider+' fixture',exact:true}).waitFor();
 }
 if(creates[0].operation!=='telegram.send'||creates[1].operation!=='email.send'||creates[1].arguments.subject!=='Email subject')throw Error('Wrong channel campaign payload');
 await p.getByRole('button',{name:'Appearance',exact:true}).click();await p.getByText('Dark',{exact:true}).click();
 await p.setViewportSize({width:390,height:844});
 if(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile campaign overflow');
 if(errors.length)throw Error(errors.join(';'));
 return {createdProviders:creates.map(v=>v.operation),emailSubject:true,mobileOverflow:false,errors};
 }finally{await p.unrouteAll({behavior:'wait'});await ctx.close();}
}
