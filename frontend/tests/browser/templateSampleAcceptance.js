// Installed assets with fixture APIs. Does not upload to Meta or create templates.
async (page) => {
 const browser=page.context().browser();const source=browser.contexts().flatMap(c=>c.pages()).filter(p=>p.url().includes('yrp.site:8002/relay')).at(-1);
 const ctx=await browser.newContext();await ctx.addCookies(await source.context().cookies());const p=await ctx.newPage();const calls=[],errors=[];p.on('pageerror',e=>errors.push(e.message));
 try {
 await p.route('**/api/method/relay_core.**',async route=>{
  const req=route.request(),method=req.url().split('relay_core.')[1].split('?')[0];const args=req.method()==='POST'?req.postDataJSON():{};let result={items:[]};
  if(method==='whatsapp.connection')result={configured:true};
  if(method==='whatsapp.execute'){
   if(args.operation==='capabilities')result={templates:true};
   else if(args.operation==='templates.list')result={data:[]};
   else if(args.operation==='templates.media_upload'){calls.push(args);result={handle:'4:fixture-handle'}};
  }
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({message:result})});
 });
 await p.goto('http://yrp.site:8002/relay#/whatsapp');
 await p.getByRole('button',{name:'New template',exact:true}).click();
 await p.getByLabel('Header',{exact:true}).selectOption('DOCUMENT');
 await p.locator('input[type=file]').evaluate(input=>{const transfer=new DataTransfer();transfer.items.add(new File(['%PDF-1.7\nfixture'],'sample.pdf',{type:'application/pdf'}));input.files=transfer.files;input.dispatchEvent(new Event('change',{bubbles:true}));});
 await p.getByText('Sample uploaded: sample.pdf',{exact:true}).waitFor();
 await p.getByText('Use an existing sample handle',{exact:true}).click();
 if(await p.getByLabel('Sample media handle',{exact:true}).inputValue()!=='4:fixture-handle')throw Error('Handle missing');
 await p.getByLabel('Header',{exact:true}).selectOption('IMAGE');
 if(await p.getByLabel('Sample media handle',{exact:true}).inputValue()!=='')throw Error('Old sample retained for different header');
 if(calls.length!==1||calls[0].arguments.media_type!=='document')throw Error('Wrong upload request');
 if(errors.length)throw Error(JSON.stringify(errors));
 return {fixture:true,uploadRequests:calls.length,handlePopulated:true,formatChangeClearsHandle:true,errors};
 }finally{await p.unrouteAll({behavior:'wait'});await ctx.close()}
}
