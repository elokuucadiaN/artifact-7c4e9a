"""Adapters translate verified backend evidence into EunoBench metric records."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

from .catalog import validate_record

ROOT = Path(__file__).resolve().parents[1]


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def backend():
    path = ROOT / 'extensions/tenon-prototype/prototype.py'
    spec = importlib.util.spec_from_file_location('eunobench_tenon_backend', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def record(metric, value, unit, configuration, parameters, *, scope, sample, kind, statistic,
           evidence, root, platform, bindings=None, eligible=False):
    row = dict(schema=1, metric_id=metric, value=value, unit=unit, configuration=configuration,
               parameters=parameters, execution_scope=scope, sample_id=sample, sample_kind=kind,
               statistic=statistic, platform=platform, evidence=str(evidence.relative_to(root)),
               evidence_sha256=sha(evidence), bindings=bindings or {}, comparison_eligible=eligible,
               overall_eligible=eligible and metric in ('task.response', 'communication.udp', 'energy.per_job', 'memory.peak_allocated'))
    validate_record(row)
    return row


class CurrentB1Adapter:
    """Reuses the real current replay and its production numerical functions."""
    def collect(self, output):
        base = output / 'evidence/baseline'
        original = ROOT / 'EunoBench_Review_20261106.zip'
        expected = json.loads((ROOT / 'RELEASE.json').read_text())['archive_sha256']
        if sha(original) != expected: raise ValueError('Changed baseline distribution')
        base.mkdir(parents=True)
        archive = base / original.name
        shutil.copyfile(original, archive)
        results = base / 'replayed'
        scratch = Path.home() / 'eunobench/baseline-replays'
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='replay-', dir=scratch) as temp:
            snapshot = Path(temp) / 'snapshot'
            snapshot.mkdir()
            with zipfile.ZipFile(archive) as z:
                for name in z.namelist():
                    if not (snapshot / name).resolve().is_relative_to(snapshot.resolve()):
                        raise ValueError('Unsafe archive member')
                z.extractall(snapshot)
            with (base / 'replay.stdout').open('wb') as out, (base / 'replay.stderr').open('wb') as err:
                subprocess.run([sys.executable, '-S', '-B', str(snapshot / 'tools/replay_current.py'),
                                '--output', str(results)], stdout=out, stderr=err, check=True)
            for name in ('score-replay-input.json', 'coverage-index.json', 'source-identities.json', 'benchmark-coverage.tex'):
                shutil.copyfile(snapshot / 'current' / name, base / name)
        source = base / 'score-replay-input.json'
        data = json.loads(source.read_text())
        rows, configs = [], []
        for item in data['rows']:
            name = item['os']
            configs.append(dict(id=name, scope='physical_board', platform='ESP32 B1; 240 MHz; one core',
                                kind='deployment', original_leaderboard=True))
            bindings = {k: item[k] for k in ('runtime_build', 'observer_build', 'task_energy_block')}
            def add(key, value, unit, params, statistic):
                rows.append(record(key, value, unit, name, params, scope='physical_board',
                    sample='archived-five-reset-aggregate', kind='archived_aggregate', statistic=statistic,
                    evidence=source, root=output, platform='ESP32 B1; 240 MHz; one core', bindings=bindings, eligible=True))
            for phase in ('1', '2'):
                values = item['phase_values'][phase]
                add('task.response', values['median_submission_to_completion_us'], 'us', {'phase': phase}, 'median_of_5_reset_means')
                add('energy.per_job', values['median_joules_per_completed_job'], 'J/job', {'phase': phase}, 'median_of_5_reset_ratios')
            add('communication.udp', item['network_transactions_per_second'], 'transaction/s', {}, 'median_of_5_resets')
            add('memory.peak_allocated', item['peak_allocated_ram_bytes'], 'byte', {}, 'maximum_of_5_cold_boot_peaks')
        shutil.copyfile(results / 'leaderboard.csv', output / 'leaderboard.csv')
        shutil.copyfile(results / 'coverage.csv', output / 'legacy-coverage.csv')
        return rows, configs


class TenonPrototypeAdapter:
    """Collects diagnostic evidence without inheriting B1 board eligibility."""
    legacy = {'task_switch': 'scheduler.legacy_switch', 'multi_switch': 'scheduler.legacy_multi_switch',
              'preempt': 'scheduler.preempt_roundtrip', 'semaphore_shuffle': 'ipc.semaphore_shuffle',
              'interrupt_entry': 'interrupt.trigger_to_isr', 'timer_offset': 'timer.interference_offset'}

    def collect(self, capture, output):
        capture = capture.resolve()
        if not (capture / 'storage.json').is_file():
            raise ValueError('Integration requires the native-filesystem campaign with storage provenance')
        impl = backend()
        impl.native_storage({'tenon_capture': capture})
        impl.replay(capture, output / 'evidence/tenon-replayed')
        saved = output / 'evidence/tenon'
        if capture != saved.resolve(): shutil.copytree(capture, saved)
        plan = json.loads((saved / 'plan.json').read_text())
        rows, configs = [], []
        for mode in plan['modes']:
            name = 'Tenon / ARM64 TCG / ' + mode
            configs.append(dict(id=name, scope='simulation_functional_validation',
                platform='QEMU virt; cortex-a72; TCG; 1 vCPU; 128 MiB', kind='deployment', original_leaderboard=False))
            build = saved / mode / 'build'
            identity = json.loads((build / 'identity.json').read_text())
            bindings = dict(image_sha256=identity['boot_image_sha256'], elf_sha256=identity['image_sha256'],
                            config_sha256=identity['config_sha256'], mode=mode, accelerator='tcg')
            def add(key, value, unit, params, evidence, sample, kind='fresh_guest', statistic='per_guest'):
                rows.append(record(key, value, unit, name, params, scope='simulation_functional_validation',
                    sample=sample, kind=kind, statistic=statistic, evidence=evidence, root=output,
                    platform=configs[-1]['platform'], bindings=bindings))
            sections = json.loads((build / 'sections.json').read_text())
            for section in sections['allocated_sections']:
                add('image.section_bytes', section['bytes'], 'byte', {'section': section['name']},
                    build / 'sections.json', 'linked-image', 'static_build', 'static')
            add('image.allocated_bytes', sections['allocated_section_bytes'], 'byte', {},
                build / 'sections.json', 'linked-image', 'static_build', 'static')
            for i in range(1, plan['runs'] + 1):
                guest = saved / mode / f'guest-{i}'
                verdict = json.loads((guest / 'verdict.json').read_text())
                hz = verdict['meta']['frequency_hz']
                ns = lambda count: count * 1e9 / hz
                sample = f'guest-{i}'
                evidence = guest / 'guest.stdout'
                add('boot.entry_to_main', ns(verdict['boot']['elapsed_counts']), 'ns', {}, evidence, sample)
                for row in verdict['switches']:
                    params = dict(workers=row['workers'], rounds=row['rounds'],
                                  context_profile='ARM-ectx-on' if row['ectx'] else 'ARM-ectx-off')
                    add('scheduler.switch_scale', ns(row['elapsed_counts']) / row['handoffs'], 'ns/handoff', params, evidence, sample)
                for case, value in verdict['legacy'].items():
                    params = {} if case == 'interrupt_entry' else {'iterations': plan['legacy_iterations']}
                    add(self.legacy[case], ns(value), 'ns', params, evidence, sample)
                for row in verdict['timers']:
                    params = {'timers': row['timers'], 'delay_ticks': 20}
                    for key, field in [('timer.arm_cost', 'arm_counts'), ('timer.handler_window', 'irq_handler_counts'), ('timer.max_lateness', 'max_late_counts')]:
                        add(key, ns(row[field]), 'ns', params, evidence, sample)
        source = saved / 'source-lines.json'
        sizes = json.loads(source.read_text())
        name = 'Tenon distributed source (shared descriptor)'
        configs.append(dict(id=name, scope='source_static', platform='distributed multi-platform source', kind='source', original_leaderboard=False))
        for component, values in sizes['groups'].items():
            for language, value in values.items():
                rows.append(record('source.physical_lines', value, 'line', name,
                    dict(component=component, language=language), scope='source_static', sample='source-tree',
                    kind='static_build', statistic='static', evidence=source, root=output,
                    platform='distributed multi-platform source', bindings={'source_manifest_sha256': sha(saved / 'source-manifest.json')}))
        return rows, configs
