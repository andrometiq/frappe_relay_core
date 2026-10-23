// Provider codes from Meta's WhatsApp Node.js SDK LanguagesEnum:
// https://github.com/WhatsApp/WhatsApp-Nodejs-SDK/blob/main/src/types/enums.ts
// This is a picker catalog, not a server-side allowlist. Preserve existing codes.
const codes = 'af sq ar az bn bg ca zh_CN zh_HK zh_TW hr cs da nl en en_GB en_US et fil fi fr ka de el gu ha he hi hu id ga it ja kn kk rw_RW ko ky_KG lo lv lt mk ms ml mr nb fa pl pt_BR pt_PT pa ro ru sr sk sl es es_AR es_ES es_MX sw sv ta te th tr uk ur uz vi zu'.split(' ')
const english = new Intl.DisplayNames(['en'], { type: 'language' })
export function languageLabel(code) {
  const locale = code.replaceAll('_', '-')
  try {
    const name = english.of(locale)
    const native = new Intl.DisplayNames([locale], { type: 'language' }).of(locale)
    return `${name}${native && native !== name ? ' · ' + native : ''} (${code})`
  } catch { return code }
}
export function templateLanguages(current = '') {
  return [...new Set([...codes, ...(current ? [current] : [])])]
    .map(value => ({ value, label: languageLabel(value) }))
    .sort((a, b) => a.label.localeCompare(b.label, 'en'))
}
