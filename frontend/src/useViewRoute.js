import { ref, watch, onMounted, onBeforeUnmount } from 'vue'

// Old hashes of screens that moved into a section tab, and the WhatsApp Core screens a /whatsapp link opens.
const MOVED_ROUTES = {
  '/incoming': '/contacts?tab=unlinked',
  '/templates': '/whatsapp',
  '/campaigns': '/whatsapp?tab=campaigns',
  '/inbox': '/messages',
  '/ai-queue': '/tickets',
  '/groups': '/messages',
  '/calling': '/messages',
  '/health': '/activity',
  '/flows/automation': '/flows',
}

// WhatsApp Core links that name a record: #/inbox/<conversation>, #/flows/<flow>, #/flows/meta/<form>.
const MOVED_PREFIXES = [
  [/^\/inbox\/([^/]+)$/, id => '/messages?legacy_conversation=' + encodeURIComponent(id)],
  [/^\/flows\/meta\/[^/]+$/, () => '/whatsapp?tab=forms'],
  [/^\/flows\/(?:automation\/)?([^/]+)$/, id => '/flows?legacy=' + encodeURIComponent(id)],
]

export function movedRoute(hash) {
  const path = hash.slice(1).split('?')[0]
  if (MOVED_ROUTES[path]) return MOVED_ROUTES[path]
  for (const [pattern, target] of MOVED_PREFIXES) {
    const match = path.match(pattern)
    if (match) return target(decodeURIComponent(match[1] || ''))
  }
  return null
}

// The section tab named in the hash query, such as #/whatsapp?tab=campaigns.
export function routeTab(hash, fallback) {
  return new URLSearchParams(hash.split('?')[1] || '').get('tab') || fallback
}

// Hash routes work on the static preview and Hub server without rewrite rules.
export function useViewRoute(views, fallback) {
  const paths = new Map(views.map(view => ['/' + view.toLowerCase().replaceAll(' ', '-'), view]))
  const pathFor = view => [...paths].find(([, value]) => value === view)?.[0]
  const read = () => paths.get(window.location.hash.slice(1).split('?')[0]) || fallback
  const redirect = () => {
    const target = movedRoute(window.location.hash)
    if (target) history.replaceState(null, '', '#' + target)
  }
  redirect()
  const view = ref(read())
  function receive() {
    redirect()
    view.value = read()
    if (!paths.has(window.location.hash.slice(1).split('?')[0])) {
      history.replaceState(null, '', '#' + pathFor(view.value))
    }
  }
  watch(view, value => {
    const path = pathFor(value)
    if (path && window.location.hash.slice(1).split('?')[0] !== path) window.location.hash = path
  })
  onMounted(() => { receive(); window.addEventListener('hashchange', receive) })
  onBeforeUnmount(() => window.removeEventListener('hashchange', receive))
  return view
}

// Drill-in views: opening from a list adds one history entry and switching replaces it, so Back returns to the list.
export function openRoute(route, replace) {
  if (location.hash === route) return
  if (replace) window.history.replaceState(window.history.state, '', route)
  else window.history.pushState({ relayList: true }, '', route)
}

export function closeRoute(listRoute) {
  if (window.history.state?.relayList) window.history.back()
  else if (location.hash !== listRoute) window.history.replaceState(null, '', listRoute)
}
