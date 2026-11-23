// The Access page: Relay roles from Frappe, and what each one lets a person do in Relay.

// The main Relay role. Team User is a separate Frappe role a person can hold next to it.
export const ROLE_OPTIONS = [
  { value: '', label: 'No access' },
  { value: 'User', label: 'User' },
  { value: 'Manager', label: 'Manager' },
]

// What each role does today, as enforced by the server. Team User only widens the team filter.
export const ROLE_MATRIX = [
  { action: 'See chats', User: 'Assigned business types and unlinked chats', 'Team User': 'Adds nothing on its own', Manager: 'Every enabled business type' },
  { action: 'Reply, notes and tickets', User: true, 'Team User': false, Manager: true },
  { action: 'Filter chats by team', User: 'Own teams', 'Team User': 'Every team', Manager: 'Every team' },
  { action: 'Assign chats', User: false, 'Team User': false, Manager: true },
  { action: 'Create and edit templates', User: false, 'Team User': false, Manager: true },
  { action: 'Bulk campaigns, business events and billing', User: false, 'Team User': false, Manager: true },
  { action: 'Ticket settings, saved replies and access', User: false, 'Team User': false, Manager: true },
]

export const ROLE_COLUMNS = ['User', 'Team User', 'Manager']

// Badges for the role cell: the main role, then Team User when the person also has it.
export function roleBadges(row) {
  const main = row.role ? [{ label: row.role, theme: row.role === 'User' ? 'gray' : row.role === 'Manager' ? 'orange' : 'blue' }] : [{ label: 'No access', theme: 'gray' }]
  return row.team_user ? [...main, { label: 'Team User', theme: 'blue' }] : main
}

// Managers and System Managers see every business type whatever is assigned to them.
export function seesAllTypes(row) {
  return row.role === 'Manager' || row.role === 'System Manager'
}

export function filterAccessRows(rows, { query = '', role = '', team = '', businessType = '' } = {}) {
  const needle = query.trim().toLocaleLowerCase()
  return rows.filter(row => (!needle || [row.full_name, row.user].some(value => String(value || '').toLocaleLowerCase().includes(needle)))
    && (!role || (role === 'Team User' ? row.team_user : row.role === role))
    && (!team || row.teams.includes(team))
    && (!businessType || seesAllTypes(row) || row.business_types.includes(businessType)))
}

// Only the parts a manager changed go to the server, so a locked role is never sent unchanged.
export function accessChanges(saved, draft) {
  const changes = {}
  if (draft.role !== saved.role) changes.role = draft.role
  if (draft.team_user !== saved.team_user) changes.team_user = draft.team_user ? 1 : 0
  for (const key of ['teams', 'business_types']) {
    if ([...draft[key]].sort().join('\n') !== [...saved[key]].sort().join('\n')) changes[key] = [...draft[key]]
  }
  return changes
}

// Comma list of labels for names, falling back to the name itself.
export function labelList(names, options) {
  return names.map(name => options.find(option => option.value === name)?.label || name).join(', ')
}
