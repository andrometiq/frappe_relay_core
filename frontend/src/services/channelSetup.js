// Labels and choices for the channel accounts a site sets up in Relay. The Hub keeps every credential; these
// helpers only read the status it reports. WhatsApp numbers, Telegram bots and mailboxes share them.

// A check or sync sends several channels events; an Account card reloads once a second at most, since each reload asks the Hub.
export const ACCOUNTS_RELOAD_DELAY = 1000

const CONNECTION = {
  connected: ['Connected', 'green'],
  unchecked: ['Not checked yet', 'gray'],
  failed: ['Check failed', 'red'],
  reconnect_required: ['Connect again', 'red'],
  disabled: ['Off', 'gray'],
}

// The badge of an account: Meta removing the app wins over the last check.
export function connectionBadge(account) {
  if (account?.health?.partner_status === 'removed') return { label: 'Removed by Meta', theme: 'red' }
  if (account && !account.enabled) return { label: 'Off', theme: 'gray' }
  const [label, theme] = CONNECTION[account?.health?.connection_status] || ['Not checked yet', 'gray']
  return { label, theme }
}

// Only Embedded Signup gives Relay new access, so these accounts show Connect again instead of Check.
export function needsReconnect(account) {
  const health = account?.health || {}
  return health.partner_status === 'removed' || health.connection_status === 'reconnect_required'
}

export function webhookText(health = {}) {
  if (health.webhook_subscribed === true) return 'Meta sends this number’s messages to Relay.'
  if (health.webhook_subscribed === false) return 'Meta is not sending this number’s messages to Relay. Select Check connection to repair it.'
  return 'Not checked yet.'
}

// The delivery rows of the Account card, as plain text.
export function deliveryRows(health = {}, format = value => value) {
  const delivery = health.delivery || {}
  const waiting = Number(delivery.callback_pending || 0), failed = Number(delivery.callback_failed || 0)
  return [
    { name: 'Last message from Meta', text: delivery.webhook_received_at ? format(delivery.webhook_received_at) : 'None yet' },
    { name: 'Last message saved in Relay', text: delivery.core_confirmed_at ? format(delivery.core_confirmed_at) : 'None yet' },
    { name: 'Waiting to reach Relay', text: waiting ? `${waiting}${failed ? ` (${failed} retrying)` : ''}` : 'None' },
  ]
}

// Switches a System Manager can change on a number. Groups and calls stay off in this version.
export const SWITCHES = [
  { name: 'enabled', label: 'Number is on', help: 'When off, Relay does not send or receive on this number.' },
  { name: 'templates', label: 'Message templates', help: 'Create and send approved templates and forms from this number.' },
  { name: 'sync_metadata', label: 'Hourly Meta sync', help: 'Read quality, limits and templates from Meta every hour.' },
]

export function switchValue(account, name) {
  return name === 'enabled' ? !!account?.enabled : !!account?.health?.settings?.[name]
}

export const PIN_TEXT = 'Relay keeps this number’s two-step PIN. Nobody needs to know it. To move the number to another provider, remove it here first.'

export function removalText(result) {
  if (!result?.removed) return ''
  if (result.deregistered) return 'The number is removed from Relay and can now move to another provider. Its chats stay in Relay.'
  return 'The number is removed from Relay. Meta did not confirm the deregistration; check the number in WhatsApp Manager before you move it. Its chats stay in Relay.'
}

export const VERTICALS = [
  ['UNDEFINED', 'Not set'], ['APPAREL', 'Clothing and apparel'], ['AUTO', 'Automotive'], ['BEAUTY', 'Beauty, spa and salon'],
  ['EDU', 'Education'], ['ENTERTAIN', 'Entertainment'], ['EVENT_PLAN', 'Event planning'], ['FINANCE', 'Finance and banking'],
  ['GROCERY', 'Food and grocery'], ['GOVT', 'Public service'], ['HOTEL', 'Hotel and lodging'], ['HEALTH', 'Medical and health'],
  ['NONPROFIT', 'Non-profit'], ['PROF_SERVICES', 'Professional services'], ['RETAIL', 'Shopping and retail'],
  ['TRAVEL', 'Travel and transport'], ['RESTAURANT', 'Restaurant'], ['OTHER', 'Other'],
].map(([value, label]) => ({ value, label }))

// The profile form keeps websites as one address per line.
export function profileDraft(profile = {}) {
  return {
    about: profile.about || '', address: profile.address || '', description: profile.description || '',
    email: profile.email || '', websites: (profile.websites || []).join('\n'), vertical: profile.vertical || 'UNDEFINED',
  }
}

