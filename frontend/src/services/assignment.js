// One line that says who a chat is assigned to and who chose them.
// `title(doctype, name, fallback)` resolves display names; team labels show only while teams are on.
export function assignmentLabel(assignment, { teams, title, user = globalThis.frappe?.session?.user }) {
  const { assigned_to: agent, assigned_by: by, team } = assignment || {}
  if (!agent) return teams && team ? 'Assigned to team ' + title('Relay Team', team, 'Team') : 'Unassigned'
  const target = agent === user ? 'Assigned to you' : 'Assigned to ' + title('User', agent, 'a colleague')
  if (!by || by === agent) return target
  return target + ' by ' + (by === user ? 'you' : title('User', by, 'a colleague'))
}
