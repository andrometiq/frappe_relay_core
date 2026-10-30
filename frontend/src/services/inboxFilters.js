// Inbox tab (All, Unread or Not linked) and filters: some channels and one customer type or record. Each user keeps them in this browser.
export const NO_RECORD = 'none'
export const TABS = Object.freeze([
  ['all', 'All', 'All chats you can see'],
  ['unread', 'Unread', 'Chats with messages no one has read yet'],
  ['unlinked', 'Not linked', 'Chats not linked to a customer or supplier'],
])
export const EMPTY_FILTERS = Object.freeze({ tab: 'all', channels: [], businessType: '', businessName: '', businessLabel: '' })

const text = value => typeof value === 'string' ? value.slice(0, 140) : ''

export function storageKey(user) {
  return 'relay-inbox-filters:' + (user || 'Guest')
}

// A missing, blocked or damaged store gives the default filters.
export function loadFilters(storage, user) {
  try {
    const saved = JSON.parse(storage.getItem(storageKey(user)) || '{}') || {}
    const businessType = text(saved.businessType)
    const businessName = businessType && businessType !== NO_RECORD ? text(saved.businessName) : ''
    return {
      tab: TABS.some(([value]) => value === saved.tab) ? saved.tab : 'all',
      channels: Array.isArray(saved.channels) ? saved.channels.filter(name => typeof name === 'string').slice(0, 50) : [],
      businessType, businessName, businessLabel: businessName ? text(saved.businessLabel) || businessName : '',
    }
  } catch {
    return { ...EMPTY_FILTERS, channels: [] }
  }
}

export function saveFilters(storage, user, filters) {
  try { storage.setItem(storageKey(user), JSON.stringify(filters)) } catch { /* Private windows can block storage; filters still apply. */ }
}

// The site channels of one medium from api.capabilities inbox_channels; 'all' gives every channel.
export function channelOptions(capabilities, medium) {
  return (capabilities?.inbox_channels || []).filter(row => medium === 'all' || row.medium === medium)
}

// Request parameters for inbox.directory and queue_counts.read. A saved channel that the medium does not offer is
// left out, and no chosen channel means every channel of the medium.
export function filterParams(filters, options) {
  const offered = new Set(options.map(row => row.name))
  const channels = filters.channels.filter(name => offered.has(name))
  return {
    ...(channels.length ? { channels: JSON.stringify(channels) } : {}),
    ...(filters.businessType ? { business_type: filters.businessType } : {}),
    ...(filters.businessType && filters.businessType !== NO_RECORD && filters.businessName ? { business_name: filters.businessName } : {}),
  }
}

// Chips that name each active filter, for the line under the tabs and the filter button count.
export function filterChips(filters, options) {
  const names = options.filter(row => filters.channels.includes(row.name)).map(row => row.label)
  const business = filters.businessType === NO_RECORD ? 'No business record'
    : filters.businessName ? `${filters.businessType}: ${filters.businessLabel || filters.businessName}`
      : filters.businessType ? `Any ${filters.businessType}` : ''
  return [
    ...(names.length ? [{ key: 'channels', label: names.join(', ') }] : []),
    ...(business ? [{ key: 'business', label: business }] : []),
  ]
}

// Remove one chip's filter.
export function withoutFilter(filters, key) {
  return key === 'channels' ? { ...filters, channels: [] } : { ...filters, businessType: '', businessName: '', businessLabel: '' }
}

// Remove every filter and keep the tab.
export function withoutFilters(filters) {
  return { ...EMPTY_FILTERS, tab: filters.tab, channels: [] }
}
