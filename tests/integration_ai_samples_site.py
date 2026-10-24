"""Exercise the installed sample upgrade transaction; retain no test changes."""
import json
import os
import sys
from unittest.mock import patch

from integration_ai_permissions_site import confine_writes


def main():
    sys.addaudithook(confine_writes)
    os.environ['FRAPPE_STREAM_LOGGING'] = '1'
    import frappe
    from channel_site_fixtures import init
    from relay_core.ai.samples import INSTRUCTIONS, LEDGER_TOOL, LEGACY_LEDGER_TOOL, install_samples

    init()
    try:
        skill = frappe.get_doc('Relay AI Skill', {'sample_key': 'supplier_ledger'})
        assert not skill.enabled and skill.instructions == INSTRUCTIONS
        assert json.loads(skill.allowed_tools) in ([LEDGER_TOOL], [LEGACY_LEDGER_TOOL])
        with patch.object(frappe.db, 'commit', side_effect=AssertionError('Test must roll back')):
            # Recreate the exact shipped predecessor, with configured operator settings.
            skill.allowed_tools = json.dumps([LEGACY_LEDGER_TOOL])
            skill.mode, skill.daily_limit = 'Automatic', 7
            skill.save()
            install_samples()
            skill.reload()
            assert json.loads(skill.allowed_tools) == [LEDGER_TOOL]
            assert skill.mode == 'Automatic' and skill.daily_limit == 7 and not skill.enabled
            modified = skill.modified
            install_samples()
            skill.reload()
            assert skill.modified == modified, 'Current sample must not be saved again'
            # Both a custom tool and custom instructions must survive installation.
            custom = {**LEGACY_LEDGER_TOOL, 'fields': ['posting_date', 'debit', 'credit', 'remarks']}
            for tools, instructions in [([custom], INSTRUCTIONS),
                    ([LEGACY_LEDGER_TOOL], 'Local sample test: ask the accounts team.')]:
                skill.allowed_tools, skill.instructions = json.dumps(tools), instructions
                skill.save()
                skill.reload()
                modified = skill.modified
                install_samples()
                skill.reload()
                assert json.loads(skill.allowed_tools) == tools and skill.instructions == instructions
                assert skill.modified == modified, 'Customized sample must remain untouched'
        print('PASS installed legacy upgrade, configuration preservation, idempotency and customization guards')
    finally:
        frappe.db.rollback()
        frappe.destroy()


if __name__ == '__main__':
    main()
