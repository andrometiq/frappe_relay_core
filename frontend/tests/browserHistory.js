// Browser history stand-in: a stack of { hash, state } entries that fires popstate on back().
export function browser(t, hash) {
  const previous = {}
  for (const key of ['document', 'window', 'sessionStorage', 'location']) previous[key] = globalThis[key]
  const entries = [{ hash, state: null }], listeners = []
  let index = 0
  const location = { hash }
  const move = (entry, replace) => {
    if (!replace) entries.splice(++index, Infinity, entry)
    else entries[index] = entry
    location.hash = entry.hash
  }
  const history = {
    get state() { return entries[index].state },
    get length() { return entries.length },
    pushState: (state, title, url) => move({ hash: url, state }, false),
    replaceState: (state, title, url) => move({ hash: url, state }, true),
    back() { index -= 1; location.hash = entries[index].hash; for (const listener of listeners) listener() },
  }
  globalThis.location = location
  globalThis.window = { history, addEventListener: (type, listener) => listeners.push(listener), removeEventListener() {} }
  globalThis.document = { visibilityState: 'visible' }
  globalThis.sessionStorage = { getItem() {}, setItem() {}, removeItem() {} }
  t.after(() => { for (const [key, value] of Object.entries(previous)) globalThis[key] = value })
  return { history, location, entries: () => entries.slice(0, index + 1).map(entry => entry.hash) }
}
