import frappe

# Relay AI Provider types that frappe_tools can call with an API key.
SUPPORTED = ('OpenRouter', 'Anthropic')


def execute():
    """Give policies without an AI Model one built from their legacy provider."""
    if not frappe.db.has_column('Relay Automation Policy', 'provider'):
        return
    policies = frappe.get_all('Relay Automation Policy', filters={'ai_model': ['is', 'not set']},
        fields=['name', 'provider', 'fallback_provider'])
    for policy in policies:
        model = next(filter(None, map(ai_model_for, (policy.provider, policy.fallback_provider))), None)
        if model:
            frappe.db.set_value('Relay Automation Policy', policy.name, 'ai_model', model, update_modified=False)
        elif policy.provider or policy.fallback_provider:
            print(f'Relay Automation Policy {policy.name}: legacy provider is not supported by AI Model; choose an AI Model')


def ai_model_for(name: str | None) -> str | None:
    if not name or not frappe.db.exists('Relay AI Provider', name):
        return None
    legacy = frappe.get_doc('Relay AI Provider', name)
    if legacy.provider not in SUPPORTED:
        return None
    label = f'Relay {legacy.name}'
    if not frappe.db.exists('AI Provider Account', label):
        frappe.get_doc(doctype='AI Provider Account', account_name=label, provider=legacy.provider, auth_type='API Key',
            enabled=legacy.enabled, api_key=legacy.get_password('api_key', raise_exception=False)).insert(ignore_permissions=True)
    if not frappe.db.exists('AI Model', label):
        frappe.get_doc(doctype='AI Model', model_label=label, account=label, model_id=legacy.model,
            enabled=legacy.enabled).insert(ignore_permissions=True)
    return label
