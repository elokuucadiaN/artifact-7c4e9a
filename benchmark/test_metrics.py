"""EunoBench metric-admission controls; fixtures are synthetic, not observations."""
import copy
import unittest
from .catalog import validate_record
from .pipeline import summarize


def fixture():
    return dict(schema=1, metric_id='scheduler.switch_scale', value=100.0, unit='ns/handoff',
        configuration='synthetic', parameters=dict(workers=2, context_profile='native-default', rounds=100),
        execution_scope='simulation_functional_validation', sample_id='guest-1', sample_kind='fresh_guest',
        statistic='per_guest', evidence='synthetic-only', evidence_sha256='synthetic-only',
        platform='synthetic-only', bindings={'image_sha256': 'synthetic-only'},
        comparison_eligible=False, overall_eligible=False)


class MetricControls(unittest.TestCase):
    def test_no_simulation_promotion(self):
        row = fixture(); row['comparison_eligible'] = True
        with self.assertRaisesRegex(ValueError, 'Simulation/static'): validate_record(row)

    def test_no_new_metric_in_original_overall(self):
        row = fixture(); row['overall_eligible'] = True
        with self.assertRaisesRegex(ValueError, 'Overall'): validate_record(row)

    def test_no_unit_relabelling(self):
        row = fixture(); row['unit'] = 'cycle'
        with self.assertRaisesRegex(ValueError, 'unit/parameter'): validate_record(row)

    def test_parameter_required(self):
        row = fixture(); row['parameters'].pop('context_profile')
        with self.assertRaises(ValueError): validate_record(row)

    def test_no_duplicate_samples(self):
        row = fixture()
        with self.assertRaisesRegex(ValueError, 'Repeated sample'): summarize([row, copy.deepcopy(row)])

    def test_no_pooling_changed_images(self):
        first, second = fixture(), fixture()
        second['sample_id'] = 'guest-2'; second['bindings']['image_sha256'] = 'different'
        with self.assertRaisesRegex(ValueError, 'changed configurations/images'): summarize([first, second])

    def test_static_descriptor_not_guest(self):
        row = fixture()
        row.update(metric_id='image.allocated_bytes', unit='byte', parameters={},
                   sample_kind='static_build', statistic='static')
        self.assertEqual(summarize([row])[0]['independent_guests'], 0)

    def test_unbound_evidence_rejected(self):
        row = fixture(); row['evidence_sha256'] = ''
        with self.assertRaisesRegex(ValueError, 'Unbound'): validate_record(row)

    def test_nan_rejected(self):
        row = fixture(); row['value'] = float('nan')
        with self.assertRaises(ValueError): validate_record(row)


if __name__ == '__main__': unittest.main()
