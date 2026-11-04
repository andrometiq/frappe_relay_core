// A single ordered model feeds both the desktop popover and phone sheet.
export const attachmentKinds = {
  photo: ['Photo', 'image'], video: ['Video', 'video'], audio: ['Audio', 'music'],
  voice: ['Voice file', 'mic'], document: ['Document', 'file-text'],
  location: ['Location', 'map-pin'], contact: ['Contact', 'user'], poll: ['Poll', 'vote'], sticker: ['Sticker…', 'sticker'],
}
export const composerEmoji = [['😀', 'Grinning face'], ['😊', 'Smiling face'], ['👍', 'Thumbs up'],
  ['❤️', 'Red heart'], ['🙏', 'Folded hands'], ['🎉', 'Party popper']]
export function composerActions({ can = () => false, kinds = [], closed = false, off = false, busy = false, email = false } = {}) {
  const actions = []
  const add = (id, label, icon, group, disabled = busy) => actions.push({ id, label, icon, group, disabled })
  if (!off) {
    if (!closed && can('saved_replies')) add('saved', 'Saved replies', 'zap', 'quick')
    if (can('templates')) add('template', 'Templates', 'file-text', 'quick')
    if (email) add('files', 'Attach files', 'paperclip', 'quick')
    if (!closed) {
      for (const [kind, [label, icon]] of Object.entries(attachmentKinds)) {
        if (kinds.includes(kind)) add(kind, label, icon, 'attachments')
      }
      if (!email) add('emoji', 'Emoji', 'smile', 'secondary')
    }
  }
  add('note', 'Internal note', 'lock', 'secondary')
  add('details', 'Sending details', 'info', 'details', false)
  return actions
}

// WhatsApp sends a poll as reply buttons (2-3 options, 20 characters) or a list (4-10 options, 24 characters).
export function pollProblem(question, options) {
  const filled = options.map(option => option.trim()).filter(Boolean)
  const limit = filled.length <= 3 ? 20 : 24
  if (!question.trim()) return 'Add a question'
  if (filled.length < 2 || filled.length > 10) return 'Add 2 to 10 options'
  if (filled.some(option => [...option].length > limit)) return `Keep each option to ${limit} characters with ${filled.length} options`
  if (new Set(filled.map(option => option.toLowerCase())).size !== filled.length) return 'Each option must be different'
  return ''
}
