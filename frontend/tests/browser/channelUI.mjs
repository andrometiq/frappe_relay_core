import { readFile, mkdir, writeFile, readdir, unlink } from 'node:fs/promises'
import testEmail from './emailSimulation.mjs'
const { chromium } = await import(process.env.RELAY_PLAYWRIGHT_MODULE)
const fixture=JSON.parse(await readFile(process.argv[2],'utf8'))
const origin='http://127.0.0.1:8001', out='/tmp/relay-cu-shots'
await mkdir(out,{recursive:true})
for (const file of await readdir(out)) if (file.endsWith('.png') || ['results.json','failure.json'].includes(file)) await unlink(out+'/'+file)
const browser=await chromium.launch({channel:'chrome',headless:true})
const context=await browser.newContext({viewport:{width:1440,height:1000}})
// Realtime must never gate the initial HTTP directory or thread.
await context.routeWebSocket(/\/socket.io\//, socket => socket.close())
// 8001 serves MAIN. Proxy only this browser's HTTP requests to the worktree WSGI
// process; assets come from this worktree's build. No installed files change.
await context.route(origin+'/**',async route=>{
  const response=await route.fetch({url:route.request().url().replace(origin,'http://127.0.0.1:'+fixture.port),maxRedirects:0})
  await route.fulfill({response})
})
const page=await context.newPage(),errors=[]
page.on('pageerror',error=>errors.push(error.message))
try {
await page.goto(origin+fixture.login)
await page.goto(origin+'/relay#/messages')
await page.getByRole('heading',{name:'Conversations',exact:true}).waitFor()
await page.locator('.directory-contact').first().waitFor()
await page.getByRole('combobox',{name:'Channel',exact:true}).click()
await page.getByRole('option',{name:'WhatsApp',exact:true}).click()
await page.waitForFunction(() => [...document.querySelectorAll('.directory-contact small')].some(node => node.textContent.includes('Local & team')))
if (!(await page.locator('.directory-rows').innerText()).includes('<img src=x onerror=alert(1)>')) throw Error('Preview lost plain text')
if (await page.locator('.directory-contact img').count()) throw Error('Preview HTML was rendered')
const email=await testEmail(page,origin,fixture)
const results=[]
async function inboxReady() {
  await page.locator('.directory-contact').first().waitFor({state:'attached'})
  await page.waitForFunction(() => document.querySelector('.directory-rows')?.getAttribute('aria-busy') === 'false')
}
async function threadReady() {
  await inboxReady()
  await page.locator('.message-thread .conversation-bubble').first().waitFor()
}
async function shot(name) {
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(250)
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth > innerWidth)
  await page.screenshot({path:`${out}/${name}.png`,fullPage:true})
  const layout=await page.evaluate(() => {
    const thread=document.querySelector('.message-thread'), composer=document.querySelector('.message-composer')
    const clipped=[...document.querySelectorAll('.contact-details, .contact-identity, .email-composer .relay-field')].filter(node => node.scrollWidth > node.clientWidth + 1).map(node=>node.className)
    return {threadHeight:thread?.clientHeight,composerHeight:composer?.clientHeight,clipped}
  })
  const realtime=await page.locator('.v1-connection').innerText()
  if(realtime==='Live')throw Error('Socket outage test unexpectedly connected')
  results.push({name,overflow,realtime,...layout})
  if(overflow || layout.clipped.length)throw Error('Clipping: '+name+' '+JSON.stringify(layout))
  if (name.endsWith('-composer') && layout.threadHeight < layout.composerHeight) throw Error('Composer squeezes thread: '+name)

}
for(const width of [1440,390])for(const theme of ['light','dark']){
  await page.setViewportSize({width,height:width===390?844:1000})
  await page.evaluate(theme=>localStorage.setItem('theme',theme),theme)
  for(const view of ['contacts','settings','skills','business-events','messages']){
    await page.goto(origin+'/relay#/'+view);await page.reload()
    if(view==='contacts'){
      await page.getByLabel('Search Frappe Contacts').fill(fixture.person.split('-Local Relay')[0])
      await page.getByRole('button',{name:'Search',exact:true}).click()
      await page.locator('.workspace-person-row').first().click()
      await page.getByRole('heading',{name:'Channel identities'}).waitFor()
      await page.getByRole('combobox',{name:'Business',exact:true}).click(); await page.getByRole('option',{name:'Customer · '+fixture.customer,exact:true}).click()
    }
    if(view==='contacts') {
      let revokeRequested=false
      const onRequest=request=>{if(request.url().includes('enrollment.revoke'))revokeRequested=true}
      page.on('request',onRequest)
      page.once('dialog',dialog=>dialog.dismiss())
      await page.getByRole('button',{name:'Revoke identity',exact:true}).first().click()
      if(revokeRequested) throw Error('Cancelling revoke mutated the identity')
      page.off('request',onRequest)
      await page.getByRole('heading',{name:'Channel identities',exact:true}).evaluate(node=>node.scrollIntoView({block:'start'}))
      if(/\d{2}:\d{2}:\d{2}\.\d{6}/.test(await page.locator('.contact-identity').allTextContents().then(rows=>rows.join(' ')))) throw Error('Raw identity timestamps')
    }
    if(view==='skills'||view==='business-events') {
      await page.getByRole('button',{name:view==='skills'?'New skill':'New event rule',exact:true}).first().click()
      if(view==='business-events') {
        await page.getByLabel('Use this business/person’s consent and channel priorities').check()
        await page.getByLabel('Telegram template',{exact:true}).fill('Order {name}: {total_qty} items')
        await page.getByLabel('Email subject template',{exact:true}).fill('Order {name}')
        await page.getByLabel('Email body template',{exact:true}).fill('Your order contains {total_qty} items.')
      }
    }
    if(view==='messages') {
      await inboxReady()
      if (width===1440) {
        await page.locator('.directory-contact').filter({hasText:fixture.person.split('-Local Relay')[0]}).first().click()
        await threadReady()
      }
      if(await page.getByRole('combobox',{name:'Channel',exact:true}).textContent() !== 'All channels') throw Error('Missing channel default')
    }
    if(view==='settings') await page.getByRole('heading',{name:'Channel readiness',exact:true}).waitFor()
    await shot(`${width}-${theme}-${view}`)
  }
  for(const provider of ['Telegram','Email']){
    await page.goto(origin+'/relay#/messages?message='+fixture.sources[provider]);await page.reload()
    if(provider==='Email')await page.getByRole('form',{name:'Email composer'}).waitFor()
    else await page.getByText('Telegram plain text',{exact:false}).waitFor()
    await threadReady()
    await shot(`${width}-${theme}-${provider.toLowerCase()}-composer`)
  }
  await page.goto(origin+'/relay#/messages?'+new URLSearchParams({business_doctype:'Customer',business_name:fixture.customer,contact:fixture.person}));await page.reload()
  await page.locator('.business-contact-strip').waitFor()
  await page.waitForFunction(()=>document.querySelector('.business-contact-strip button')?.disabled===false && !document.querySelector('.contact-strip-loading'))
  await page.waitForTimeout(200)
  if(await page.locator('.business-recipient-bar button').isVisible())await page.locator('.business-recipient-bar button').click()
  await page.locator('.business-compose-start button').click().catch(async error=>{await page.screenshot({path:out+'/start-failure.png'});await writeFile(out+'/start-failure.json',JSON.stringify({errors,text:await page.locator('body').innerText()},null,2));await browser.close();throw error})
  await page.locator('.start-contact-results [role=option]').first().click()
  await page.getByLabel('Send through',{exact:true}).waitFor()
  for(const provider of ['Telegram','Email']) {
    const value=await page.getByLabel('Send through',{exact:true}).locator('option').evaluateAll((options,provider)=>options.find(option=>option.textContent.startsWith(provider+' · '))?.value,provider)
    if(!value)throw Error('Missing start destination for '+provider)
    await page.getByLabel('Send through',{exact:true}).selectOption(value)
    await page.getByRole('dialog').getByLabel(/^Message\b/).fill('Local new conversation: quantity 25')
    if(provider==='Email')await page.getByRole('dialog').getByLabel(/^Subject\b/).fill('Local order 25')
    await shot(`${width}-${theme}-start-${provider.toLowerCase()}`)
  }
  await page.getByRole('dialog').getByRole('button',{name:'Close',exact:true}).last().click()

}
await writeFile(out+'/results.json',JSON.stringify({build:'worktree via browser-only proxy; main 8001 unchanged',email,results,errors},null,2))
if(errors.length)throw Error(JSON.stringify(errors))
console.log(`PASS API-backed email browser acceptance; ${results.length} screenshots; no page errors or overflow`)
} catch (error) {
  if (!page.isClosed()) {
    await page.screenshot({path:out+'/failure.png',fullPage:true})
    await writeFile(out+'/failure.json',JSON.stringify({errors,text:await page.locator('body').innerText()},null,2))
  }
  throw error
} finally { await browser.close() }
