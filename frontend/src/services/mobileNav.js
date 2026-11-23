// Phone tab bar: Inbox, Tickets and Templates get a tab when the user may see them; every other allowed page goes to More.
// A tab may rename its page and open one section of it, as Templates does for WhatsApp.
const TABS = [
  { name: 'Messages', label: 'Inbox', icon: 'inbox' },
  { name: 'Tickets', label: 'Tickets', icon: 'ticket' },
  { name: 'WhatsApp', label: 'Templates', icon: 'layout', section: 'templates' },
]

export function splitMobileNav(items) {
  const tabs = TABS.filter(tab => items.some(item => item.name === tab.name))
  return { tabs, more: items.filter(item => !TABS.some(tab => tab.name === item.name)) }
}

// The contact info page is the open chat route plus info=1, so Back returns to the chat.
export function contactInfoRoute(hash) {
  const [path, query = ''] = hash.split('?')
  const params = new URLSearchParams(query)
  params.set('info', '1')
  return `${path}?${params}`
}

export function isContactInfoRoute(hash) {
  return new URLSearchParams(hash.split('?')[1] || '').get('info') === '1'
}
