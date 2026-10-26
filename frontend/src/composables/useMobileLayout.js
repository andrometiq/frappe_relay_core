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
