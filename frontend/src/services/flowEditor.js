// Flow steps as the server stores them (relay_core/flows/contracts.py) and the plain fields the step editor shows.
export const STEP_KINDS = [
  { value: 'input', label: 'Ask a question' },
  { value: 'reply', label: 'Send a message' },
  { value: 'condition', label: 'Branch on an answer' },
  { value: 'action', label: 'Run a business action' },
  { value: 'wait', label: 'Wait' },
  { value: 'ticket', label: 'Raise a ticket' },
  { value: 'topic', label: 'Save a topic' },
  { value: 'handoff', label: 'Hand over to a person' },
  { value: 'end', label: 'End the flow' },
]
export const INPUT_TYPES = [
  { value: 'text', label: 'Text' }, { value: 'choice', label: 'One choice (buttons or list)' },
  { value: 'multi_choice', label: 'Several choices' }, { value: 'number', label: 'Number' },
  { value: 'email', label: 'Email' }, { value: 'date', label: 'Date' },
  { value: 'content', label: 'Any message (text, media, location, contact)' },
]
export const CONTENT_TYPES = ['text', 'image', 'video', 'audio', 'voice', 'document', 'sticker', 'location', 'contacts']
export const OPERATORS = [
  { value: 'eq', label: 'is' }, { value: 'ne', label: 'is not' }, { value: 'contains', label: 'contains' },
  { value: 'gt', label: 'is more than' }, { value: 'gte', label: 'is at least' }, { value: 'lt', label: 'is less than' },
  { value: 'lte', label: 'is at most' }, { value: 'is_set', label: 'has a value' },
]
const TERMINAL = ['end', 'handoff']

export function newFlow() {
  return { title: '', command: '', keywords: '', template_button: '', channel: '', execution_user: '', business_doctype: '', enabled: 0, nodes: [newStep('input', [])] }
}

export function stepLabel(kind) {
  return STEP_KINDS.find(row => row.value === kind)?.label || kind
}

export function newStep(kind, steps) {
  const ids = new Set(steps.map(step => step.id))
  let number = steps.length + 1
  while (ids.has(kind + '_' + number)) number++
  const step = { id: kind + '_' + number, kind, text: '' }
  if (kind === 'input') Object.assign(step, { variable: 'answer_' + number, input_type: 'text' })
  if (kind === 'condition') Object.assign(step, { variable: '', operator: 'eq', value: '', then: '', otherwise: '' })
  if (kind === 'action') Object.assign(step, { action: '', arguments: {} })
  if (kind === 'wait') step.seconds = 60
  if (kind === 'topic') Object.assign(step, { title: '', status: 'Open' })
  return step
}

// Choices are edited one per line as "Label" or "Label = value"; the value is what branches compare.
export function choicesText(choices = []) {
  return choices.map(choice => typeof choice === 'string' ? choice : choice.label === choice.value ? choice.label : choice.label + ' = ' + choice.value).join('\n')
}

export function parseChoices(text) {
  return String(text || '').split('\n').map(line => line.trim()).filter(Boolean).map(line => {
    const [label, ...rest] = line.split('=')
    const value = rest.join('=').trim()
    return { label: label.trim(), value: value || label.trim() }
  })
}

export function moveStep(steps, index, delta) {
  const target = index + delta
  if (target < 0 || target >= steps.length) return
  ;[steps[index], steps[target]] = [steps[target], steps[index]]
}

// Removing a step also clears links that pointed at it, so the server reports a missing branch instead of a stale one.
export function removeStep(steps, index) {
  const [removed] = steps.splice(index, 1)
  for (const step of steps) for (const key of ['next', 'then', 'otherwise']) if (step[key] === removed.id) step[key] = ''
}

export function renameStep(steps, step, id) {
  const previous = step.id
  step.id = id
  for (const other of steps) for (const key of ['next', 'then', 'otherwise']) if (other[key] === previous) other[key] = id
}

const OPTIONAL = ['next', 'max_visits', 'min_length', 'max_length', 'minimum', 'maximum', 'error_text', 'button', 'category', 'variable']

// One step as the server accepts it: empty optional fields left out, numbers as numbers.
export function cleanStep(step) {
  const { _arguments, ...result } = step
  for (const key of OPTIONAL) if (result[key] === '' || result[key] === null || result[key] === undefined) delete result[key]
  for (const key of ['max_visits', 'min_length', 'max_length', 'minimum', 'maximum', 'seconds']) if (key in result) result[key] = Number(result[key])
  if (TERMINAL.includes(result.kind) || result.kind === 'condition') delete result.next
  if (result.kind !== 'input') for (const key of ['input_type', 'choices', 'optional', 'integer_only', 'accept', 'min_length', 'max_length', 'error_text', 'button']) delete result[key]
  if (result.kind === 'input' && !['choice', 'multi_choice'].includes(result.input_type)) delete result.choices
  if (result.kind === 'input' && result.input_type !== 'content') delete result.accept
  if (result.kind === 'input' && result.input_type !== 'text') { delete result.min_length; delete result.max_length }
  if (result.kind === 'input' && result.input_type !== 'number') { delete result.minimum; delete result.maximum; delete result.integer_only }
  if (result.kind === 'input' && !result.optional) delete result.optional
  return result
}

export function flowValues(draft) {
  return {
    title: draft.title, command: draft.command || '', keywords: draft.keywords || '', template_button: draft.template_button || '',
    channel: draft.channel, execution_user: draft.execution_user, business_doctype: draft.business_doctype,
    nodes: draft.nodes.map(cleanStep),
  }
}

export function triggerSummary(row) {
  const words = String(row.keywords || '').split('\n').map(word => word.trim()).filter(Boolean)
  const parts = [row.command, ...words.map(word => '“' + word + '”'), row.template_button ? 'Template button' : ''].filter(Boolean)
  return parts.join(' · ') || 'No trigger'
}

const canonical = value => JSON.stringify(value, (_key, item) => item && typeof item === 'object' && !Array.isArray(item)
  ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item)

// The editor holds steps as objects with editor-only fields; the server sends JSON text.
export function hasUnpublished(flow) {
  if (!flow.published_nodes) return true
  const nodes = typeof flow.nodes === 'string' ? JSON.parse(flow.nodes) : flow.nodes.map(cleanStep)
  return canonical(nodes) !== canonical(JSON.parse(flow.published_nodes))
}

// What the next step after this one is, in words, for the step card.
export function nextLabel(steps, index) {
  const step = steps[index]
  if (TERMINAL.includes(step.kind)) return 'Flow ends'
  if (step.kind === 'condition') return 'Branches'
  if (step.next) return 'Then ' + step.next
  return index + 1 < steps.length ? 'Then ' + steps[index + 1].id : 'Flow ends'
}
