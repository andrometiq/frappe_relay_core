import assert from 'node:assert/strict'
import { chromium } from '../../../.runtime/browser/node_modules/playwright/index.mjs'
let input = ''
for await (const chunk of process.stdin) input += chunk
const f = JSON.parse(input)
const browser = await chromium.launch({headless:true})
try {
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', error => { errors.push(error.message); console.error('UI error:', error.message) })
  const waitWrite = method => page.waitForResponse(response => response.url().endsWith('/api/method/relay_core.'+method) && response.request().method()==='POST')
  async function checkWrite(promise, nested=false) {
    const response = await promise
    assert.equal(response.status(),200, await response.text())
    const payload=response.request().postDataJSON(), scope=nested?payload.values:payload
    assert.equal(scope.business_doctype,'Customer');assert.equal(scope.business_name,f.customer)
    const result=(await response.json()).message
    assert.ok(result.name)
    return result
  }
  async function action(name) {
    await page.getByRole('button',{name:'Conversation actions',exact:true}).click()
    await page.getByRole('menuitem',{name,exact:true}).click()
  }
  for (const width of [1440,390]) {
    await page.setViewportSize({width,height:900})
    await page.goto(f.base+'/#/messages')
    await page.getByRole('searchbox',{name:'Search conversations'}).fill(f.contactTitle)
    const conversation=page.getByRole('button',{name:'Open conversation: '+f.contactTitle,exact:true})
    await conversation.waitFor()
    await conversation.focus();await page.keyboard.press('Enter')
    await page.getByRole('button',{name:'Conversation actions',exact:true}).waitFor()
    assert.equal(await page.locator('script').filter({hasText:'alert(1)'}).count(),0)
    await action('Internal notes')
    await page.getByRole('textbox',{name:'Internal note',exact:true}).fill('Sim UI quantity 30 total 1500')
    let sent=waitWrite('collaboration.add')
    await page.getByRole('button',{name:'Add internal note',exact:true}).click()
    await checkWrite(sent)
    await page.getByRole('button',{name:'Close internal notes',exact:true}).click()
    await action('Cases')
    await page.getByRole('button',{name:'New case',exact:true}).click()
    await page.getByLabel('Case type',{exact:true}).selectOption(f.caseType)
    await page.getByLabel('Case title',{exact:true}).fill('Sim UI order review')
    await page.getByLabel('quantity',{exact:true}).fill('30')
    sent=waitWrite('cases.create_manual')
    await page.getByRole('button',{name:'Create case',exact:true}).click()
    const result=await checkWrite(sent);assert.equal(result.field_values.quantity,30)
    await page.getByRole('dialog').getByRole('button',{name:'Close',exact:true}).click()
    await action('Topics')
    await page.getByRole('button',{name:'New topic',exact:true}).click()
    await page.getByRole('dialog').getByRole('textbox',{name:'Title',exact:true}).fill('Sim UI empty topic')
    sent=waitWrite('topics.save')
    await page.getByRole('button',{name:'Save topic',exact:true}).click()
    assert.equal((await checkWrite(sent,true)).message_count,0)
    await page.getByRole('dialog').getByRole('button',{name:'Close',exact:true}).click()
    await page.screenshot({path:`.runtime/followup-inbox-${width}.png`})
    await page.goto(f.base+'/#/tickets')
    const ticket=page.getByRole('button',{name:'Open ticket: '+f.ticket,exact:true})
    await ticket.waitFor();await ticket.focus();await page.keyboard.press('Enter')
    await page.getByRole('heading',{name:f.ticket,exact:true}).waitFor()
    await page.screenshot({path:`.runtime/followup-ticket-${width}.png`})
    await page.goto(f.base+'/#/skills')
    await page.getByRole('button',{name:/^Open skill:/}).first().waitFor()
    const skill=page.getByRole('button',{name:'Open skill: '+f.skill,exact:true})
    // Existing site skills can occupy earlier pages.
    while (await skill.count()===0 && await page.getByRole('button',{name:'Load more',exact:true}).count()) {
      const loaded=page.waitForResponse(response=>response.url().includes('/relay_core.ai.configuration.directory'))
      await page.getByRole('button',{name:'Load more',exact:true}).click()
      await loaded
      await page.getByRole('button',{name:'New skill',exact:true}).waitFor()
    }
    await skill.waitFor();await skill.focus();await page.keyboard.press('Enter')
    await page.getByRole('heading',{name:'Edit skill',exact:true}).waitFor()
    await page.screenshot({path:`.runtime/followup-skill-${width}.png`})
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false)
    console.log(`PASS ${width}px: keyboard conversation/ticket/skill cards; real scoped note/case/topic HTTP writes`)
  }
  assert.deepEqual(errors,[])
} finally {await browser.close()}
