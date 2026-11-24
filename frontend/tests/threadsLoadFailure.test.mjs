import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { computed, effectScope, nextTick, ref, watch } from 'vue'
import { coreApi } from '../src/services/coreApi.js'

test('a failed threads read shows its error with Retry instead of loading forever, and Retry reads again', async t => {
  const previous = { fetch: globalThis.fetch, window: globalThis.window }
  t.after(() => Object.assign(globalThis, previous))
  globalThis.window = { frappe: { csrf_token: 'local-fixture' } }
  let fail = true, reads = 0
  globalThis.fetch = async () => {
    reads++
    return fail ? Response.json({ exc_type: 'PermissionError', message: 'Not permitted' }, { status: 403 })
      : Response.json({ message: { items: [{ key: 'R1|CH|91', channel: 'CH' }] } })
  }
  const source = (await readFile(new URL('../src/composables/useConversationThreads.js', import.meta.url), 'utf8'))
    .replace(/^import .*\n/gm, '').replace('export function', 'function')
  const useConversationThreads = new Function('computed', 'ref', 'watch', 'coreApi', 'useRealtimeRefresh', source + '\nreturn useConversationThreads')(
    computed, ref, watch, coreApi, () => {})
  const scope = effectScope()
  t.after(() => scope.stop())
  const threads = scope.run(() => useConversationThreads({ selected: ref('RELAY-CON-1'), businessType: ref(''), businessName: ref('') }))
  const settle = async () => { for (let i = 0; i < 10 && threads.loading.value; i++) await new Promise(resolve => setTimeout(resolve, 5)); await nextTick() }
  await settle()
  assert.equal(threads.ready.value, false)
  assert.ok(threads.error.value, 'The failure is kept for the chat to show')
  fail = false
  await threads.load()
  assert.deepEqual([threads.ready.value, threads.error.value, threads.items.value.length, reads], [true, '', 1, 2])

  const view = await readFile(new URL('../src/components/ConnectedMessages.vue', import.meta.url), 'utf8')
  assert.match(view, /const threadsFailed = computed\(\(\) => !threadOpen\.value && !threads\.ready\.value && !!threads\.error\.value && !threads\.loading\.value\)/)
  assert.match(view, /<WorkspaceState v-else-if="threadsFailed"[^>]*\n?[^>]*title="Could not load this chat"/)
  assert.match(view, /<div v-else-if="active && !loadFailed && !threadsFailed" class="composer-dock"/, 'A failed read hides the "Start one with a template" footer')
  assert.match(view, /<Button label="Retry" variant="solid" icon-left="refresh-cw" @click="threads\.load\(\)" \/>/)
})
