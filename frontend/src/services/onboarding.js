// Get started: the Facebook window, the messages it sends back and when the page reads the setup again. No timers.
export const SIGNUP_WINDOW = 'relay-whatsapp-signup'
export const SIGNUP_MESSAGE = 'relay-whatsapp-signup'

export const STEPS = [
  { name: 'hub', label: 'Connect to Relay' },
  { name: 'business', label: 'Business details' },
  { name: 'number', label: 'WhatsApp number' },
  { name: 'ready', label: 'Test and finish' },
  { name: 'records', label: 'Link records' },
]

export const FLOWS = [
  { value: 'new', icon: 'phone', title: 'A new number', text: 'You get a code by SMS or call. The number must not be in use on any WhatsApp app.',
    need: 'The phone that receives the code.', meta: ['Log in to Facebook', 'Choose or create your business portfolio', 'Enter the number and the code Meta sends'] },
  { value: 'coexistence', icon: 'scan', title: 'My WhatsApp Business app number', text: 'Keep using the app on your phone. Relay copies chats from the last 6 months and your contacts.',
    need: 'The phone with WhatsApp Business 2.24.17 or later, near you, to scan a QR code.', meta: ['Log in to Facebook', 'Choose your business portfolio', 'Scan the QR code with the WhatsApp Business app', 'Choose to share your chat history'] },
  { value: 'migrate', icon: 'repeat', title: 'A number on another provider', text: 'Keep your number, name and limits. Chat history from the old provider does not move.',
    need: 'Two-step verification turned off for the number at the old provider.', meta: ['Log in to Facebook', 'Choose your business portfolio', 'Choose the number that is on the other provider'] },
]

const STEP_LABELS = {
  exchange: 'Getting access from Facebook', verify: 'Checking access', channel: 'Adding your number', subscribe: 'Turning on messages',
  register: 'Registering the number', sync_contacts: 'Copying contacts', sync_history: 'Copying chats',
}
export const WAITING = ['created', 'waiting_for_meta']
export const CLOSED = ['cancelled', 'expired', 'superseded']

// A blank named window opened inside the click, so the browser allows it; the Hub address follows when it is known.
// Phones get a new tab. Returns null when the browser blocked it.
export function openSignupWindow(open, mobile, url = 'about:blank') {
  return open(url, SIGNUP_WINDOW, mobile ? '' : 'popup,width=600,height=760') || null
}

// After a page reload Core no longer knows the window's address. An empty address finds a window that is still
// open by its name without loading it again; only a new blank window means that no Facebook steps are running.
export function findSignupWindow(open, mobile) {
  const popup = openSignupWindow(open, mobile, '')
  if (!popup) return { popup: null, running: false }
  try { return { popup, running: popup.location.href !== 'about:blank' } }
  catch { return { popup, running: true } }
}

// Reads run one at a time; a change that comes during a read is read once more after it, never dropped.
export function readQueue(read) {
  let busy = false, waiting = ''
  return async function queued(reason) {
    if (busy) { waiting ||= reason; return }
    busy = true
    try { await read(reason) } finally { busy = false }
    if (waiting) { const next = waiting; waiting = ''; await queued(next) }
  }
}

export function originOf(url) {
  try { return new URL(url).origin } catch { return '' }
}

// Only the Hub's own window may say that this session changed.
export function isSignupMessage(event, hubOrigin, sessionId) {
  const data = event?.data
  return Boolean(hubOrigin && sessionId && event?.origin === originOf(hubOrigin) && data && typeof data === 'object'
    && data.type === SIGNUP_MESSAGE && data.session_id === sessionId)
}

// The page reads the setup again on the Hub window's message, when the tab becomes visible, on a socket
// reconnect and on a realtime onboarding or channel change. `reread(reason)` is the only callback.
export function watchSetup({ hubOrigin, sessionId, reread, onRealtime, target = window, page = document }) {
  const message = event => { if (isSignupMessage(event, hubOrigin(), sessionId())) reread('message') }
  const visible = () => { if (page.visibilityState === 'visible') reread('visible') }
  const realtime = event => {
    if (event?.kind === 'reconnect') reread('reconnect')
    else if (event?.kind === 'onboarding' && (!event.session || !sessionId() || event.session === sessionId())) reread('onboarding')
    else if (event?.kind === 'channel_automation') reread('channels')
  }
  target.addEventListener('message', message)
  page.addEventListener('visibilitychange', visible)
  const stop = onRealtime(realtime)
  return () => { target.removeEventListener('message', message); page.removeEventListener('visibilitychange', visible); stop() }
}

// A session that failed before Relay got access from Facebook has nothing to resume: the customer starts again.
export function needsRestart(session) {
  return session?.state === 'failed' && !session.steps?.some(step => step.name === 'exchange' && step.status === 'done')
}

// Steps that do not apply are not shown: register for a Business app number, the copies for other numbers.
// The Hub skips them only when it gets there, so the flow decides first.
export function signupSteps(session) {
  const flow = session?.flow_actual || session?.flow
  const applies = name => name.startsWith('sync_') ? !flow || flow === 'coexistence' : name !== 'register' || flow !== 'coexistence'
  return (session?.steps || []).filter(step => step.status !== 'skipped' && STEP_LABELS[step.name] && applies(step.name))
    .map(step => ({ ...step, label: STEP_LABELS[step.name] }))
}

// The step the page opens: the one asked for in the address when it is reachable, else the first open one.
// Once a number works, Link records is reachable too; a finished setup opens on Test and finish.
export function activeStep(serverStep, requested) {
  const names = STEPS.map(step => step.name)
  const open = serverStep === 'done' ? 'ready' : names.includes(serverStep) ? serverStep : 'hub'
  const last = ['ready', 'done'].includes(serverStep) ? names.length - 1 : names.indexOf(open)
  const asked = names.indexOf(requested)
  return asked >= 0 && asked <= last ? requested : open
}

export function setupQuery(hash) {
  const query = new URLSearchParams(hash.split('?')[1] || '')
  return { step: query.get('step') || '', session: query.get('session') || '' }
}

export function setupRoute(step, session) {
  const query = new URLSearchParams({ ...(step ? { step } : {}), ...(session ? { session } : {}) })
  return '#/setup' + (query.size ? '?' + query : '')
}

export function limitText(limit) {
  const tiers = { TIER_50: 50, TIER_250: 250, TIER_1K: 1000, TIER_10K: 10000, TIER_100K: 100000 }
  if (tiers[limit] === 250) return '250 customers a day until Meta verifies your business'
  if (tiers[limit]) return `${tiers[limit].toLocaleString('en-US')} customers a day`
  return limit === 'TIER_UNLIMITED' ? 'No daily limit' : 'Not known yet'
}

export function nameStatus(status) {
  const value = String(status || '').toUpperCase()
  if (['APPROVED', 'AVAILABLE_WITHOUT_REVIEW'].includes(value)) return { label: 'Approved', theme: 'green' }
  if (['DECLINED', 'REJECTED', 'EXPIRED'].includes(value)) return { label: 'Declined', theme: 'red' }
  return { label: 'In review', theme: 'amber' }
}

export function managerLink(waba) {
  return 'https://business.facebook.com/wa/manage/home/?waba_id=' + encodeURIComponent(waba || '')
}

export const VERIFICATION_LINK = 'https://business.facebook.com/settings/security'
