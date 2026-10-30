import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import * as Vue from 'vue'
import { compile } from '@vue/compiler-dom'
import { renderToString } from 'vue/server-renderer'
import { contactColumns, importCount, importFileError, importState } from '../src/services/contactImport.js'

test('preview states count valid actions, skipped duplicates and row errors', () => {
  const rows = [ { status: 'create' }, { status: 'link' }, { status: 'skip' }, { status: 'error', reason: 'Choose an enabled business type.' } ]
  assert.deepEqual(importState({ rows, counts: { created: 1, linked: 1, skipped: 1, errors: 1 } }),
    { rows, valid: 2, skipped: 1, errors: 1, error: '' })
  assert.equal(importState({ error: 'The file has no contact rows.' }).valid, 0)
  assert.equal(importState(null).valid, 0)
  assert.equal(importState({ counts: { errors: 2000 } }).valid, 0)
  assert.deepEqual(contactColumns, ['Mobile', 'Email', 'Contact name', 'Business type', 'Business record'])
})
test('file checks accept xlsx and csv and reject oversized or unsupported files', () => {
  for (const name of ['contacts.xlsx', 'contacts.CSV']) assert.equal(importFileError({ name, size: 200 }), '')
  assert.match(importFileError({ name: 'contacts.xls', size: 200 }), /Choose an Excel/)
  assert.match(importFileError({ name: 'contacts.csv', size: 6 * 1024 * 1024 }), /smaller than 5 MB/)
})

test('dialog summaries and import action pluralize zero, one and multiple counts', async () => {
  const source = await readFile(new URL('../src/components/ContactImportDialog.vue', import.meta.url), 'utf8')
  const summary = source.match(/<p role="status">.*?<\/p>/)[0]
  const action = source.match(/<Button v-if="!done && result\?\.counts".*?\/>/)[0]
  const render = new Function('Vue', compile(summary + action, { prefixIdentifiers: true }).code)(Vue)
  for (const count of [0, 1, 2]) {
    for (const done of [false, true]) {
      const app = Vue.createSSRApp({ render,
        components: { Button: { props: ['label'], setup: props => () => Vue.h('button', props.label) } },
        setup: () => ({ done, busy: false, apply() {}, importCount,
          result: { counts: { created: count, linked: count } }, state: { valid: count, skipped: count, errors: count } }) })
      const html = await renderToString(app), suffix = count === 1 ? '' : 's'
      assert.ok(html.includes(`${count} error${suffix}</p>`))
      assert.ok(html.includes(`${count} skipped`))
      if (done) assert.ok(html.includes(`${count} contact${suffix} created · ${count} link${suffix} added`))
      else {
        assert.ok(html.includes(`${count} valid row${suffix} ·`))
        assert.ok(html.includes(`>Import ${count} valid row${suffix}</button>`))
      }
    }
  }
})
