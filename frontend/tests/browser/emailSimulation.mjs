// Runs against the real worktree HTTP API and populated local fixtures. No API fixtures.
export default async function testEmail(page, origin, fixture) {
  await page.goto(origin + '/relay#/messages?message=' + fixture.sources.Email)
  const composer = page.getByRole('form', {name:'Email composer'})
  await composer.getByLabel(/^To\b/).waitFor()
  await composer.getByLabel(/^Message\b/).fill('Local browser draft: quantity 25')
  await page.reload()
  await composer.getByLabel(/^Message\b/).waitFor()
  if (await composer.getByLabel(/^Message\b/).inputValue() !== 'Local browser draft: quantity 25') throw Error('Reload lost email draft')
  await composer.getByRole('button', {name:'Reply all',exact:true}).click()
  if (!(await composer.getByLabel('CC', {exact:true}).inputValue()).includes('local-inbox@example.invalid')) throw Error('Reply-all dropped recorded recipients')
  await composer.getByRole('button', {name:'Reply',exact:true}).click()
  if (!(await composer.getByLabel('CC',{exact:true}).isVisible())) await composer.getByRole('button',{name:'CC / BCC',exact:true}).click()
  await composer.getByLabel('CC',{exact:true}).fill(fixture.cc)
  await composer.getByLabel('BCC (private delivery audit only)',{exact:true}).fill(fixture.bcc)
  await composer.locator('input[type=file]').setInputFiles({name:'local-cu-evidence.txt',mimeType:'text/plain',buffer:Buffer.from('Local evidence quantity 25')})
  await composer.getByRole('button',{name:'Remove',exact:true}).waitFor()
  const attempt = page.waitForResponse(response=>response.url().includes('relay_core.email.send') && response.request().method()==='POST')
  await composer.getByRole('button', {name:'Send email',exact:true}).click()
  const response=await attempt
  if(response.status()!==200)throw Error('Email API rejected local browser fixture')
  const result=(await response.json()).message
  if(!result.action || result.status!=='Submitted' || !result.message) throw Error('Email did not journal and project')
  const history=await page.evaluate(async contact=>(await (await fetch('/api/method/relay_core.api.messages?contact='+encodeURIComponent(contact))).json()).message,fixture.contact)
  const outgoing=history.items.find(row=>row.name===result.message)
  if(!outgoing || JSON.stringify(outgoing).includes(fixture.bcc))throw Error('BCC leaked into message history')
  await composer.getByRole('button', {name:'Forward',exact:true}).click()
  if(await composer.getByLabel(/^To\b/).inputValue())throw Error('Forward retained source recipients')
  return {realAPI:true,reloadSafeDraft:true,replyAll:true,forward:true,submitted:true,attachments:true,bccPrivate:true}
}
