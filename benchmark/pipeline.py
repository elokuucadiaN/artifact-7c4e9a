"""Single EunoBench result path for existing categories and registered new metrics."""
import argparse
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile

from .adapters import ROOT, CurrentB1Adapter, TenonPrototypeAdapter, backend, sha
from .catalog import METRICS, BY_ID, validate_record


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def write_csv(path, rows, columns=None):
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns or list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def summarize(records):
    groups = defaultdict(list)
    for row in records:
        validate_record(row)
        key = (row['metric_id'], row['configuration'], json.dumps(row['parameters'], sort_keys=True), row['unit'], row['execution_scope'])
        groups[key].append(row)
    result = []
    for (metric, config, params, unit, scope), rows in sorted(groups.items()):
        ids = [r['sample_id'] for r in rows]
        if len(set(ids)) != len(ids): raise ValueError('Repeated sample in one measurement cell')
        if len({r['sample_kind'] for r in rows}) != 1: raise ValueError('Mixed statistical units')
        if len({json.dumps(r['bindings'], sort_keys=True) for r in rows}) != 1:
            raise ValueError('Cannot pool changed configurations/images')
        values = [r['value'] for r in rows]
        kind = rows[0]['sample_kind']
        result.append(dict(metric_id=metric, configuration=config, parameters=params, unit=unit,
            execution_scope=scope, sample_kind=kind, records=len(rows),
            independent_guests=len(rows) if kind == 'fresh_guest' else 0,
            independent_processes=len(rows) if kind == 'fresh_process' else 0,
            source_statistic=rows[0]['statistic'], median=statistics.median(values),
            minimum=min(values), maximum=max(values),
            board_comparison_eligible=all(r['comparison_eligible'] for r in rows),
            original_overall_eligible=all(r['overall_eligible'] for r in rows)))
    return result


def coverage(records, configurations):
    result = []
    for contract in METRICS:
        for config in configurations:
            rows = [r for r in records if r['metric_id'] == contract['id'] and r['configuration'] == config['id']]
            reason = ''
            if rows:
                if rows[0]['sample_kind'] == 'static_build': status = 'static_descriptor'
                elif rows[0]['execution_scope'] == 'physical_board': status = 'archived_measurement'
                else: status = 'simulation_verified'
            elif config['kind'] == 'source' and contract['id'] != 'source.physical_lines':
                status, reason = 'not_applicable', 'Source descriptor is not a deployed runtime'
            elif config.get('execution_model') == 'cooperative_process' and contract['id'] in ('scheduler.switch_scale','scheduler.legacy_switch','scheduler.legacy_multi_switch','scheduler.preempt_roundtrip','scheduler.semaphore_wakeup_entry','ipc.semaphore_shuffle','ipc.semaphore_pingpong','interrupt.trigger_to_isr','timer.interference_offset'):
                status, reason = 'not_applicable', 'This native cooperative configuration has no priority threads, blocking semaphore scheduler or hardware ISR; host services cannot substitute'
            elif config.get('execution_model') == 'threaded' and contract['id']=='scheduler.cooperative_dispatch_scale':
                status, reason = 'not_applicable', 'Separate contract for native cooperative event processes'
            else:
                status, reason = 'unmeasured', 'No qualifying capture registered for this metric and exact configuration'
            result.append(dict(metric_id=contract['id'], configuration=config['id'], status=status,
                records=len(rows), scope=config['scope'], reason=reason))
    return result


def latex(value):
    result = str(value)
    for a, b in [('&', r'\&'), ('_', r'\_'), ('%', r'\%'), ('#', r'\#')]: result = result.replace(a, b)
    return result


