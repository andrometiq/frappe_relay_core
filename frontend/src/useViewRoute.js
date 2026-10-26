import { ref, watch, onMounted, onBeforeUnmount } from 'vue'

// Old hashes of screens that moved into a section tab.
const MOVED_ROUTES = {
  '/incoming': '/contacts?tab=unlinked',
  '/templates': '/whatsapp',
  '/campaigns': '/whatsapp?tab=campaigns',
}

export function movedRoute(hash) {
  return MOVED_ROUTES[hash.slice(1).split('?')[0]] || null
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