// Only the fields the person changed go to the Hub, so an untouched field keeps Meta's value.
export function profileChanges(original, draft) {
  const before = profileDraft(original), changes = {}
  for (const name of ['about', 'address', 'description', 'email', 'vertical']) {
    if (draft[name].trim() !== before[name].trim()) changes[name] = draft[name].trim()
  }
  const sites = draft.websites.split('\n').map(item => item.trim()).filter(Boolean)
  if (sites.join('\n') !== before.websites) changes.websites = sites
  return changes
}

export const PHOTO_TYPES = ['image/jpeg', 'image/png']
export const PHOTO_BYTES = 5 * 1024 * 1024

export function photoProblem(file) {
  if (!file) return ''
  if (!PHOTO_TYPES.includes(file.type)) return 'Choose a JPEG or PNG photo.'
  if (file.size > PHOTO_BYTES) return 'The photo must be at most 5 MB.'
  return ''
}

const WEBHOOK = {
  registered: ['Connected', 'green'],
  not_registered: ['Not receiving', 'orange'],
  failed: ['Check failed', 'red'],
  removed: ['Removed', 'gray'],
}

// The badge of a Telegram bot: off wins, then the webhook state of the last check.
export function botBadge(account) {
  if (account && !account.enabled) return { label: 'Off', theme: 'gray' }
  const [label, theme] = WEBHOOK[account?.health?.webhook_status] || ['Not checked yet', 'gray']
  return { label, theme }
}

export function botRows(health = {}) {
  const receiving = {
    registered: 'Telegram sends this bot’s messages to Relay.',
    failed: 'The last check failed. Select Check connection to try again.',
  }[health.webhook_status] || health.webhook_missing || 'Telegram is not sending this bot’s messages to Relay. Select Check connection to repair it.'
  return [
    { name: 'Bot', text: health.username ? '@' + health.username : 'Not read yet' },
    { name: 'Messages from Telegram', text: receiving },
    { name: 'Bot token', text: health.token_saved ? 'Kept by Relay Hub' : 'Missing. Save a new token.' },
  ]
}

const SIGN_IN = { connected: 'Signed in', failed: 'Sign-in failed', not_configured: 'Not set up' }

// The badge of a mailbox: off wins, then the last sign-in check.
export function mailboxBadge(account) {
  return connectionBadge({ enabled: account?.enabled, health: { connection_status: account?.health?.connection_status } })
}

export function mailboxRows(health = {}, format = value => value) {
  const sync = (health.sync || [])[0] || {}
  return [
    { name: 'Sending (SMTP)', text: SIGN_IN[health.smtp_status] || 'Not checked yet' },
    { name: 'Receiving (IMAP)', text: SIGN_IN[health.imap_status] || 'Not checked yet' },
    { name: 'Last mail check', text: sync.error || (sync.last_sync ? format(sync.last_sync) : 'Not yet') },
    { name: 'Rejected messages', text: health.rejected ? String(health.rejected) : 'None' },
  ]
}

// Mailbox form fields. Passwords are write-only: the form starts them blank and never shows a saved one.
export const MAIL_FIELDS = ['host', 'port', 'username', 'imap_host', 'imap_port', 'imap_username', 'imap_folder', 'trusted_authserv_id', 'trusted_dsn_domain']
export const SECRET_FIELDS = ['password', 'imap_password', 'bot_token']

export function mailboxDraft(health = {}) {
  const server = health.server || {}
  const draft = { password: '', imap_password: '' }
  for (const name of MAIL_FIELDS) draft[name] = server[name] == null ? '' : String(server[name])
  return draft
}

// Only fields the person changed, and only passwords the person typed, go to the Hub.
export function mailboxChanges(health, draft) {
  const before = mailboxDraft(health), changes = {}
  for (const name of MAIL_FIELDS) if (String(draft[name] ?? '').trim() !== before[name].trim() && String(draft[name] ?? '').trim()) changes[name] = String(draft[name]).trim()
  for (const name of ['password', 'imap_password']) if (draft[name]) changes[name] = draft[name]
  return changes
}

// A new mailbox: blank optional fields are left out, so the Hub uses its defaults.
export function mailboxConnect(form) {
  const values = {}
  for (const [name, value] of Object.entries(form)) if (String(value ?? '').trim()) values[name] = SECRET_FIELDS.includes(name) ? value : String(value).trim()
  return values
}

// Clears every token and password of a form after a submit, sent or not.
export function clearSecrets(form) {
  for (const name of SECRET_FIELDS) if (name in form) form[name] = ''
}
