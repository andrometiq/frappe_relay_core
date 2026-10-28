import { getCurrentScope, ref, watch, onScopeDispose, toValue, nextTick } from 'vue'

// Re-observe after every page, including pages shorter than the viewport.
// A failed request stays stopped until its owner clears the error or retries.
export function useLoadMore({ loading, hasMore, load, error, root, margin = '200px 0px', preserveScroll = false }) {
  const sentinel = ref(null)
  const pending = ref(false)
  let observer, disposed = false
  const ready = () => !disposed && !pending.value && !toValue(loading) && !!toValue(hasMore) && !toValue(error)
  watch([sentinel, pending, () => toValue(loading), () => toValue(hasMore), () => toValue(error), () => toValue(root)], () => {
    observer?.disconnect()
    if (!sentinel.value || !ready() || typeof IntersectionObserver === 'undefined') return
    const current = new IntersectionObserver(async entries => {
      if (observer !== current || !entries.some(entry => entry.isIntersecting) || !ready()) return
      pending.value = true
      const node = toValue(root), top = node?.scrollTop, height = node?.scrollHeight
      try {
        await load()
        await nextTick()
        if (preserveScroll && node && !disposed) node.scrollTop = top + node.scrollHeight - height
      } finally { pending.value = false }
    }, { root: toValue(root) || null, rootMargin: margin })
    observer = current
    observer.observe(sentinel.value)
  }, { flush: 'post' })
  if (getCurrentScope()) onScopeDispose(() => { disposed = true; observer?.disconnect() })
  return sentinel
}
