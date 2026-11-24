import { ref } from 'vue'

// Phone layout: pages instead of panes. Matches the max-width:768px rules in style.css and mobile.css.
const isMobile = ref(false)
let started = false

// The visual viewport shrinks when the phone keyboard opens; the shell follows it so the composer stays visible.
function followViewport() {
  const viewport = window.visualViewport
  if (!viewport) return
  const root = document.documentElement
  const update = () => {
    root.style.setProperty('--relay-viewport-height', `${Math.round(viewport.height)}px`)
    root.style.setProperty('--relay-viewport-top', `${Math.round(viewport.offsetTop)}px`)
  }
  update()
  viewport.addEventListener('resize', update)
  viewport.addEventListener('scroll', update)
}

// Below this width a chat side panel opens over the chat, so the chat keeps at least 480px beside the inbox columns.
export const DOCKED_PANEL_WIDTH = 1360
// From this width the details panel opens by default.
export const DETAILS_OPEN_WIDTH = 1500

const wide = new Map()
// True while the window is at least `width` pixels wide; one listener per width for the whole app.
export function useWideScreen(width) {
  if (!wide.has(width)) {
    const state = ref(false)
    if (typeof window !== 'undefined' && window.matchMedia) {
      const media = window.matchMedia(`(min-width: ${width}px)`)
      state.value = media.matches
      media.addEventListener('change', event => { state.value = event.matches })
    }
    wide.set(width, state)
  }
  return wide.get(width)
}

export function useMobileLayout() {
  if (!started && typeof window !== 'undefined' && window.matchMedia) {
    started = true
    const media = window.matchMedia('(max-width: 768px)')
    isMobile.value = media.matches
    media.addEventListener('change', event => { isMobile.value = event.matches })
    followViewport()
  }
  return isMobile
}
