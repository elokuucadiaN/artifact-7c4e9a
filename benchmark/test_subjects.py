import unittest
from .subjects import subjects, preparation, preflight

class OriginalSubjects(unittest.TestCase):
    def test_original_eight_not_reference_tenon(self):
        targets = subjects()
        self.assertEqual(len(targets), 8)
        self.assertFalse(any('Tenon' in t['id'] for t in targets))
        self.assertEqual(sum('Zephyr' in t['id'] for t in targets), 3)

    def test_no_public_snapshot_project_claims(self):
        status = preflight()
        self.assertEqual(status['ready_projects'], 0)
        self.assertFalse(any(r['acquisition_completed'] for r in status['subjects']))

    def test_planned_cells_are_not_test_passes(self):
        plan = preparation()
        self.assertTrue(plan['experiments'])
        self.assertTrue(all(r['status'].startswith('requires_') for r in plan['experiments']))
        self.assertTrue(all(p['project_root'] is None for p in plan['project_template']['projects']))

if __name__ == '__main__': unittest.main()
