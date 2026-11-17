"""Adversarial protocol controls; generated fixture is synthetic, never measurement data."""
import unittest
from pathlib import Path
import tempfile
import prototype as p


def synthetic():
    lines = ['EUNO_META schema=1 mode=fixed counter=cntvct frequency_hz=62500000 tick_hz=1000 rounds=20 legacy_iterations=10',
             'EUNO_BOOT boundary=ukplat_entry_to_main elapsed_counts=1000 read_min_counts=1']
    for case, label in zip(p.CASES, p.LABELS):
        lines += [f'EUNO_CASE_BEGIN name={case}', f'R-Rhealstone: {label}, in generic timer counts - 100 count',
                  f'EUNO_CASE_END name={case} status=0']
    for e in [0, 1]:
        for n in p.WORKERS:
            lines.append(f'EUNO_SWITCH workers={n} ectx={e} rounds=20 entries={n*20} handoffs={n*20-1} errors=0 elapsed_counts=10000')
    for n in p.TIMERS:
        lines.append(f'EUNO_TIMER timers={n} callbacks={n} errors=0 arm_counts=20 irq_count=1 irq_handler_counts=30 max_late_counts=0')
    return '\n'.join(lines + ['EUNO_DONE failures=0', ''])


class ProtocolControls(unittest.TestCase):
    def test_windows_capture_path_rejected(self):
        with self.assertRaisesRegex(ValueError, 'must be under'):
            p.native_storage({'active_capture': Path('/mnt/e/learn/benchmark/output/forbidden')})

    def test_symlink_to_windows_rejected(self):
        base = Path.home() / 'eunobench'
        with tempfile.TemporaryDirectory(prefix='storage-test-', dir=base) as temp:
            link = Path(temp) / 'windows'
            link.symlink_to('/mnt/e', target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'must be under'):
                p.native_storage({'active_capture': link / 'capture'})

    def assert_rejected(self, text):
        with self.assertRaises(ValueError): p.validate(text, 'fixed', 20, 10)

    def test_complete_synthetic_envelope(self):
        self.assertTrue(p.validate(synthetic(), 'fixed', 20, 10)['pass'])

    def test_missing_completion(self):
        self.assert_rejected(synthetic().replace('EUNO_DONE failures=0', ''))

    def test_skipped_or_failed_original_case(self):
        self.assert_rejected(synthetic().replace('EUNO_CASE_END name=preempt status=0', 'EUNO_CASE_END name=preempt status=1'))

    def test_missing_actual_handoff(self):
        self.assert_rejected(synthetic().replace('handoffs=39', 'handoffs=0'))

    def test_lost_timer_callback(self):
        self.assert_rejected(synthetic().replace('timers=100 callbacks=100', 'timers=100 callbacks=99'))

    def test_no_actual_timer_irq(self):
        self.assert_rejected(synthetic().replace('irq_count=1', 'irq_count=0'))

    def test_wrong_tick_mode(self):
        self.assert_rejected(synthetic().replace('mode=fixed', 'mode=tickless'))

    def test_counter_cannot_be_relabelled_as_cpu_cycles(self):
        self.assert_rejected(synthetic().replace('counter=cntvct', 'counter=pmccntr'))

    def test_duplicate_grid_case(self):
        line = next(x for x in synthetic().splitlines() if x.startswith('EUNO_SWITCH'))
        self.assert_rejected(synthetic().replace('EUNO_DONE', line + '\nEUNO_DONE'))

    def test_zero_clock_frequency(self):
        self.assert_rejected(synthetic().replace('frequency_hz=62500000', 'frequency_hz=0'))

    def test_tampered_run_end(self):
        self.assert_rejected(synthetic().replace('EUNO_DONE failures=0', 'EUNO_DONE failures=1'))

    def test_measurement_outside_case(self):
        s = synthetic()
        line = next(x for x in s.splitlines() if 'average_task_preempt_time' in x)
        s = s.replace(line + '\n', '').replace('EUNO_DONE', line + '\nEUNO_DONE')
        self.assert_rejected(s)


if __name__ == '__main__': unittest.main()
