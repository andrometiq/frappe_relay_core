const TONES = 7

export function avatarInitials(name) {
  return String(name || '').trim().split(/\s+/).slice(0, 2).map(part => Array.from(part)[0] || '').join('').toUpperCase()
}

// One stable colour per name, so a person keeps the same avatar everywhere.
export function avatarTone(name) {
  let hash = 0
  for (const character of String(name || '').trim().toLowerCase()) hash = (hash * 31 + character.codePointAt(0)) >>> 0
  return `relay-tone-${(hash % TONES) + 1}`
}
