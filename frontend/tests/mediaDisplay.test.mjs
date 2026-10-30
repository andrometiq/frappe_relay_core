import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import * as Vue from 'vue'
import { attachmentKind, documentType } from '../src/components/messageContent.js'

const read = path => readFile(new URL(path, import.meta.url), 'utf8')
const template = source => source.slice(source.indexOf('<template>') + 10, source.lastIndexOf('</template>'))

async function render(state) {
  const { compile } = await import('@vue/compiler-dom')
  const { renderToString } = await import('@vue/server-renderer')
  const code = compile(template(await read('../src/components/AttachmentViewer.vue')), { mode: 'function', prefixIdentifiers: true }).code
  const view = {
    message: { name: 'RELAY-MSG-1' }, link: '', downloadable: true, media: null, error: null, loading: false, shown: false,
    frame: null, lightbox: null, filename: '', size: '', audioLabel: 'Audio', documentType, load() {}, save() {}, fail() {}, ...state,
  }
  view.kind = attachmentKind(view.data.kind)
  view.label = { image: 'Photo', video: 'Video', audio: view.audioLabel, document: 'Document' }[view.kind]
  const app = Vue.createSSRApp({ render: new Function('Vue', code)(Vue), setup: () => view })
  app.component('FeatherIcon', { props: ['name'], setup: props => () => Vue.h('i', { 'data-icon': props.name }) })
  return renderToString(app, {})
}

test('attachment kinds group provider kinds into four viewers', () => {
  assert.deepEqual(['photo', 'image', 'video', 'animation', 'audio', 'voice', 'document', 'sticker'].map(attachmentKind),
    ['image', 'image', 'video', 'video', 'audio', 'audio', 'document', 'document'])
})

test('a photo keeps its whole picture and opens the full viewer', async () => {
  const loading = await render({ data: { kind: 'image' }, loading: true })
  assert.match(loading, /class="media-visual"/)
  assert.match(loading, /Loading photo…/)

  const shown = await render({ data: { kind: 'image', caption: 'Offer' }, media: { url: 'blob:photo' }, shown: true })
  assert.match(shown, /class="media-visual is-shown"/)
  assert.match(shown, /<button[^>]*class="media-open"[^>]*aria-label="Open Offer"/)
  assert.match(shown, /<img src="blob:photo"[^>]*class="media-picture"/)
  assert.doesNotMatch(shown, /Loading photo/)
})

test('a video is a real player with its first frame, never autoplay', async () => {
  const html = await render({ data: { kind: 'video' }, media: { url: 'blob:clip' }, shown: true })
  assert.match(html, /<video[^>]*src="blob:clip"[^>]*controls[^>]*playsinline[^>]*preload="metadata"[^>]*class="media-picture"/)
  assert.doesNotMatch(html, /autoplay|Play video/)
})

test('unavailable media shows one compact card with the reason', async () => {
  const html = await render({ data: { kind: 'video' }, error: { message: 'Media could not be loaded.', retry: true } })
  assert.match(html, /class="media-unavailable" role="alert"/)
  assert.match(html, /Video unavailable/)
  assert.match(html, /Media could not be loaded\./)
  assert.match(html, />Retry</)
  assert.doesNotMatch(html, /media-visual|<video/)
})

test('documents show a file card that downloads, opens a link, or stays plain', async () => {
  const kept = await render({ data: { kind: 'document', media: { file_name: 'March bill.pdf' } }, filename: 'March bill.pdf', size: '3.3 KB' })
  assert.match(kept, /March bill\.pdf/)
  assert.match(kept, /PDF · 3\.3 KB/)
  assert.match(kept, /aria-label="Download March bill\.pdf"/)

  const linked = await render({ data: { kind: 'document' }, link: 'https://cdn.example.com/bill.pdf', filename: 'bill.pdf' })
  assert.match(linked, /aria-label="Open bill\.pdf"[\s\S]*data-icon="external-link"/)

  const plain = await render({ data: { kind: 'document' }, downloadable: false, filename: 'Order.pdf' })
  assert.doesNotMatch(plain, /media-download/)
})

test('template header media uses the same viewer as received media', async () => {
  const source = template(await read('../src/components/MessageContent.vue'))
  const header = source.slice(source.indexOf('class="message-template"'), source.indexOf('<strong v-if="template.header">'))
  assert.match(header, /<AttachmentViewer[^>]*:link="header\.kept \? '' : header\.link"/)
  assert.doesNotMatch(header, /<img|<video|media-document/)
})

test('media fits inside the bubble without cropping', async () => {
  const css = await read('../src/style.css')
  const picture = css.match(/\.media-picture\{([^}]*)\}/)[1]
  assert.match(picture, /object-fit:contain/)
  assert.match(picture, /max-width:min\(320px,75vw\)/)
  assert.match(picture, /max-height:360px/)
  assert.doesNotMatch(css, /\.media-[a-z-]+\{[^}]*object-fit:cover/)
})
