import assert from 'node:assert/strict'
import { chromium } from '../../../.runtime/browser/node_modules/playwright/index.mjs'
import { readableName } from '../../src/services/recordTitle.js'
let input='';for await(const chunk of process.stdin)input+=chunk
const fixture=JSON.parse(input)
const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'/usr/bin/google-chrome',headless:true,args:['--no-sandbox']})
try {
  const page=await browser.newPage({viewport:{width:390,height:900}}),errors=[]
  page.setDefaultTimeout(12000)
  page.on('pageerror',error=>errors.push(error.message))
  await page.goto(fixture.origin+'/site.html#/tickets')
  await page.getByLabel('Assignee',{exact:true}).fill(fixture.actor)
  await page.waitForFunction(()=>[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='Apply'&&!b.disabled))
  const filtered=page.waitForResponse(response=>response.url().includes('tickets.directory')&&new URL(response.url()).searchParams.get('assigned_to')===fixture.actor)
  await page.getByRole('button',{name:'Apply',exact:true}).click()
  assert.equal((await filtered).status(),200)
  await page.getByRole('button',{name:'Open ticket: '+readableName(fixture.subject),exact:true}).click()
  const detail=page.locator('.ticket-detail')
  await detail.getByText('Sim legacy order quantity 25, amount 1250',{exact:true}).waitFor()
  await detail.getByText('Sim legacy payment amount 250',{exact:true}).waitFor()
  await detail.getByRole('heading',{name:'Notification',exact:true}).waitFor()
  assert.equal(await detail.getByRole('button',{name:'Take over',exact:true}).count(),0)
  assert.equal(await detail.getByText('AI active',{exact:true}).count(),0)
  assert.ok(!(await detail.innerText()).includes('7500'))
  assert.ok(!(await detail.innerText()).includes('1792867625249477656'))
  await detail.getByRole('link',{name:'Open conversation · WhatsApp',exact:true}).first().waitFor()
  for(const width of [390,1440]) {
    await page.setViewportSize({width,height:900})
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false)
  }
  await page.goto(fixture.origin+'/site.html#/skills')
  const event=page.getByRole('button',{name:'Open event: '+readableName(fixture.event),exact:true})
  while(!await event.count()){
    const more=page.getByRole('button',{name:'Load more',exact:true})
    await Promise.race([event.waitFor(),more.waitFor()])
    if(await event.count())break
    await more.click()
  }
  await page.waitForFunction(title=>[...document.querySelectorAll('.event-list button')].some(
    el=>el.textContent.includes(title)&&el.textContent.includes('WhatsApp')),readableName(fixture.event))
  assert.ok(!(await event.innerText()).includes('Sim Action'))
  await event.click()
  assert.equal(await page.getByRole('textbox',{name:/^Title/}).inputValue(),readableName(fixture.event))
  const channel=page.getByRole('combobox',{name:'Channel',exact:true})
  assert.equal(await channel.textContent(),'WhatsApp')
  await page.getByLabel('Reply style',{exact:true}).fill('Sim readable title preservation')
  await page.getByRole('button',{name:'Save',exact:true}).click()
  await page.getByText('Saved.',{exact:true}).waitFor()
  assert.deepEqual(errors,[])
  console.log('PASS built UI + yrp.site: legacy ticket opens at mobile/desktop, linked amounts visible, no episode controls or raw captions; event channel fallback and readable title survive unrelated save')
} finally {await browser.close()}
