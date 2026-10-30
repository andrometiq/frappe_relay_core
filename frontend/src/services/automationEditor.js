export function newConfiguration(skill) {
  const common = { title: '', enabled: 0, channel: '', business_doctype: '', run_as_user: '' }
  return skill ? { ...common, ai_model: '', handoff_owner: '', mode: 'Shadow', daily_limit: 100, target: '', instructions: '', reply_style: '', search_confirmation: 'Always', exact_trigger: '', execution_policy: 'Ticket only', allowed_tools: '[]', allowed_actions: '[]' }
    : { ...common, source_doctype: '', event: 'on_submit', recipient_field: '', template: '', parameter_mapping: '[]', contact: '', use_preferences: 0, telegram_body: '', email_subject: '', email_body: '', email_signature: '',
      condition: '', recipients: '', contact_field: '', attachment_type: '', print_format: '', report_name: '', report_filters: '', file_name: '' }
}

// Existing configurations can reference a channel outside the current account's
// options. Keep that selection visible without offering other hidden channels.
export function configurationChannels(channels, selected) {
  return selected && !channels.some(row => row.name === selected)
    ? [...channels, { name: selected }]
    : channels
}
export function configurationChannelOptions(channels, selected) {
  const options = configurationChannels(channels, selected).map(row => ({
    value: row.name,
    label: row.channel
      ? [...new Set([row.channel, row.label, row.address].filter(Boolean))].join(' · ') +
        (!row.label && !row.address ? ` · ${row.name}` : '')
      : 'Saved channel (unavailable)',
  }))
  return options.map(option => options.filter(row => row.label === option.label).length > 1
    ? { ...option, label: `${option.label} · ${option.value}` } : option)
}
export function toolRows(value) {
  return JSON.parse(value || '[]').map(row => ({ ...row, fields: [...row.fields], identity_fields: { ...row.identity_fields } }))
}
export function configurationValues(draft, skill, tools, parameters, actions = []) {
  const values = Object.fromEntries(Object.keys(newConfiguration(skill)).map(key => [key, draft[key]]))
  values.enabled = Number(Boolean(values.enabled))
  if (skill) {
    values.daily_limit = Number(values.daily_limit)
    values.allowed_tools = JSON.stringify(tools.map(row => ({ ...row, fields: Array.isArray(row.fields) ? [...row.fields] : row.fields.split(',').map(field => field.trim()).filter(Boolean) })))
    values.allowed_actions = JSON.stringify(values.execution_policy === 'Execute' ? actions : [])
  } else { values.use_preferences = Number(Boolean(values.use_preferences)); values.parameter_mapping = JSON.stringify(parameters.split('\n').map(field => field.trim()).filter(Boolean)) }
  return values
}
export function eventDescription(row) {
  const event = { on_submit: 'on submit', after_insert: 'when created', on_cancel: 'on cancel' }[row.event] || 'choose an event'
  return `${row.source_doctype || 'Source document'} → ${row.business_doctype || 'Recipient party'} · ${event}`
}
export function messagePreview(body, parameters) {
  const fields = parameters.split('\n').map(field => field.trim()).filter(Boolean)
  return body.replace(/\{\{\s*(\d+)\s*\}\}/g, (_, number) => `[${fields[Number(number) - 1] || `Parameter ${number}`}]`)
}
export function toolCount(value) {
  try { const rows = JSON.parse(value || '[]'); return Array.isArray(rows) ? rows.length : 0 } catch { return 0 }
}

export function variantPreview(body, parameters) {
  const fields = parameters.split('\n').map(field => field.trim()).filter(Boolean)
  return String(body || '').replace(/\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g, (_, field) => fields.includes(field) ? `[${field}]` : `[Undeclared: ${field}]`)
}

export function referenceName(value) {
  return String(value || '').replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase())
}
export function moveAction(actions, index, delta) {
  const destination = index + delta
  if (destination < 0 || destination >= actions.length) return
  ;[actions[index], actions[destination]] = [actions[destination], actions[index]]
}
export function eventErrors(draft, references, actions, provider) {
  const errors = []
  if (!draft.title?.trim()) errors.push('Give the event a readable title.')
  if (!draft.business_doctype) errors.push('Choose a business type.')
  if (!draft.instructions?.trim()) errors.push('Write the skill instructions.')
  for (const [key, limit] of [['target', 2000], ['instructions', 8000], ['reply_style', 2000], ['exact_trigger', 140]]) {
    if ((draft[key] || '').length > limit) errors.push(`${referenceName(key)} is too long.`)
  }
  if (draft.enabled && (!draft.target?.trim() || !draft.channel || !draft.ai_model || !draft.run_as_user || !draft.handoff_owner)) errors.push('Enabled events need a target, channel, model, run-as user and handoff owner.')
  if (!(Number(draft.daily_limit) >= 1 && Number(draft.daily_limit) <= 1000)) errors.push('Choose a daily model limit from 1 to 1000.')
  for (const row of references) {
    if (!row.report) errors.push('Choose a configured report; legacy record references cannot answer data questions.')
    if (!row.name || !row.doctype || !row.scope_field || !row.fields.length) errors.push('Complete each read reference and choose readable fields.')
    if (!row.company_field || !row.identity_fields?.[provider] || row.identity_anchor !== draft.business_doctype) errors.push('Choose the channel, authenticated identity field and company field for every reference.')
  }
  if (new Set(references.map(row => row.name)).size !== references.length) errors.push('Read references must be distinct.')
  if (draft.execution_policy === 'Execute' && actions.some(row => row.action === 'create_draft' && (!row.doctype || !row.fields.length))) errors.push('Choose a draft DocType and its required fields.')
  return [...new Set(errors)]
}
// Templates are searched on the server by name; a fixed number limits them to its WABA.
export function templateField(draft, readOnly, currentLabel) {
  return {
    label: 'Approved WhatsApp template', method: 'business_events.template_options',
    params: draft.use_preferences || !draft.channel ? {} : { channel: draft.channel },
    placeholder: 'Search templates by name…', required: Boolean(draft.enabled) && !draft.use_preferences, readOnly,
    initialOptions: draft.template ? [{ value: draft.template, label: currentLabel }] : [],
  }
}
