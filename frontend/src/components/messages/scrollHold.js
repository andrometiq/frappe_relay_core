// Keeps the thread at the newest message, or keeps one message at the same place,
// while bubbles above or below change size (media, transcripts, async parts, paging).
const BOTTOM_SLACK = 80

// `isEnd` says whether the loaded rows reach the newest message; only then does the bottom follow new rows.
export function createScrollHold(viewport, isEnd = () => true) {
  let hold = 'bottom', expectedTop = null

  const rows = () => [...(viewport()?.querySelectorAll('[data-message]') || [])]
  const offsetOf = (node, row) => row.getBoundingClientRect().top - node.getBoundingClientRect().top
  const isNearBottom = node => node.scrollHeight - node.scrollTop - node.clientHeight < BOTTOM_SLACK

  function apply() {
    const node = viewport()
    if (!node || !hold) return false
    // With newer rows not loaded, pinning to the bottom would page newer rows in again and again.
    if (hold === 'bottom' && !isEnd()) return false
    if (hold === 'bottom') node.scrollTop = node.scrollHeight
    else {
      const row = rows().find(item => item.dataset.message === hold.name)
      if (!row) return false
      // The browser's own scroll anchoring usually keeps the row in place; writing scrollTop then would stop a fling.
      const drift = offsetOf(node, row) - hold.offset
      if (Math.abs(drift) >= 1) node.scrollTop += drift
    }
    expectedTop = node.scrollTop
    return true
  }

  return {
    apply,
    get isAtBottom() { return hold === 'bottom' },
    toBottom() { hold = 'bottom'; return apply() },
    toMessage(name, offset = 20) {
      const previous = hold
      hold = { name, offset }
      if (apply()) return true
      hold = previous
      return false
    },
    // A scroll the code did not make is the reader's: follow the end or keep their first visible message.
    scrolled() {
      const node = viewport()
      if (!node || (expectedTop !== null && Math.abs(node.scrollTop - expectedTop) <= 1)) return
      // Scroll anchoring moves the view down when a bubble grows; only an upward scroll leaves the end.
      if (hold === 'bottom' && isEnd() && expectedTop !== null && node.scrollTop > expectedTop) { apply(); return }
      expectedTop = null
      if (isEnd() && isNearBottom(node)) { hold = 'bottom'; return }
      const top = node.getBoundingClientRect().top
      const row = rows().find(item => item.getBoundingClientRect().bottom > top + 20)
      hold = row ? { name: row.dataset.message, offset: offsetOf(node, row) } : null
    },
  }
}