def render(output, records, configurations, summary, matrix):
    native_configs={r['configuration'] for r in records if r['sample_kind']=='fresh_process'}
    native_processes={(r['configuration'],r['sample_id']) for r in records if r['sample_kind']=='fresh_process'}
    lines = ['# EunoBench unified results', '',
        'The same EunoBench metric layer contains the original common-task measurements and the TenonOS-inspired additions.', '',
        '## Existing common-task leaderboard', '',
        'Recomputed by the original replay/production numerical functions. Eight B1 deployment configurations, 48 archived scalars, 235 preference profiles. The original four-category Overall policy is preserved.', '',
        '| Configuration | Overall | Rank |', '| --- | ---: | ---: |']
    with (output / 'leaderboard.csv').open() as f:
        for row in csv.DictReader(f):
            lines.append(f"| {row['configuration']} | {float(row['overall']):.4f} | {row['rank']} |")
    lines += ['', '## Registered system-overhead and real-time metrics', '',
        'The original eight B1 deployments remain the board subjects. Reconstructed configurations of the same OS families are separately registered for functional testing. TenonOS supplies metric references. Reconstructed simulator records do not fill original ESP32 cells.', '',
        '| Metric | Reference | Unit | B1 configurations with data | Simulator configurations with data |', '| --- | --- | --- | ---: | ---: |']
    tex = [r'% Generated from the EunoBench metric registry and actual imported records.',
        r'\begin{table*}[t]', r'\centering\small', r'\begin{tabular}{p{.27\textwidth}p{.32\textwidth}lll}',
        r'\hline Metric & TenonOS reference & Unit & B1 & Simulator \\ \hline']
    for item in METRICS:
        if item['origin'] == 'existing': continue
        matches = [r for r in records if r['metric_id'] == item['id']]
        boards = len({r['configuration'] for r in matches if r['execution_scope'] == 'physical_board'})
        tcg = len({r['configuration'] for r in matches if r['execution_scope'] == 'simulation_functional_validation'})
        lines.append(f"| {item['title']} | {item['reference']} | {item['unit']} | {boards} | {tcg} |")
        tex.append(' & '.join(latex(x) for x in (item['title'], item['reference'], item['unit'], boards, tcg)) + r' \\')
    tex += [r'\hline\end{tabular}',
        r'\caption{Added EunoBench metric definitions and evidence status. Simulator columns denote functional validation, not hardware performance. Host ELF sections are not embedded Flash or dynamic RAM.}',
        r'\label{tab:eunobench-tenon-metrics}', r'\end{table*}', '']
    (output / 'eunobench-new-metrics.tex').write_text('\n'.join(tex), encoding='utf-8')
    lines += ['', f'**Status: {len(native_configs)} paper-version host configurations verified in {len(native_processes)} independent processes for the selected native probes. New measurements on the original eight ESP32 B1 deployments remain pending.**', '',
        '## Measurement and coverage outputs', '',
        '- `measurements.jsonl` / `measurements.csv`: one common record schema for all imported quantities, with units, parameters, statistical units and evidence/image/config bindings.',
        '- `summary.csv`: per-configuration, per-parameter summaries. It never pools board/TCG records or counts static sizes and archived aggregates as fresh guests.',
        '- `metric-coverage.csv`: all registered metrics across every registered configuration, including unmeasured and inapplicable cells.',
        '- `legacy-coverage.csv`: original 70-cell workload coverage, preserved separately from new metric acquisition status.',
        '- `catalog.json` / `metric-definitions.csv`: operations, endpoints, denominators, units and paper references.',
        '- `eunobench-new-metrics.tex`: generated paper table; `PAPER_UPDATE.md`: implementation/status text.', '',
        'Native reconstruction captures are admitted only when their source revisions match the EunoBench paper. Each admitted family has three independent processes, five worker counts and five timer counts, plus one static linked ELF. Contiki cooperative dispatch is a separate contract from stackful worker switching. Timer callback contexts remain OS-specific.', '',
        'Extended-v2 captures additionally verify port-specific native C-entry startup, semaphore release-to-higher-priority entry, native semaphore request/ack roundtrips, native-clock requested-deadline offset and benchmark C-callback-body windows. Contiki priority-thread tests are inapplicable. Deadline offsets stay in their declared OS clock domain; zero at tick resolution is not zero hardware latency. Declared source-scope C/header lines are replayed from hashed source snapshots and are not TCB size.', '',
        'The legacy six test bodies already existed in EunoBench. Their new generic-counter profile and the new scaling dimensions are not described as first ports.', '',
        'No new hardware performance, physical reset-to-ready, energy, Mortise co-location or full architectural ISR phase measurement is claimed. New metrics have not been assigned unmeasured values or silently added to Overall.', '',
        f"Registered metrics: {len(METRICS)}; configurations/source objects: {len(configurations)}; measurement records: {len(records)}; summary cells: {len(summary)}."]
    (output / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (output / 'PAPER_UPDATE.md').write_text('''# EunoBench paper update

## Scope and workloads (§2 and Table 1)

EunoBench now registers system-overhead and real-time measurements inspired by TenonOS Section 5 alongside its existing task, communication, energy and memory categories. The additions cover ELF-section footprint, a defined initialization interval, same-priority worker scaling with extended-context preservation modes, the existing switching/preemption/semaphore/IRQ tests under an explicit counter profile, timer-count scaling under fixed-tick and tickless configurations, and a separately scoped source-size descriptor. Existing six-body coverage and new acquisition dimensions are distinguished.

## Measurement layer (§3)

All adapters emit one EunoBench record schema binding the metric contract, exact configuration, platform, execution scope, parameters, statistical unit and raw evidence. Source/linked-image descriptors, archived reset aggregates and fresh-guest samples remain distinct. Summary cells require identical parameter and image/configuration bindings. Missing captures remain explicit; simulation evidence cannot be promoted to physical-board eligibility. Kernel-entry-to-main is not physical reset time, ELF size is not peak allocated RAM, and trigger-to-ISR response is not the complete interrupt save/dispatch/restore path.

## Implementation and evidence (§4–5)

The root EunoBench entry preserves the frozen B1 replay and registers the added contracts on the original eight configurations. The native runner rebuilds paper-pinned OS source revisions and checks progress, timer callback multiplicity/context and linked-image sections in new host simulator configurations. Each runtime grid cell has three independent OS processes. Native cooperative Contiki dispatch has its own contract and does not become a stackful context-switch result. The distributed review snapshot omits the original complete ESP32 projects; their added B1 measurements remain pending. Tenon reference evidence, if imported explicitly, is reported outside the main subject dataset and cannot fill the original OS cells.

## Results and limitations (§5–6)

Include the generated eunobench-new-metrics.tex as a definition/evidence-status table. Keep the existing eight-configuration leaderboard and original four-category Overall policy. Place host simulator numerical summaries in an implementation-validation appendix, not in a board-performance comparison. The clocks, ports, linked host libraries, timer mechanisms and execution models differ; simulator times do not support a cross-OS hardware ranking. Actual new B1 comparisons, physical startup, complete interrupt phases and Mortise/Linux co-location remain future measurement work.
''', encoding='utf-8')


def seal(output):
    save(output / 'bundle-manifest.json', {'schema': 1,
        'members': {str(p.relative_to(output)): sha(p) for p in output.rglob('*') if p.is_file() and p.name != 'bundle-manifest.json'},
        'scope': 'Self-consistency manifest; not an external identity attestation'})


def evaluate(capture, output, existing=False, native_capture=None, matrix_capture=None, qemu_capture=None):
    backend().native_storage({'eunobench_source': ROOT, 'integrated_output': output})
    output.mkdir(parents=True, exist_ok=existing)
    original, configurations = CurrentB1Adapter().collect(output)
    records = original
    native_records=[]
    if native_capture is not None:
        from .native_adapter import collect
        backend().native_storage({'native_capture':native_capture})
        native_records, native_configs=collect(native_capture,output)
        records=original+native_records
        configurations+=native_configs
        subjects=json.loads((native_capture/'receipt.json').read_text())['subjects']
        write_csv(output/'os-version-qualification.csv',[
            dict(os=s['os'],upstream_commit=s.get('upstream_commit',''),status=s['status'],
                 paper_version_match=s.get('paper_version_match',False),independent_processes=s.get('independent_processes',0))
            for s in subjects])
    supplemental_records=[];supplemental_configs=[]
    for supplemental,kind in [(matrix_capture,'matrix'),(qemu_capture,'qemu')]:
        if supplemental is not None:
            from .matrix_adapter import collect as supplemental_collect
            added,added_configs=supplemental_collect(supplemental,output,kind)
            supplemental_records+=added;supplemental_configs+=added_configs
    records+=supplemental_records;configurations+=supplemental_configs
    reference = []
    if capture is not None:
        reference, reference_configs = TenonPrototypeAdapter().collect(capture, output)
        save(output/'reference-tenon-only.json', {'records': reference, 'configurations': reference_configs,
            'scope': 'Method/instrumentation reference only; excluded from original-OS measurement cells'})
    from .subjects import preparation, preflight
    plan = preparation()
    save(output/'acquisition-plan.json', plan)
    save(output/'projects.template.json', plan['project_template'])
    save(output/'readiness.json', preflight())
    summary, matrix = summarize(records), coverage(records, configurations)
    save(output / 'catalog.json', {'schema': 1, 'metrics': METRICS})
    save(output / 'configurations.json', configurations)
    save(output / 'source-identities.json', {str(p.relative_to(ROOT)): sha(p) for p in [ROOT/'eunobench.py', *sorted((ROOT/'benchmark').glob('*.py'))]})
    with (output / 'measurements.jsonl').open('w', encoding='utf-8') as f:
        for r in records: f.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + '\n')
    flat = [{**r, 'parameters': json.dumps(r['parameters'], sort_keys=True), 'bindings': json.dumps(r['bindings'], sort_keys=True)} for r in records]
    write_csv(output / 'measurements.csv', flat)
    write_csv(output / 'summary.csv', summary)
    write_csv(output / 'metric-coverage.csv', matrix)
    write_csv(output / 'metric-definitions.csv', [{**m, 'parameters': json.dumps(m['parameters'])} for m in METRICS])
    render(output, records, configurations, summary, matrix)
    receipt = dict(pass_=True, baseline_configurations=8, baseline_scalars=len(original),
        registered_metrics=len(METRICS), added_metric_contracts=sum(m['origin'] != 'existing' for m in METRICS),
        imported_records=len(records), summary_cells=len(summary), coverage_cells=len(matrix),
        reference_only_records=len(reference), original_OS_new_metric_records=0,
        reconstructed_native_records=len(native_records),
        supplemental_records=len(supplemental_records),supplemental_configurations=len(supplemental_configs),
        paper_version_simulator_configurations=len(native_configs) if native_capture is not None else 0,
        native_runtime_records=sum(r['sample_kind']=='fresh_process' for r in native_records),
        original_OS_new_measurements_complete=False,
        new_guests=0, new_board_measurements=0, original_overall_policy='unchanged four categories',
        measurement_scope='Original eight archived EunoBench configurations plus separately attributed paper-version simulator captures; new original-board metrics remain pending')
    receipt['pass'] = receipt.pop('pass_')
    save(output / 'receipt.json', receipt)
    seal(output)
    return receipt


