import unittest
from read_state import Actor, Conversation, ReadState, authorize


class InboxSemantics(unittest.TestCase):
    def setUp(self):
        self.agent = Actor('site-a', 'agent-a')
        self.chat = Conversation('site-a', 'agent-a', (1, 2, 3, 4, 5), 5)

    def test_open_clears_badge_but_preserves_resume_and_exact_reads(self):
        state = ReadState(viewport_anchor=2, viewed={2})
        opened = state.open(self.agent, self.chat)
        self.assertEqual(opened['previous_anchor'], 2)
        self.assertEqual(state.unread(self.agent, self.chat), 0)
        self.assertEqual(state.viewed, {2})
        self.assertEqual(state.viewport_anchor, 2)

    def test_new_arrival_after_open_stays_unread_until_actually_viewed(self):
        state = ReadState()
        opened = state.open(self.agent, self.chat)
        later = Conversation('site-a', 'agent-a', (1, 2, 3, 4, 5, 6, 7), 7)
        self.assertEqual(state.unread(self.agent, later), 2)
        state.view(self.agent, later, session=opened['session'], version=0,
                   visible={7}, anchor=7, foreground=True)
        self.assertEqual(state.unread(self.agent, later), 1)  # Viewing 7 doesn't invent a read of 6.

    def test_two_users_have_independent_badges(self):
        a, manager_state = ReadState(), ReadState()
        a.open(self.agent, self.chat)
        self.assertEqual(manager_state.unread(Actor('site-a', 'manager', True), self.chat), 5)

    def test_same_team_or_unassigned_does_not_grant_agent_access(self):
        with self.assertRaises(PermissionError):
            authorize(Actor('site-a', 'agent-b'), self.chat)
        with self.assertRaises(PermissionError):
            authorize(self.agent, Conversation('site-a', None, (), 0))

    def test_manager_is_site_scoped(self):
        authorize(Actor('site-a', 'manager', True), self.chat)
        with self.assertRaises(PermissionError):
            authorize(Actor('site-b', 'manager', True), self.chat)

    def test_stale_tab_cannot_replace_new_session_anchor(self):
        state = ReadState()
        old = state.open(self.agent, self.chat)
        state.open(self.agent, self.chat)
        with self.assertRaises(ValueError):
            state.view(self.agent, self.chat, session=old['session'], version=0,
                       visible={1}, anchor=1, foreground=True)

    def test_backward_scroll_is_valid_but_out_of_order_updates_are_not(self):
        state = ReadState()
        opened = state.open(self.agent, self.chat)
        state.view(self.agent, self.chat, session=opened['session'], version=0,
                   visible={5}, anchor=5, foreground=True)
        state.view(self.agent, self.chat, session=opened['session'], version=1,
                   visible={2}, anchor=2, foreground=True)
        self.assertEqual(state.viewport_anchor, 2)
        with self.assertRaises(ValueError):
            state.view(self.agent, self.chat, session=opened['session'], version=1,
                       visible={5}, anchor=5, foreground=True)

    def test_background_future_and_revoked_access_rejected(self):
        state = ReadState()
        opened = state.open(self.agent, self.chat)
        for visible, foreground in [({5}, False), ({6}, True)]:
            with self.assertRaises(ValueError):
                state.view(self.agent, self.chat, session=opened['session'], version=0,
                           visible=visible, anchor=next(iter(visible)), foreground=foreground)
        with self.assertRaises(PermissionError):
            state.unread(self.agent, Conversation('site-a', 'agent-b', (1,), 1))


if __name__ == '__main__':
    unittest.main()
