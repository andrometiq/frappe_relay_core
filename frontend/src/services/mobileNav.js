// Phone tab bar: these pages get a tab when the user may see them; every other allowed page goes to More.
const TAB_PAGES = ['Messages', 'Tickets', 'WhatsApp']

export function splitMobileNav(items) {
  const tabs = TAB_PAGES.map(name => items.find(item => item.name === name)).filter(Boolean)
  return { tabs, more: items.filter(item => !TAB_PAGES.includes(item.name)) }
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