def verify(source):
    manifest = json.loads((source / 'bundle-manifest.json').read_text())
    for name, expected in manifest['members'].items():
        p = (source/name).resolve()
        if not p.is_relative_to(source) or not p.is_file() or sha(p) != expected:
            raise ValueError('Changed/missing EunoBench evidence: ' + name)
    actual = {str(p.relative_to(source)) for p in source.rglob('*') if p.is_file() and p.name != 'bundle-manifest.json'}
    if actual != set(manifest['members']): raise ValueError('Unexpected/missing bundle member')
    scratch = Path.home()/'eunobench/integration-checks'
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='verify-', dir=scratch) as temp:
        fresh = Path(temp)/'evaluated'
        capture = source/'evidence/tenon'
        native=source/'evidence/native-batch'
        matrix=source/'evidence/zephyr-matrix';qemu=source/'evidence/arm-qemu'
        evaluate(capture if capture.exists() else None, fresh,native_capture=native if native.exists() else None,matrix_capture=matrix if matrix.exists() else None,qemu_capture=qemu if qemu.exists() else None)
        names = ['measurements.jsonl', 'measurements.csv', 'summary.csv', 'metric-coverage.csv', 'leaderboard.csv', 'catalog.json', 'metric-definitions.csv']
        if (source/'os-version-qualification.csv').exists():names.append('os-version-qualification.csv')
        for name in names:
            if sha(source/name) != sha(fresh/name): raise ValueError('Semantic replay differs: ' + name)
    return {'pass': True, 'recomputed_files': names, 'new_guests': 0}


