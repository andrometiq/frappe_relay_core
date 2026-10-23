<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { fetchTgs } from './tgsSticker'
const props = defineProps({ source: { type: String, required: true } })
const container = ref(null), loading = ref(false), ready = ref(false), failed = ref(false), playing = ref(true)
let animation, controller, observer, loadTimeout, visible = false, generation = 0, mounted = false
const syncPlayback = () => {
  if (!animation) return
  if (visible && !document.hidden && playing.value) animation.play()
  else animation.pause()
}
const dispose = () => {
  generation++; clearTimeout(loadTimeout); controller?.abort(); controller = undefined
  animation?.destroy(); animation = undefined
  ready.value = false; loading.value = false
}
async function load() {
  if (loading.value || ready.value) return
  dispose(); failed.value = false; loading.value = true; controller = new AbortController()
  const current = generation, signal = controller.signal
  loadTimeout = setTimeout(() => { if (current === generation) { dispose(); failed.value = true } }, 15000)
  try {
    const [data, module] = await Promise.all([
      fetchTgs(props.source, signal),
      import('lottie-web/build/player/lottie_light_canvas'),
    ])
    if (!mounted || signal.aborted || current !== generation) return
    const player = module.default || module
    animation = player.loadAnimation({ container: container.value, renderer: 'canvas', loop: true, autoplay: false, animationData: data,
      rendererSettings: { dpr: 1, clearCanvas: true, preserveAspectRatio: 'xMidYMid meet' } })
    animation.setSubframe(false)
    animation.addEventListener('DOMLoaded', () => { if (current === generation) { clearTimeout(loadTimeout); ready.value = true; loading.value = false; syncPlayback() } })
    const unavailable = () => { if (current === generation) { dispose(); failed.value = true } }
    animation.addEventListener('data_failed', unavailable)
    animation.addEventListener('error', unavailable)
  } catch (error) {
    if (signal.aborted || current !== generation) return
    dispose(); failed.value = true
  }
}
function toggle() { playing.value = !playing.value; syncPlayback() }
watch(() => props.source, () => { dispose(); failed.value = false; playing.value = true })
onMounted(() => {
  mounted = true
  playing.value = !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  if (typeof IntersectionObserver === 'function') {
    observer = new IntersectionObserver(entries => { visible = Boolean(entries[0]?.isIntersecting); syncPlayback() })
    observer.observe(container.value)
  } else visible = true
  document.addEventListener('visibilitychange', syncPlayback)
})
onBeforeUnmount(() => { mounted = false; observer?.disconnect(); document.removeEventListener('visibilitychange', syncPlayback); dispose() })
</script>

<template>
  <div class="tgs-sticker" :data-animation-state="failed ? 'failed' : ready ? (playing ? 'playing' : 'paused') : loading ? 'loading' : 'idle'">
    <div ref="container" role="img" aria-label="Animated sticker" class="tgs-canvas" v-show="loading || ready" />
    <button v-if="!ready" class="rounded border px-3 py-2" :disabled="loading" @click="load">{{ loading ? 'Loading sticker…' : failed ? 'Retry animated sticker' : 'Load animated sticker' }}</button>
    <button v-else class="text-xs underline" @click="toggle">{{ playing ? 'Pause sticker' : 'Play sticker' }}</button>
    <p v-if="failed" role="status" class="text-xs">Animated sticker unavailable.</p>
  </div>
</template>

<style scoped>
.tgs-canvas { width: min(192px, 100%); aspect-ratio: 1; }
.tgs-canvas :deep(canvas) { max-width: 100%; max-height: 192px; }
</style>
