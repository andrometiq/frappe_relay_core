// A single ordered model feeds both the desktop popover and phone sheet.
export const attachmentKinds = {
  photo: ['Photo', 'image'], video: ['Video', 'video'], audio: ['Audio', 'music'],
  voice: ['Voice file', 'mic'], document: ['Document', 'file-text'],
  location: ['Location', 'map-pin'], contact: ['Contact', 'user'], sticker: ['Sticker…', 'sticker'],
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
