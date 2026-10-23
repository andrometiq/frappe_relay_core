async (page) => {
  const browser=page.context().browser();
  const source=browser.contexts().flatMap(c=>c.pages()).find(p=>p.url().startsWith('http://yrp.site:8002/relay#/reports'));
  const ctx=await browser.newContext();
  await ctx.addCookies(await source.context().cookies('http://yrp.site:8002'));
  const p=await ctx.newPage(), sends=[], searches=[];
  let release;
  try {
    await p.route('**/api/method/relay_core.**',async route=>{
      const req=route.request(), method=req.url().split('relay_core.')[1].split('?')[0];
      let message={};
      if(method==='telegram.group_chats')searches.push(decodeURIComponent(req.url().match(/[?&]query=([^&]*)/)?.[1]||''));
      if(method==='telegram.group_chats')message={configured:true,items:[{name:'RELAY-CE-0000000001',chat_id:-100100,label:'Composer fixture',contact:'RELAY-CON-0000000001',channel:'RELAY-CH-0000000001'}]};
      else if(method==='telegram.groups')message={result:{title:'Composer fixture',type:'supergroup'}};
      else if(method==='api.messages'||method==='telegram_delivery.pending')message={items:[],next:null,has_more:false};
      else if(method==='telegram.send'){
        sends.push(req.postDataJSON());
        await new Promise(resolve=>release=resolve);
        message={action:'RELAY-MA-0000000001',status:'Submitted'};
      }
      await route.fulfill({json:{message}});
    });
    await p.goto('http://yrp.site:8002/relay#/groups');
    await p.getByRole('tab',{name:'Telegram',exact:true}).click();
    await p.getByLabel('Telegram group',{exact:true}).click();
    await p.getByLabel('Telegram group',{exact:true}).pressSequentially('Com',{delay:50});
    await p.getByRole('option').filter({hasText:'Composer fixture'}).waitFor();
    const picker=p.getByLabel('Telegram group',{exact:true});
    await picker.dispatchEvent('keydown',{key:'Enter',isComposing:true,bubbles:true});
    if(await picker.getAttribute('aria-expanded')!=='true')throw Error('IME Enter selected a record');
    await picker.evaluate(node=>{
      node.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));
      node.value='த';node.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true}));
    });
    await p.waitForTimeout(400);
    if(searches.includes('த'))throw Error('Partial IME search sent');
    await picker.evaluate(node=>{
      node.value='தமிழ்';node.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}));
    });
    await p.getByRole('option').filter({hasText:'Composer fixture'}).click();
    const draft=p.getByLabel('Message',{exact:true});
    await draft.fill('First line');
    await draft.press('Shift+Enter');
    await draft.press('x');
    if(await draft.inputValue()!=='First line\nx')throw Error('Shift+Enter did not preserve multiline draft');
    await draft.dispatchEvent('keydown',{key:'Enter',code:'Enter',isComposing:true,bubbles:true});
    await draft.dispatchEvent('keydown',{key:'Enter',code:'Enter',keyCode:229,bubbles:true});
    await draft.dispatchEvent('keydown',{key:'Enter',code:'Enter',repeat:true,bubbles:true});
    await p.waitForTimeout(200);
    if(sends.length)throw Error('Composition or held Enter sent a message');
    const sent=p.waitForRequest(r=>r.url().includes('relay_core.telegram.send'));
    await draft.press('Enter');await sent;
    await draft.fill('Next unsent draft');
    await draft.press('Enter');
    if(sends.length!==1)throw Error('Busy composer submitted twice');
    release();
    await p.getByText('Message sent',{exact:true}).waitFor();
    if(await draft.inputValue()!=='Next unsent draft')throw Error('Delayed receipt erased next draft');
    if(sends[0].text!=='First line\nx'||!sends[0].request_key)throw Error('Wrong submitted content or missing durable key');
    if(searches.filter(Boolean).join(',')!=='Com,தமிழ்')throw Error('Group search was not debounced: '+JSON.stringify(searches));
    return {fixture:true,debouncedSearch:true,imeSearch:true,sends:sends.length,multiline:true,compositionGuard:true,repeatGuard:true,busyGuard:true,nextDraftPreserved:true};
  } finally {
    release?.();await p.unrouteAll({behavior:'wait'});await ctx.close();
  }
}
