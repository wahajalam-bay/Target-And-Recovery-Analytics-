/**
 * Team sizes for the staff option list. The backend sends the list in hierarchy order with a
 * `level` per node, so a node's team is the run of following nodes with a deeper level.
 * Display only: the data filter itself already includes a manager's whole subtree.
 */
export function withTeams(staff) {
  const list = staff || []
  return list.map((s, i) => {
    let team = 0
    let agents = 0
    for (let j = i + 1; j < list.length && list[j].level > s.level; j++) {
      team += 1
      if (list[j].has_target) agents += 1
    }
    return { ...s, team, agents, isManager: team > 0 }
  })
}
