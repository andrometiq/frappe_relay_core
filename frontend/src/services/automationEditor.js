export function newConfiguration(skill) {
  const common = { title: '', enabled: 0, channel: '', business_doctype: '', run_as_user: '' }
  return skill ? { ...common, ai_model: '', handoff_owner: '', mode: 'Shadow', daily_limit: 100, instructions: '', allowed_tools: '[]' }
    : { ...common, source_doctype: '', event: 'on_submit', recipient_field: '', template: '', parameter_mapping: '[]' }
}
export function toolRows(value) {
  return JSON.parse(value || '[]').map(row => ({ ...row, fields: row.fields.join(', ') }))
}
export function configurationValues(draft, skill, tools, parameters) {
  const values = Object.fromEntries(Object.keys(newConfiguration(skill)).map(key => [key, draft[key]]))
  values.enabled = Number(Boolean(values.enabled))
  if (skill) {
    values.daily_limit = Number(values.daily_limit)
    values.allowed_tools = JSON.stringify(tools.map(row => ({ ...row, fields: row.fields.split(',').map(field => field.trim()).filter(Boolean) })))
  } else values.parameter_mapping = JSON.stringify(parameters.split('\n').map(field => field.trim()).filter(Boolean))
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
