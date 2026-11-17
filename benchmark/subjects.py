"""The original EunoBench deployments, not the paper used as a metric reference."""
import json
from pathlib import Path

from .adapters import ROOT
from .catalog import METRICS

VERSIONS = {
    'FreeRTOS': 'ESP-IDF 5.2.5 with its native FreeRTOS',
    'Zephyr': 'Zephyr 3.7.0 baseline',
    'NuttX': 'NuttX 12.2.1',
    'RIOT': 'RIOT dd06b3727c41c2c44bf93f47ff7831fdd501d68b',
    'AliOS Things': 'AliOS Things bacc144bdc5df8fe8e302e3732675a920aa40bc5; Rhino kernel',
    'Zephyr C2-1 (Qwen)': 'Zephyr 3.7.0, original saved direct-prompted configuration',
    'Zephyr (AutoOS-adapted)': 'Zephyr 3.7.0, original saved AutoOS-adapted configuration',
    'Contiki-NG + ESP-IDF/FreeRTOS': 'Contiki-NG c02eedae hosted on ESP-IDF 5.2.5/FreeRTOS'
}
NEEDED = ('project_root', 'resolved_config', 'board_manifest', 'native_adapter', 'build_recipe')


def subjects():
    source = ROOT / 'artifact/current/score-replay-input.json'
    result = []
    for row in json.loads(source.read_text())['rows']:
        result.append(dict(id=row['os'], version=VERSIONS[row['os']], scope='physical_board',
            platform='ESP32 B1; 240 MHz; one core', kind='deployment', original_leaderboard=True,
            runtime_build=row['runtime_build'], observer_build=row['observer_build'],
            attribution=('Contiki dispatch + FreeRTOS host; native Contiki kernel tests require separate applicability review'
                         if row['os'].startswith('Contiki') else 'target OS native services')))
    return result


def preparation():
    profiles, experiments = [], []
    for target in subjects():
        profiles.append(dict(configuration=target['id'], version=target['version'],
            runtime_build=target['runtime_build'], observer_build=target['observer_build'],
            **{name: None for name in NEEDED}))
        for metric in METRICS:
            if metric['origin'] == 'existing': continue
            family = metric['id'].split('.')[0]
            item = dict(configuration=target['id'], metric_id=metric['id'],
                status='requires_original_project', independent_resets=5,
                platform='same original B1 board and deployment',
                clock='review actual target counter and frequency; no assumed 24 MHz',
                parameter_grid={})
            if metric['id'] == 'scheduler.switch_scale':
                item['parameter_grid'] = dict(workers=[2, 10, 20, 50, 100],
                    context_profile=['original-native-context'], rounds=[500])
                item['context_note'] = 'ARM ectx is architecture-specific; do not invent an equivalent switch for Xtensa'
            if metric['id'].startswith('timer.') and metric['id'] != 'timer.interference_offset':
                item['parameter_grid'] = dict(timers=[1, 10, 20, 50, 100], delay_ticks=[20])
                item['mode_note'] = 'Start with original mode; add fixed/tickless only where natively supported and verified'
                item['dispatch_note'] = 'Record IRQ vs timer-service-thread dispatch; handler-only cost is conditional on equivalent boundaries'
            if target['id'].startswith('Contiki') and family in ('scheduler', 'ipc', 'interrupt', 'timer'):
                item['status'] = 'requires_component_attribution'
                item['attribution_note'] = 'Native cooperative Contiki and FreeRTOS host mechanisms must remain distinct; no host-thread substitution as Contiki kernel coverage'
            if family in ('image', 'source'):
                item['independent_resets'] = 0
                item['statistic'] = 'static descriptor; no additional independent runtime samples'
            experiments.append(item)
    return dict(schema=1, subjects=subjects(), project_template={'schema': 1, 'projects': profiles},
        experiments=experiments, source_scope='public review snapshot: no claim that missing projects were reconstructed',
        original_private_paths_referenced_by_tools=['artifact/firmware/bsp/esp32', 'artifact/firmware/bsp/esp32/rhealstone',
            'original OS SDK workspaces and resolved build configurations'],
        reference_only=['TenonOS Section 5 supplies metrics/methods; Tenon is not an original B1 subject'])


def preflight(project_file=None):
    entries = {} if project_file is None else {p['configuration']: p for p in json.loads(project_file.read_text())['projects']}
    if set(entries) - {s['id'] for s in subjects()}: raise ValueError('Unknown original EunoBench configuration')
    rows = []
    for target in subjects():
        supplied = entries.get(target['id'], {})
        missing = []
        for name in NEEDED:
            value = supplied.get(name)
            if not value: missing.append(name + ': not supplied'); continue
            path = Path(value).expanduser()
            if not path.is_absolute() or not path.exists(): missing.append(name + ': absolute existing path required')
            elif not path.resolve().is_relative_to((Path.home()/'eunobench').resolve()):
                missing.append(name + ': native project must be under /home/zyc/eunobench')
        rows.append(dict(configuration=target['id'], version=target['version'],
            ready_for_build_review=not missing, acquisition_completed=False, missing=missing,
            note='Path readiness is not native-adapter equivalence or performance qualification'))
    return dict(schema=1, subjects=rows, ready_projects=sum(r['ready_for_build_review'] for r in rows),
                total_subjects=len(rows), new_OS_measurements=0)
