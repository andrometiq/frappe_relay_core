export default async function testPolicies(page,origin='http://127.0.0.1:18126'){
 const requests=[],errors=[],saves=[];let fail=true
 page.on('pageerror',error=>errors.push(error.message))
 await page.addInitScript(()=>{window.frappe={csrf_token:'synthetic-csrf-token',session:{user:'Administrator'}}})
 await page.route('**/api/method/**',async route=>{
  const request=route.request(),method=request.url().split('/').at(-1).split('?')[0];let data
  if(method==='relay_core.settings.connection')data={can_configure:true}
  else if(method==='relay_core.automation.settings.providers'||method==='relay_core.automation.settings.policies')data={items:[],next:null}
  else if(method==='relay_core.automation.settings.references'){
   const params=new URL(request.url()).searchParams,kind=params.get('kind');requests.push({kind,query:params.get('query')})
   data=[{value:kind+'-fixture',label:kind+' fixture'}]
  }
  else if(method==='relay_core.automation.settings.save_policy'){
   saves.push({body:request.postDataJSON(),headers:request.headers()})
   if(fail)return route.fulfill({status:403,json:{exc:'PermissionError'}})
   data={name:'policy-fixture'}
  }else throw Error('Unexpected '+method)
  return route.fulfill({json:{message:data}})
 })
 await page.goto(origin+'/relay#/settings');await page.getByRole('button',{name:'Add policy',exact:true}).click()
 for(const [label,kind] of [['Channel','channel'],['Primary provider','provider'],['Execution user','execution_user'],['Business type','business_doctype']]){
  await page.getByLabel(label,{exact:true}).selectOption(kind+'-fixture')
 }
 await page.getByLabel('Instructions',{exact:true}).fill('Preserve this policy draft')
 await page.getByRole('button',{name:'Save policy',exact:true}).click();await page.getByText('You do not have permission for this action.',{exact:true}).waitFor()
 if(await page.getByLabel('Instructions',{exact:true}).inputValue()!=='Preserve this policy draft')throw Error('Policy draft lost after error')
 fail=false;await page.getByRole('button',{name:'Save policy',exact:true}).click();await page.getByText('Automation policy saved',{exact:true}).waitFor()
 if(saves.length!==2||saves[1].body.values.mode!=='Shadow'||saves[1].body.values.enabled!==0||saves[1].headers['x-frappe-csrf-token']!=='synthetic-csrf-token')throw Error('Policy save contract failed')
 await page.getByRole('button',{name:'Add policy',exact:true}).click()
 for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:900});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Overflow '+width)}
 if(errors.length)throw Error(errors.join('\n'))
 return {passed:true,remoteSearch:requests.some(r=>r.query==='backup'),draftRetained:true,shadowDefault:true,viewports:[320,390,768,1440]}
}
