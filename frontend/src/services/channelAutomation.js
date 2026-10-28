export const STEP_TYPES = ['Flow', 'AI skill', 'Assign', 'Ticket', 'Out of hours reply']
export const WORKING_DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
export const TICKET_RULES = ['Create if not resolved', 'Always', 'Never']

export function newChannelStep(step) {
  return { step, enabled: 1, ai_skill: '', team: '', user: '', ticket_rule: 'Create if not resolved', message: '', on_reply: ['Assign', 'Ticket'].includes(step) ? 'Continue' : 'Stop' }
}

export function channelValues(draft) {
  return {
    automation_enabled: Number(Boolean(draft.automation_enabled)),
    timezone: draft.timezone || '', open_time: draft.open_time || null, close_time: draft.close_time || null,
    working_days: draft.working_days || '',
    steps: draft.steps.map(row => ({ ...newChannelStep(row.step), ...row, enabled: Number(Boolean(row.enabled)) })),
  }
}
