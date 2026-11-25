"""Sites with Teams already on keep each Relay user's business types after the update."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from frappe import _dict
from relay_core.patches.v1_0 import keep_business_access_with_teams_on as keep


class KeepBusinessAccessTests(unittest.TestCase):
    def setUp(self):
        self.roles = {'Relay Communication User': ['ann', 'ben', 'cy', 'off', 'boss', 'covered', 'none'],
                      'Relay Communication Manager': ['boss'], 'System Manager': []}
        self.assigned = [('ann', 'Customer'), ('ann', 'Supplier'), ('ben', 'Supplier'), ('ben', 'Customer'),
                         ('cy', 'Customer'), ('cy', 'Retired'), ('off', 'Customer'), ('boss', 'Customer'),
                         ('covered', 'Customer')]
        self.inserted = []
        self.fake = SimpleNamespace(get_all=self.get_all, get_doc=self.get_doc)
        self.enterContext(patch.object(keep, 'frappe', self.fake))
        self.teams_on = self.enterContext(patch('relay_core.features.is_enabled', return_value=True))
        self.enterContext(patch.object(keep, 'coverage', side_effect=lambda user: {'Customer': {'Group'}} if user == 'covered' else {}))

    def get_all(self, doctype, filters=None, pluck=None, fields=None):
        if doctype == 'Has Role':
            return [user for role in filters['role'][1] for user in self.roles[role]]
        if doctype == 'User':
            return [user for user in filters['name'][1] if user != 'off']
        if doctype == 'Relay Contact Type':
            return ['Customer', 'Supplier']
        return [_dict(user=user, parent=parent) for user, parent in self.assigned]

    def get_doc(self, values):
        self.inserted.append(values)
        return Mock()

    def test_each_set_of_assigned_types_gets_one_all_records_team(self):
        keep.execute()
        teams = {team['title']: ([row['user'] for row in team['members']], team['business_access']) for team in self.inserted}
        self.assertEqual(teams, {
            'Customer and Supplier access': (['ann', 'ben'], [{'business_doctype': 'Customer', 'access': 'All records'},
                                                               {'business_doctype': 'Supplier', 'access': 'All records'}]),
            'Customer access': (['cy'], [{'business_doctype': 'Customer', 'access': 'All records'}])},
            'Disabled users, managers, users without types and users a team already covers get nothing')

    def test_teams_off_or_a_second_run_change_nothing(self):
        self.teams_on.return_value = False
        keep.execute()
        self.assertEqual(self.inserted, [])
        self.teams_on.return_value = True
        with patch.object(keep, 'coverage', return_value={'Customer': {'All records'}}):
            keep.execute()
        self.assertEqual(self.inserted, [], 'Seeded users are covered, so the patch is idempotent')

    def test_large_groups_split_into_teams_of_one_hundred(self):
        users = [f'user{index:03}' for index in range(150)]
        self.roles['Relay Communication User'] = users
        self.assigned = [(user, 'Customer') for user in users]
        keep.execute()
        self.assertEqual([(team['title'], len(team['members'])) for team in self.inserted],
                         [('Customer access', 100), ('Customer access 2', 50)])


if __name__ == '__main__':
    unittest.main()
