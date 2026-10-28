import { getCurrentScope, watch, onScopeDispose } from 'vue'

export function useDebouncedSearch(source, search, invalidate = () => {}) {
  let timer
  const run = () => { clearTimeout(timer); return search() }
  watch(source, () => { clearTimeout(timer); invalidate(); timer = setTimeout(run, 300) })
  if (getCurrentScope()) onScopeDispose(() => clearTimeout(timer))
  return run
}
