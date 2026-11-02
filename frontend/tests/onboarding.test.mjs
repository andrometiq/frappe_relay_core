import test from 'node:test'
import assert from 'node:assert/strict'
import {
  SIGNUP_WINDOW, activeStep, isSignupMessage, limitText, nameStatus, openSignupWindow, setupQuery, setupRoute, signupSteps,
  watchSetup,
} from '../src/services/onboarding.js'

const HUB = 'https://hub.example.com/hub'
const SESSION = 'sus_' + 'a'.repeat(32)
const message = (origin, data) => ({ origin, data })

test('only the Hub window may report this session', () => {
  const data = { type: 'relay-whatsapp-signup', session_id: SESSION, state: 'working' }
  assert.equal(isSignupMessage(message('https://hub.example.com', data), HUB, SESSION), true)
  assert.equal(isSignupMessage(message('https://evil.example.com', data), HUB, SESSION), false)
  assert.equal(isSignupMessage(message('https://hub.example.com', { ...data, session_id: 'sus_other' }), HUB, SESSION), false)
  assert.equal(isSignupMessage(message('https://hub.example.com', { ...data, type: 'other' }), HUB, SESSION), false)
  assert.equal(isSignupMessage(message('https://hub.example.com', JSON.stringify(data)), HUB, SESSION), false)
  assert.equal(isSignupMessage(message('https://hub.example.com', data), '', SESSION), false)
})

test('the window opens blank inside the click and a blocked window is reported', () => {
  const calls = []
  const opened = {}
  assert.equal(openSignupWindow((...args) => { calls.push(args); return opened }, false), opened)
  assert.deepEqual(calls[0], ['about:blank', SIGNUP_WINDOW, 'popup,width=600,height=760'])
  assert.equal(openSignupWindow((...args) => { calls.push(args); return null }, true, 'https://hub/x'), null)
  assert.deepEqual(calls[1], ['https://hub/x', SIGNUP_WINDOW, ''])
})

function fakeTarget() {
  const handlers = {}
  return { handlers, addEventListener: (name, fn) => { handlers[name] = fn }, removeEventListener: name => { delete handlers[name] } }
}

test('the setup is read again on the Hub message, a visible tab, a reconnect and realtime changes only', () => {
  const reasons = []
  const target = fakeTarget(), page = { ...fakeTarget(), visibilityState: 'hidden' }
  let listener, stopped = false
  const stop = watchSetup({ hubOrigin: () => HUB, sessionId: () => SESSION, reread: reason => reasons.push(reason),
    onRealtime: fn => { listener = fn; return () => { stopped = true } }, target, page })
  target.handlers.message(message('https://hub.example.com', { type: 'relay-whatsapp-signup', session_id: SESSION }))
  target.handlers.message(message('https://evil.example.com', { type: 'relay-whatsapp-signup', session_id: SESSION }))
  page.handlers.visibilitychange()
  page.visibilityState = 'visible'
  page.handlers.visibilitychange()
  listener({ kind: 'reconnect' })
  listener({ kind: 'onboarding', session: SESSION })
  listener({ kind: 'onboarding', session: 'sus_other' })
  listener({ kind: 'channel_automation' })
  listener({ kind: 'messages' })
  assert.deepEqual(reasons, ['message', 'visible', 'reconnect', 'onboarding', 'channels'])
  stop()
  assert.equal(stopped, true)
  assert.deepEqual(Object.keys(target.handlers), [])
})

test('the page opens the first open step unless a reachable one is asked for', () => {
  assert.equal(activeStep('hub', 'number'), 'hub')
  assert.equal(activeStep('business', ''), 'business')
  assert.equal(activeStep('number', 'business'), 'business')
  assert.equal(activeStep('number', 'records'), 'number')
  assert.equal(activeStep('ready', 'records'), 'records')
  assert.equal(activeStep('done', ''), 'ready')
  assert.equal(activeStep('done', 'number'), 'number')
  assert.equal(activeStep('odd', 'odd'), 'hub')
})

test('setup links carry the step and session', () => {
  assert.equal(setupRoute('number'), '#/setup?step=number')
  assert.equal(setupRoute('', SESSION), '#/setup?session=' + SESSION)
  assert.deepEqual(setupQuery('#/setup?step=number&session=' + SESSION), { step: 'number', session: SESSION })
  assert.deepEqual(setupQuery('#/setup'), { step: '', session: '' })
})

test('skipped steps are hidden and limits and name states read plainly', () => {
  const session = { steps: [{ name: 'verify', status: 'done' }, { name: 'register', status: 'skipped' }, { name: 'sync_history', status: 'running' }, { name: 'odd', status: 'done' }] }
  assert.deepEqual(signupSteps(session).map(step => [step.label, step.status]), [['Checking access', 'done'], ['Copying chats', 'running']])
  assert.equal(limitText('TIER_250'), '250 customers a day until Meta verifies your business')
  assert.equal(limitText('TIER_1K'), '1,000 customers a day')
  assert.equal(limitText(undefined), 'Not known yet')
  assert.deepEqual(nameStatus('APPROVED'), { label: 'Approved', theme: 'green' })
  assert.deepEqual(nameStatus('PENDING_REVIEW'), { label: 'In review', theme: 'amber' })
  assert.deepEqual(nameStatus('DECLINED'), { label: 'Declined', theme: 'red' })
})
