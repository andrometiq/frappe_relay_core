// A list of rows that all have one height: which rows to render, and where to scroll so the reader's rows stay put.

// The rows in view plus `overscan` rows above and below.
export function rowWindow({ count, rowHeight, scrollTop, viewportHeight, overscan = 6 }) {
  const top = Math.max(0, scrollTop)
  const start = Math.max(0, Math.min(count, Math.floor(top / rowHeight)) - overscan)
  const end = Math.min(count, Math.ceil((top + viewportHeight) / rowHeight) + overscan)
  return { start, end }
}

// After the rows change, the scroll offset that keeps the first steady row in view at the same place.
// A steady row is still listed and still followed by the same row, so a row that moved to the top is skipped.
// At the top of the list the offset stays 0, so new rows show.
export function anchoredScrollTop({ scrollTop, rowHeight, previous, next, key, scan = 50 }) {
  if (scrollTop < 1 || !previous.length || !next.length) return scrollTop
  const places = new Map(next.map((row, index) => [key(row), index]))
  const first = Math.min(previous.length - 1, Math.floor(scrollTop / rowHeight))
  for (let index = first; index < Math.min(previous.length, first + scan); index++) {
    const place = places.get(key(previous[index]))
    const last = index === previous.length - 1
    if (place !== undefined && (last || places.get(key(previous[index + 1])) === place + 1)) return scrollTop + (place - index) * rowHeight
  }
  return scrollTop
}
