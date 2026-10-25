import assert from 'node:assert/strict'
import {chromium} from '../../../.runtime/browser/node_modules/playwright/index.mjs'
let input=''
for await(const chunk of process.stdin) input+=chunk
const fixture=JSON.parse(input)
const browser=await chromium.launch({executablePath:process.env.CHROME_PATH || '/usr/bin/google-chrome',headless:true,args:['--no-sandbox']})
try {
  const page=await browser.newPage({viewport:{width:390,height:900}}), errors=[]
  page.on('pageerror',error=>errors.push(error.message))
  await page.goto(fixture.origin+'/site.html#/skills')
  const event=page.getByRole('button',{name:'Open event: '+fixture.title,exact:true})
  while(!await event.count()){
    const more=page.getByRole('button',{name:'Load more',exact:true})
    await Promise.race([event.waitFor(),more.waitFor()])
    if(await event.count())break
    await more.click()
  }
  await event.click()
  await page.getByLabel('Reply style',{exact:true}).fill('Sim preview: short clear wording')
  await page.getByRole('button',{name:'Save',exact:true}).click()
  await page.getByText('Saved.',{exact:true}).waitFor()
  await page.getByRole('combobox',{name:'Incoming message',exact:true}).click()
  await page.getByRole('option',{name:'/ledger',exact:true}).waitFor();await page.keyboard.press('Enter')
  await page.getByRole('button',{name:'Run preview',exact:true}).click()
  await page.getByText('Would raise the episode ticket only',{exact:true}).waitFor()
  await page.getByText('No proposed writes.',{exact:true}).waitFor()
  assert.ok((await page.locator('.automation-preview').innerText()).includes(fixture.company))
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false)
  assert.deepEqual(errors,[])
  console.log('PASS built UI + yrp.site HTTP: readable metadata, save, keyboard source selection and ticket-only preview at 390px')
} finally {await browser.close()}
