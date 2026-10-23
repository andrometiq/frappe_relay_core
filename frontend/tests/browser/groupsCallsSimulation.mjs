// Installed UI interaction test. All provider operations below are intercepted.
// Backend authorization and real HTTP provider fixtures are tested separately.
export default async function groupsCalls(page, origin) {
 const calls=[],errors=[]
 page.on('pageerror',e=>errors.push(e.message))
 await page.addInitScript(()=>{
  Object.defineProperty(navigator.mediaDevices,'getUserMedia',{value:async()=>({getTracks:()=>[{stop(){}}]})})
  window.RTCPeerConnection=class {constructor(){this.iceGatheringState='complete'} addTrack(){} async createOffer(){return {type:'offer',sdp:'synthetic browser offer'}} async setLocalDescription(value){this.localDescription=value} close(){} }
 })
 await page.route('**/api/method/relay_core.**',async route=>{
  const request=route.request(),method=request.url().split('/').at(-1).split('?')[0],args=request.method()==='POST'?request.postDataJSON():{}
  let message={}
  if(method==='relay_core.api.business_types')message=['Customer']
  else if(method==='relay_core.api.business_records')message=[{name:'Synthetic customer'}]
  else if(method==='relay_core.api.messages')message={items:[],first:null,has_more:false}
  else if(method==='relay_core.api.contacts')message={items:[]}
  else if(method==='relay_core.telegram.group_chats')message={configured:true,items:[{name:'RELAY-CE-0000000001',chat_id:-100100,label:'Dispatch team',contact:'RELAY-CON-0000000001',channel:'RELAY-CH-0000000001'}],next:null}
  else if(method==='relay_core.telegram.groups'){
   calls.push({method,args,csrf:request.headers()['x-frappe-csrf-token']})
   let result=true
   if(args.operation==='info')result={id:-100100,title:'Dispatch team',type:'supergroup',is_forum:true,description:'Orders'}
   if(args.operation==='administrators')result=[{user:{id:123,first_name:'Manager'},status:'administrator'}]
   if(args.operation==='count')result=8
   if(args.operation==='member')result={user:{id:123,first_name:'Manager'},status:'member'}
   if(args.operation.startsWith('invite.'))result={invite_link:'https://t.me/+synthetic'}
   if(args.operation==='topics.create')result={message_thread_id:7}
   message={result}
  }else if(method==='relay_core.telegram.send'){calls.push({method,args});message={sent:true}}
  else if(method==='relay_core.whatsapp.business_contacts')message={contacts:[{name:'Synthetic contact',full_name:'Review recipient',mobile_no:'919000000001'}],has_more:false}
  else if(method==='relay_core.whatsapp.execute'){
   calls.push({method,args})
   if(args.operation==='capabilities')message={site:origin,calls:true,groups:true,templates:true}
   else if(args.operation==='groups.list')message={data:[{id:'group-one',subject:'Supplier group'}]}
   else if(args.operation==='groups.info')message={id:'group-one',subject:'Supplier group',description:'Orders',participants:[]}
   else if(args.operation==='calls.permission.get')message={permission:{status:'Granted'},actions:[{action_name:'start_call',can_perform_action:true}]}
   else if(args.operation==='calls.action')message={calls:[{id:'synthetic-call'}]}
   else message={data:[],events:[]}
  }else throw Error('Unexpected method '+method)
  return route.fulfill({json:{message}})
 })
 await page.goto(origin+'/relay#/groups')
 await page.getByRole('tab',{name:'Telegram',exact:true}).click()
 await page.getByLabel('Telegram group',{exact:true}).click();
    await page.getByRole('option').filter({hasText:'Dispatch team'}).click()
 await page.getByLabel('Message',{exact:true}).fill('Synthetic group reply')
 await page.getByRole('button',{name:'Send message',exact:true}).click()
 await page.getByRole('status').filter({hasText:'Message submitted'}).waitFor()
 await page.getByRole('tab',{name:'Topics',exact:true}).click()
 await page.getByLabel('Topic name',{exact:true}).fill('Orders')
 await page.getByRole('button',{name:'Create topic',exact:true}).click()
 await page.getByRole('status').filter({hasText:'Topic created'}).waitFor()
 await page.getByRole('button',{name:'Close topic',exact:true}).click()
 await page.getByRole('status').filter({hasText:'Topic updated'}).waitFor()
 await page.getByRole('tab',{name:'Invites',exact:true}).click()
 await page.getByRole('button',{name:'Create invite',exact:true}).click()
 await page.getByRole('status').filter({hasText:'Invite created'}).waitFor()
 await page.getByRole('tab',{name:'Members',exact:true}).click()
 await page.getByRole('button',{name:'Load administrators',exact:true}).click()
 await page.getByText('8 members',{exact:true}).waitFor()
 await page.getByRole('button',{name:'Select member',exact:true}).click()
 await page.getByRole('button',{name:'Approve join request',exact:true}).click()
 await page.getByRole('status').filter({hasText:'Member action confirmed'}).waitFor()
 await page.getByRole('tab',{name:'WhatsApp',exact:true}).click()
 await page.getByLabel('Group',{exact:true}).selectOption('group-one')
 await page.getByRole('button',{name:'Group settings',exact:true}).click()
 await page.getByLabel('Subject',{exact:true}).waitFor()
 await page.getByRole('button',{name:'Calls',exact:true}).click()
 await page.getByLabel('Business record',{exact:true}).selectOption('Synthetic customer')
 await page.getByRole('button',{name:'Find contacts',exact:true}).click()
 await page.getByLabel('Recipient contact',{exact:true}).selectOption('Synthetic contact')
 await page.getByRole('button',{name:'Call',exact:true}).click()
 await page.getByText('Awaiting answer',{exact:true}).waitFor()
 await page.getByRole('button',{name:'Groups',exact:true}).click()
 await page.getByRole('button',{name:'Calls',exact:true}).click()
 await page.getByText('Awaiting answer',{exact:true}).waitFor()
 await page.getByRole('button',{name:'End call',exact:true}).click()
 await page.getByText('Ended',{exact:true}).waitFor()
 const sizes=[]
 for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:900});sizes.push(await page.evaluate(()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth})));}
 if(sizes.some(x=>x.scrollWidth>x.width))throw Error('Horizontal overflow')
 if(errors.length)throw Error(errors.join('; '))
 const sent=calls.find(x=>x.method==='relay_core.telegram.send')
 if(sent?.args.chat_id!==-100100)throw Error('Telegram send lost group identity')
 const topicCall=calls.find(x=>x.args.operation==='topics.close')
 if(topicCall?.args.arguments.message_thread_id!==7)throw Error('Topic identity lost')
 const connect=calls.find(x=>x.args.arguments?.action==='connect')
 if(connect?.args.contact!=='Synthetic contact'||connect.args.business_name!=='Synthetic customer')throw Error('Call recipient binding lost')
 if(!calls.find(x=>x.args.arguments?.action==='terminate'))throw Error('Missing call termination')
 return {passed:true,groupOperations:calls.filter(x=>x.method==='relay_core.telegram.groups').map(x=>x.args.operation),callLifecycle:['permission','connect','navigate and return','terminate'],sizes}
}
