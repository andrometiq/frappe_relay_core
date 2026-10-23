"""Permission-checked skill configuration and non-sending previews."""
import frappe
from relay_core.permissions import require_access
from relay_core.ai.tools import contracts, as_user

FIELDS = ('title', 'enabled', 'channel', 'business_doctype', 'ai_model', 'run_as_user',
          'handoff_owner', 'mode', 'daily_limit', 'instructions', 'allowed_tools')


def validate_skill(doc):
    require_access(configure=True)
    if not doc.instructions or len(doc.instructions) > 8000 or not 1 <= int(doc.daily_limit or 0) <= 1000:
        raise ValueError('Use 1–8000 instruction characters and a daily limit of 1–1000')
    if doc.mode not in ('Shadow', 'Automatic'):
        raise ValueError('Choose Shadow or Automatic mode')
    with as_user(doc.run_as_user):
        require_access(manage=True)
    with as_user(doc.handoff_owner):
        require_access()
    contracts(doc)
    if doc.enabled:
        # Serialize activation so two skills cannot own the same channel/business.
        frappe.db.get_value('Relay Channel', doc.channel, 'name', for_update=True)
        names = frappe.get_all('Relay AI Skill', filters={'channel': doc.channel,
            'business_doctype': doc.business_doctype, 'enabled': 1}, pluck='name')
        if any(name != doc.name for name in names):
            raise ValueError('Disable the existing skill for this channel and business type first')
        model = frappe.get_doc('AI Model', doc.ai_model)
        if not model.enabled or not frappe.get_doc('AI Provider Account', model.account).enabled:
            raise ValueError('Choose an enabled AI Model and provider account')


@frappe.whitelist(methods=['GET'])
def directory(after=None):
    require_access(configure=True)
    rows = frappe.get_list('Relay AI Skill', filters={'name': ['>', after]} if after else {},
        fields=['name', *FIELDS], order_by='name asc', page_length=31)
    return {'items': rows[:30], 'next': rows[29].name if len(rows) > 30 else None}


@frappe.whitelist(methods=['POST'])
def save(values, name=None):
    require_access(configure=True)
    if isinstance(values, str): values = frappe.parse_json(values)
    if not isinstance(values, dict) or set(values) - set(FIELDS):
        raise ValueError('Invalid skill fields')
    doc = frappe.get_doc('Relay AI Skill', name) if name else frappe.new_doc('Relay AI Skill')
    doc.update(values); doc.save()
    return {'name': doc.name}


@frappe.whitelist(methods=['POST'])
def test_skill(name, message):
    require_access(configure=True)
    skill = frappe.get_doc('Relay AI Skill', name); skill.check_permission('read')
    source = frappe.get_doc('Relay Message', message); source.check_permission('read')
    from relay_core.ai.service import decide
    from relay_core.automation.service import reserve_attempt
    reserve_attempt(skill)
    # Preview is structurally read-only: no run, ticket, pause or send is created.
    with as_user(skill.run_as_user):
        source.check_permission('read')
        try:
            return dict(decide(skill, source), mode='Shadow')
        except Exception:
            return {'mode': 'Shadow', 'reply': '', 'handoff': True, 'reason': 'Decision or authorization failed'}
