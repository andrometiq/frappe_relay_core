export default async function testFlows(page,origin='http://127.0.0.1:18126'){
 const errors=[],saves=[],published=[],name='RELAY-FLOW-0000000001';let saved=null
 page.on('pageerror',e=>errors.push(e.message))
 await page.addInitScript(()=>{window.frappe={csrf_token:'synthetic-csrf-token',session:{user:'Administrator'}}})
 await page.route('**/api/method/**',async route=>{
  const request=route.request(),method=request.url().split('/').at(-1).split('?')[0];let result
  if(method==='relay_core.flows.service.directory')result={items:saved?[saved]:[],can_configure:true}
  else if(method==='relay_core.automation.settings.references'){
   const query=new Map((request.url().split('?')[1]||'').split('&').map(v=>v.split('=').map(decodeURIComponent)))
   const kind=query.get('kind');result=[{value:kind+'-fixture',label:kind+' fixture'}]
  }
  else if(method==='relay_core.flows.service.save'){
   const body=request.postDataJSON();saves.push({body,headers:request.headers()});saved={...body.values,name,nodes:JSON.stringify(body.values.nodes),published_version:saved?.published_version||null};result=saved
  }
  else if(method==='relay_core.flows.service.publish'){published.push(request.postDataJSON());saved.published_version='RELAY-FV-0000000001';result=saved}
  else if(method==='relay_core.flows.service.runs')result={items:[]}
  else throw Error('Unexpected '+method)
  return route.fulfill({json:{message:result}})
 })
 await page.goto(origin+'/relay#/flows');await page.getByRole('button',{name:'New flow',exact:true}).click()
 await page.getByLabel(/^Flow title/).fill('Support intake');await page.getByLabel(/^Slash command/).fill('/support')
 for(const [label,kind] of [['Channel','channel'],['Execution user','execution_user'],['Business type','business_doctype']])await page.getByLabel(label,{exact:true}).selectOption(kind+'-fixture')
 await page.getByRole('button',{name:'Add step',exact:true}).click();await page.getByLabel('Step 1 action',{exact:true}).selectOption('input')
 await page.getByLabel('Step 1 input name',{exact:true}).fill('age');await page.getByLabel('Step 1 input type',{exact:true}).selectOption('number');await page.getByLabel('Step 1 text',{exact:true}).fill('Enter your age')
 await page.getByRole('button',{name:'Add step',exact:true}).click();await page.getByLabel('Step 2 action',{exact:true}).selectOption('ticket');await page.getByLabel('Step 2 text',{exact:true}).fill('Support for age {{age}}')
 await page.getByRole('button',{name:'Save flow draft',exact:true}).click();await page.getByText('Draft saved. Publish to use these steps for new runs.',{exact:true}).waitFor()
 await page.getByRole('button',{name:'Publish saved version',exact:true}).click();await page.getByText('Saved version published. Enable the flow when ready.',{exact:true}).waitFor()
 if(saves.length!==1||saves[0].body.values.nodes[0].input_type!=='number'||saves[0].body.values.enabled!==0||published.length!==1||saves[0].headers['x-frappe-csrf-token']!=='synthetic-csrf-token')throw Error('Flow draft/publish contract changed')
 for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:900});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Overflow '+width)}
 if(errors.length)throw Error(errors.join('\n'))
 return {passed:true,visualSteps:true,typedInput:true,draftPublish:true,viewports:[320,390,768,1440]}
}
