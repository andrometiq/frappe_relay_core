// Copies of one composed message share a send_group: the thread shows one bubble with every copy in `sends`.
// A group with one loaded copy stays a plain row.
export function groupSends(rows) {
  const groups = new Map()
  const result = []
  for (const row of rows) {
    const group = row.send_group && groups.get(row.send_group)
    if (group) group.sends.push(row)
    else if (row.send_group) {
      groups.set(row.send_group, { ...row, sends: [row] })
      result.push(groups.get(row.send_group))
    } else result.push(row)
  }
  return result.map(row => row.sends?.length === 1 ? row.sends[0] : row)
}