def export(source, output):
    backend().native_storage({'eunobench_results': source})
    root = Path('/mnt/e/learn/benchmark/output').resolve()
    if output == root or not output.is_relative_to(root) or output.exists():
        raise ValueError('Use a new export directory under Windows output')
    result = verify(source)
    shutil.copytree(source, output)
    before = {str(p.relative_to(source)): sha(p) for p in source.rglob('*') if p.is_file()}
    after = {str(p.relative_to(output)): sha(p) for p in output.rglob('*') if p.is_file()}
    if before != after: raise ValueError('Post-export hash mismatch')
    save(output.with_name(output.name+'.export.json'), dict(result, files_verified=len(after), source=str(source), destination=str(output)))
    return dict(result, files_verified=len(after))


def main():
    p = argparse.ArgumentParser(description='EunoBench unified runtime metric evaluation')
    commands = p.add_subparsers(dest='command', required=True)
    commands.add_parser('catalog')
    q = commands.add_parser('evaluate')
    q.add_argument('--output', type=Path, required=True)
    q.add_argument('--tenon-capture', type=Path, help='Optional method reference only; never added to original OS result cells')
    q.add_argument('--native-capture', type=Path, help='Verified OS-family reconstruction batch; separate from original B1 deployments')
    q.add_argument('--zephyr-matrix',type=Path)
    q.add_argument('--qemu-capture',type=Path)
    q = commands.add_parser('prepare')
    q.add_argument('--output', type=Path, required=True)
    q = commands.add_parser('preflight')
    q.add_argument('--projects', type=Path)
    q = commands.add_parser('verify'); q.add_argument('--input', type=Path, required=True)
    q = commands.add_parser('export'); q.add_argument('--input', type=Path, required=True); q.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.command == 'catalog': result = {'schema': 1, 'metrics': METRICS}
    elif a.command == 'verify': result = verify(a.input.resolve())
    elif a.command == 'export': result = export(a.input.resolve(), a.output.resolve())
    elif a.command == 'evaluate': result = evaluate(a.tenon_capture.resolve() if a.tenon_capture else None, a.output.resolve(),native_capture=a.native_capture.resolve() if a.native_capture else None,matrix_capture=a.zephyr_matrix.resolve() if a.zephyr_matrix else None,qemu_capture=a.qemu_capture.resolve() if a.qemu_capture else None)
    elif a.command == 'preflight':
        from .subjects import preflight
        result = preflight(a.projects.resolve() if a.projects else None)
    else:
        from .subjects import preparation, preflight
        output = a.output.resolve()
        backend().native_storage({'eunobench_source': ROOT, 'preparation_output': output})
        output.mkdir(parents=True, exist_ok=False)
        plan = preparation()
        save(output/'acquisition-plan.json', plan)
        save(output/'projects.template.json', plan['project_template'])
        save(output/'readiness.json', preflight())
        result = {'pass': True, 'prepared_subjects': len(plan['subjects']),
            'planned_metric_subject_pairs': len(plan['experiments']), 'acquisition_completed': False}
    print(json.dumps(result, indent=2, ensure_ascii=False))
