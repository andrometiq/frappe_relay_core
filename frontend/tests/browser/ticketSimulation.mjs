export default async function testTickets(page,origin='http://127.0.0.1:18126'){
 const name='RELAY-TKT-0000000001',message='RELAY-MSG-0000000001',requests=[],errors=[]
 let status='Open',assigned='agent@example.invalid',enabled=0
 page.on('pageerror',error=>errors.push(error.message))
 await page.addInitScript(()=>{window.frappe={csrf_token:'synthetic-csrf-token',session:{user:'Administrator'}}})
 await page.route('**/api/method/**',async route=>{
  const request=route.request(),method=request.url().split('/').at(-1).split('?')[0];let result
  if(request.method()==='POST')requests.push({method,body:request.postDataJSON(),headers:request.headers()})
  const ticket={name,subject:'Support request',category:'Support',status,assigned_to:assigned,can_assign:true,messages:[{message,channel:'Email'}]}
  if(method==='relay_core.tickets.directory')result={items:[{...ticket,id:name}]}
  else if(method==='relay_core.tickets.read')result=ticket
  else if(method==='relay_core.teams.agents')result=[{name:'agent@example.invalid',full_name:'Agent One'},{name:'second@example.invalid',full_name:'Agent Two'}]
  else if(method==='relay_core.tickets.update_status'){status=request.postDataJSON().status;result={status}}
  else if(method==='relay_core.tickets.assign'){assigned=request.postDataJSON().user;result={}}
  else if(method==='relay_core.ticket_notifications.subscription')result={enabled,destination:enabled?'RELAY-CE-0000000001':''}
  else if(method==='relay_core.ticket_notifications.destinations')result={items:[{value:'RELAY-CE-0000000001',label:'Email · agent@example.invalid'}]}
  else if(method==='relay_core.ticket_notifications.subscribe'){enabled=request.postDataJSON().enabled;result={enabled}}
  else throw Error('Unexpected '+method)
  return route.fulfill({json:{message:result}})
 })
 await page.goto(origin+'/relay#/tickets?ticket='+name);await page.getByRole('heading',{name:'Support request',exact:true}).waitFor()
 await page.getByLabel('Ticket status',{exact:true}).selectOption('In progress');await page.getByRole('button',{name:'Update status',exact:true}).click();await page.getByText('Ticket updated',{exact:true}).waitFor()
 await page.getByLabel('Ticket assignee',{exact:true}).selectOption('second@example.invalid');await page.getByRole('button',{name:'Assign ticket',exact:true}).click();await page.getByText('Ticket assignment saved',{exact:true}).waitFor()
 await page.getByLabel('Notification endpoint',{exact:true}).selectOption('RELAY-CE-0000000001');await page.getByRole('button',{name:'Enable notifications',exact:true}).click();await page.getByText('Ticket notifications enabled',{exact:true}).waitFor()
 await page.getByRole('button',{name:'Disable notifications',exact:true}).click();await page.getByText('Ticket notifications disabled',{exact:true}).waitFor()
 const link=page.getByRole('link',{name:message+' · Email',exact:true});if(await link.getAttribute('href')!=='#/messages?message='+message)throw Error('Ticket message link changed')
 for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:900});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Overflow '+width)}
 if(requests.length!==4||requests.some(r=>r.headers['x-frappe-csrf-token']!=='synthetic-csrf-token')||errors.length)throw Error(JSON.stringify({requests,errors}))
 return {passed:true,assignment:true,subscription:true,exactNavigation:true,viewports:[320,390,768,1440]}
}
