"""Current skill, scoped-read, handoff and journal acceptance on the approved site.

The retired provider-policy/outbox runner is covered by compatibility unit tests.
Live automation uses adapter.complete and Relay Message Action, exercised here.
"""
from integration_ai_permissions_site import main

if __name__ == '__main__':
    main()
