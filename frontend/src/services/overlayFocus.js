export function focusableElements(root) {
  return [...(root?.querySelectorAll('button:not(:disabled), [href], input:not(:disabled), textarea:not(:disabled), select:not(:disabled), summary, [tabindex="0"]') || [])]
    .filter(node => node.getClientRects().length)
}
// Teleported menus cannot rely on the trigger's DOM ancestry for keyboard events.
export function overlayKeydown(event, root, close, { arrows = false, trap = true } = {}) {
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); return }
  const nodes = focusableElements(root)
  if (!nodes.length) return
  const index = nodes.indexOf(document.activeElement)
  if (event.key === 'Tab' && trap) {
    if (event.shiftKey && index <= 0) { event.preventDefault(); nodes.at(-1).focus() }
    else if (!event.shiftKey && (index === nodes.length - 1 || index < 0)) { event.preventDefault(); nodes[0].focus() }
  }
  if (!arrows || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key) || event.target.matches('input, textarea, select')) return
  event.preventDefault()
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? nodes.length - 1
    : (index + (event.key === 'ArrowDown' ? 1 : -1) + nodes.length) % nodes.length
  nodes[next].focus()
}
