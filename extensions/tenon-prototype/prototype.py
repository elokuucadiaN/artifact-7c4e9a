#!/usr/bin/env python3
"""Build and exercise native Tenon under ARM64 TCG. No board-performance claims.

Standard library only, except ELF inspection uses the snapshot's vendored pyelftools.
Never changes artifact/, its source commitments, or the historical leaderboard.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ARTIFACT = REPO / "artifact"
WORKERS = [2, 10, 20, 50, 100]
TIMERS = [1, 10, 20, 50, 100]
CASES = ["task_switch", "multi_switch", "preempt", "semaphore_shuffle", "interrupt_entry", "timer_offset"]
LABELS = ["average_task_switch_time", "average_multi_task_switch_time", "average_task_preempt_time",
          "average_semaphore_shuffle_time", "interrupt_latency_time", "timer_deviation_under_interrupt_interference"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError("Source patch anchor missing or repeated: " + old[:70])
    return text.replace(old, new, 1)


def command(argv, folder, name, timeout=600):
    folder.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with (folder / (name + ".stdout")).open("wb") as out, (folder / (name + ".stderr")).open("wb") as err:
        result = subprocess.run([str(x) for x in argv], stdout=out, stderr=err, timeout=timeout)
    record = {"argv": list(map(str, argv)), "returncode": result.returncode,
              "host_elapsed_s": time.monotonic() - started,
              "stdout_sha256": sha(folder / (name + ".stdout")),
              "stderr_sha256": sha(folder / (name + ".stderr"))}
    save(folder / (name + ".json"), record)
    if result.returncode:
        tail = (folder / (name + ".stderr")).read_text(errors="replace")[-3500:]
        raise RuntimeError(f"{name} failed ({result.returncode}); see {folder}\n{tail}")
    return record


def environment():
    tools = ["make", "gcc", "bison", "flex", "aarch64-linux-gnu-gcc", "qemu-system-aarch64"]
    result = {"system": platform.platform(), "host_arch": platform.machine(),
              "python": sys.version, "tools": {}, "accelerator": "tcg", "guest_arch": "aarch64",
              "ranking_eligible": False, "scope": "simulation_functional_validation"}
    for name in tools:
        path = shutil.which(name)
        if not path:
            raise RuntimeError("Missing required executable: " + name)
        version = subprocess.check_output([path, "--version"], text=True).splitlines()[0]
        result["tools"][name] = {"path": path, "version": version}
    return result


def native_storage(paths):
    """Require active experiment inputs/outputs to stay on the named Linux root."""
    base = (Path.home() / 'eunobench').resolve()
    records = {}
    for name, value in paths.items():
        path = Path(value).resolve()
        if not path.is_relative_to(base):
            raise ValueError(f'{name} must be under {base}, not {path}. Run from the Linux source copy; export after completion.')
        ancestor = path
        while not ancestor.exists(): ancestor = ancestor.parent
        mount = json.loads(subprocess.check_output(
            ['findmnt', '--json', '--target', str(ancestor), '--output', 'TARGET,FSTYPE,SOURCE'], text=True))['filesystems'][0]
        if mount['fstype'] not in ('ext4', 'xfs', 'btrfs'):
            raise ValueError(f'{name} is not on a native Linux filesystem: {mount}')
        records[name] = {'path': str(path), 'mount': mount}
    return {'policy': 'all active source/build/image/capture files under native Linux home; post-run export only',
            'root': str(base), 'paths': records}


def stage(work, rounds, iterations, source=None):
    source = source or ARTIFACT / "third_party"
    dest = work / "source"
    shutil.copytree(source / "tenon-c11", dest / "tenon-c11")
    shutil.copytree(source / "libs", dest / "libs")
    # The wrapper points at a remote archive. Use the already distributed patched source.
    app = dest / "app-euno-prototype"
    shutil.copytree(source / "apps/app-rtos-benchmark-abi", app)
    changes = []

    def edit(path, transform):
        before = sha(path)
        text = path.read_text(encoding="utf-8")
        path.write_text(transform(text), encoding="utf-8")
        changes.append({"path": str(path.relative_to(dest)), "before_sha256": before, "after_sha256": sha(path)})

    wrapper = dest / "libs/lib-tlsf/Makefile.uk"
    shutil.copytree(source / "TLSF-patched", dest / "libs/lib-tlsf/offline/TLSF-2.4.6")
    edit(wrapper, lambda s: replace_once(replace_once(s,
        'ifeq ($(CONFIG_LIBTLSF),y)\n$(eval $(call fetch,libtlsf,$(LIBTLSF_URL),TLSF-$(LIBTLSF_VERSION).tbz2))\n$(eval $(call patch,libtlsf,$(LIBTLSF_PATCHDIR),$(LIBTLSF_DIR)))\nendif',
        '# Offline build of the exact patched source distributed in this snapshot.'),
        'LIBTLSF=$(LIBTLSF_ORIGIN)/$(LIBTLSF_DIR)', 'LIBTLSF=$(LIBTLSF_BASE)/offline/$(LIBTLSF_DIR)'))
    edit(app / "include/rst_cfg.h", lambda s: replace_once(s, "#define RST_BENCHMARKS_COUNT 500", f"#define RST_BENCHMARKS_COUNT {iterations}"))
    edit(app / "include/rst_def.h", lambda s: replace_once(s, "#define BOARD_CLOCK_FREQUENCY 24000000",
        "extern uint64_t euno_frequency(void);\n#define BOARD_CLOCK_FREQUENCY euno_frequency()"))
    for path in sorted((app / "src").glob("*.c")):
        if "in cpu cycles" in path.read_text():
            edit(path, lambda s: s.replace("in cpu cycles", "in generic timer counts"))
    for name in ("Makefile.uk", "Config.uk", "main.c", "clock.c"):
        shutil.copyfile(HERE / "app" / name, app / name)
    (app / "include/euno_config.h").write_text(f"#define EUNO_ROUNDS {rounds}\n")
    kernel = dest / "tenon-c11"
    edit(kernel / "lib/ukboot/boot.c", lambda s: replace_once(s,
        "void ukplat_entry(int argc, char *argv[])\n{",
        "void ukplat_entry(int argc, char *argv[])\n{\n\textern void euno_boot_mark(void);\n\teuno_boot_mark();"))
    edit(kernel / "lib/tnsystick/tnsystick.c", lambda s: replace_once(replace_once(s,
        "int sys_timer_irq_handler(void *arg __unused)\n{",
        "int sys_timer_irq_handler(void *arg __unused)\n{\n\textern uint64_t euno_timer_irq_begin(void);\n\textern void euno_timer_irq_end(uint64_t);\n\tuint64_t euno_start = euno_timer_irq_begin();"),
        "/* todo: Interrupt processing temporarily returns 0 */\n\treturn 0;",
        "/* Measured body excludes architectural IRQ entry and return. */\n\teuno_timer_irq_end(euno_start);\n\treturn 0;"))
    hashes = {str(p.relative_to(dest)): sha(p) for p in dest.rglob("*") if p.is_file()}
    return dest, {"schema": 1, "source_files": hashes, "derived_source_changes": changes,
                  "new_app_files": {n: sha(HERE / "app" / n) for n in ("Makefile.uk", "Config.uk", "main.c", "clock.c")},
                  "rounds": rounds, "legacy_iterations": iterations,
                  "original_six_bodies": "derived: generic-counter labels; bodies otherwise retained",
                  "original_artifact_modified": False}


def config_for(source, mode):
    # Minimal native priority scheduler + the same supplied TLSF implementation.
    return '\n'.join([
        'CONFIG_ARCH_ARM_64=y', 'CONFIG_MCPU_ARM64_CORTEX_A72=y',
        'CONFIG_PLAT_KVM=y', 'CONFIG_FPSIMD=y', 'CONFIG_VIRTUALIZE_PLAT_MEM_SIZE=0x8000000',
        'CONFIG_LIBUKLOCK=y', 'CONFIG_LIBUKLOCK_SEMAPHORE=y',
        '# CONFIG_LIBUKLOCK_MUTEX is not set', '# CONFIG_LIBUKLOCK_RWLOCK is not set',
        'CONFIG_LIBTNSYSTICK_FREQ=1000',
        'CONFIG_LIBTNSYSTICK_TICKLESS=y' if mode == 'tickless' else '# CONFIG_LIBTNSYSTICK_TICKLESS is not set',
        'CONFIG_LIBUKBOOT_INITSCHEDPRIO=y', 'CONFIG_LIBTNSCHEDPRIO_ENABLE_PREEMTIVE=y',
        'CONFIG_LIBTLSF=y', 'CONFIG_LIBUKBOOT_INITTLSF=y', 'CONFIG_TLSF_LOG2_SLI=2',
        'CONFIG_LIBTNTIMER=y', 'CONFIG_TIME_USE_64BIT=y', 'CONFIG_LIBUKDEBUG_PRINTK_ERR=y',
        'CONFIG_OPTIMIZE_PERF=y', '# CONFIG_OPTIMIZE_WARNISERROR is not set',
        'CONFIG_UK_NAME="app-euno-prototype"', ''])


def build(source, work, output, mode):
    folder = work / ("build-" + mode)
    folder.mkdir()
    config = folder / ".config"
    initial = folder / "input.defconfig"
    initial.write_text(config_for(source, mode))
    argv = ["make", "-C", source / "tenon-c11", "A=" + str(source / "app-euno-prototype"),
            "L=" + str(source / "libs"), "O=" + str(folder / "build"),
            "C=" + str(config), "CROSS_COMPILE=aarch64-linux-gnu-", "COMPILER=gcc"]
    logs = output / mode / "build"
    command([*argv, "UK_DEFCONFIG=" + str(initial), "defconfig"], logs, "configure")
    resolved = config.read_text()
    if ('CONFIG_LIBTNSYSTICK_TICKLESS=y' in resolved) != (mode == 'tickless'):
        raise ValueError("Tick mode did not resolve as requested")
    for required in ['CONFIG_LIBUKBOOT_INITSCHEDPRIO=y', 'CONFIG_LIBTNTIMER=y', 'CONFIG_TIME_USE_64BIT=y', 'CONFIG_LIBUKBOOT_INITTLSF=y']:
        if required not in resolved: raise ValueError("Missing resolved setting " + required)
    command([*argv, "-j4"], logs, "compile")
    images = list((folder / "build").glob("*_qemu-arm64"))
    if len(images) != 1: raise ValueError("Expected exactly one ARM64 image")
    shutil.copyfile(images[0], logs / "runtime.img")
    shutil.copyfile(Path(str(images[0]) + '.dbg'), logs / "runtime.elf")
    shutil.copyfile(config, logs / "resolved.config")
    shutil.copyfile(initial, logs / "input.defconfig")
    # Kernel map files are auxiliary; ELF section headers are the resource source.
    for p in (folder / "build").glob("*.map"):
        shutil.copyfile(p, logs / p.name)
    resource = elf_sections(logs / "runtime.elf")
    save(logs / "sections.json", resource)
    save(logs / "identity.json", {"mode": mode, "image_sha256": sha(logs / "runtime.elf"),
        "boot_image_sha256": sha(logs / "runtime.img"),
        "config_sha256": sha(logs / "resolved.config"), "source_manifest_sha256": sha(output / "source-manifest.json"),
        "sections_sha256": sha(logs / "sections.json"), "ranking_eligible": False})
    return logs / "runtime.img"


def elf_sections(path):
    sys.path.insert(0, str(ARTIFACT / "vendor"))
    from elftools.elf.elffile import ELFFile
    with path.open("rb") as stream:
        elf = ELFFile(stream)
        rows = [{"name": s.name, "bytes": s['sh_size'], "address": s['sh_addr'], "type": s['sh_type'],
                 "writable": bool(s['sh_flags'] & 1), "executable": bool(s['sh_flags'] & 4)}
                for s in elf.iter_sections() if s['sh_flags'] & 2]
    return {"image_sha256": sha(path), "file_bytes": path.stat().st_size, "allocated_sections": rows,
            "allocated_section_bytes": sum(r['bytes'] for r in rows),
            "nobits_section_bytes": sum(r['bytes'] for r in rows if r['type'] == 'SHT_NOBITS'),
            "boundary": "ELF SHF_ALLOC sections; excludes runtime heap/stack allocations and is not a peak-RAM claim"}


def physical_code_lines(text):
    """Physical nonblank lines after C-style comments; preserves quoted literals."""
    state, escaped, count = 'code', False, 0
    for line in text.splitlines():
        used, i = False, 0
        while i < len(line):
            c, pair = line[i], line[i:i+2]
            if state == 'comment':
                if pair == '*/': state = 'code'; i += 2; continue
            elif state in ('"', "'"):
                used = True
                if escaped: escaped = False
                elif c == '\\': escaped = True
                elif c == state: state = 'code'
            elif pair == '//': break
            elif pair == '/*': state = 'comment'; i += 2; continue
            elif c in ('"', "'"): state = c; used = True
            elif not c.isspace(): used = True
            i += 1
        count += used
    return count


def source_size(source):
    totals = {}
    members = []
    for p in sorted((source / 'tenon-c11').rglob('*')):
        if not p.is_file() or p.suffix not in ('.c', '.S', '.s'): continue
        relative = p.relative_to(source / 'tenon-c11')
        group = relative.parts[0]
        kind = 'C' if p.suffix == '.c' else 'asm'
        lines = physical_code_lines(p.read_text(errors='replace'))
        totals.setdefault(group, {'C': 0, 'asm': 0})[kind] += lines
        members.append({'path': str(relative), 'kind': kind, 'lines': lines, 'sha256': sha(p)})
    return {'groups': totals, 'files': members,
            'scope': 'Entire supplied Tenon source tree .c/.S/.s; excludes headers and external TLSF; includes tests and unlinked features. Physical nonblank lines excluding C-style comments, not binary-linked TCB or the paper SLoC scope.'}


def fields(line):
    result = {}
    for token in line.split()[1:]:
        key, value = token.split('=', 1)
        if key in result: raise ValueError("Repeated field " + key)
        result[key] = int(value) if re.fullmatch(r'-?\d+', value) else value
    return result


def validate(log, mode, rounds, iterations):
    clean = re.sub(r'\x1b\[[0-9;]*m', '', log)
    lines = clean.splitlines()
    if re.search(r'EUNO_FAIL|\bPANIC\b|Assertion failure|unhandled trap|Fatal exception', clean, re.I):
        raise ValueError("Guest failure marker")
    def rows(prefix): return [fields(x) for x in lines if x.startswith(prefix + ' ')]
    meta, boot, done = rows('EUNO_META'), rows('EUNO_BOOT'), rows('EUNO_DONE')
    if len(meta) != 1 or meta[0] != {'schema': 1, 'mode': mode, 'counter': 'cntvct',
            'frequency_hz': meta[0].get('frequency_hz'), 'tick_hz': 1000,
            'rounds': rounds, 'legacy_iterations': iterations}:
        raise ValueError("Wrong/missing guest metadata")
    if not isinstance(meta[0]['frequency_hz'], int) or meta[0]['frequency_hz'] <= 0:
        raise ValueError("Invalid counter frequency")
    if len(boot) != 1 or boot[0].get('boundary') != 'ukplat_entry_to_main' or boot[0].get('elapsed_counts', 0) <= 0:
        raise ValueError("Invalid boot boundary")
    if len(done) != 1 or done[0] != {'failures': 0} or not lines[-1].startswith('EUNO_DONE '):
        # Normal kernel termination messages may follow EUNO_DONE.
        if len(done) != 1 or done[0] != {'failures': 0}: raise ValueError("Incomplete/failed guest")
    evidence = [x for x in lines if x.startswith('EUNO_')]
    if not evidence or not evidence[0].startswith('EUNO_META ') or not evidence[-1].startswith('EUNO_DONE '):
        raise ValueError('Evidence outside run envelope')
    begin, end = rows('EUNO_CASE_BEGIN'), rows('EUNO_CASE_END')
    if begin != [{'name': n} for n in CASES] or end != [{'name': n, 'status': 0} for n in CASES]:
        raise ValueError("Original six case status/order missing")
    legacy = {}
    position = clean.index('EUNO_BOOT ')
    for name, label in zip(CASES, LABELS):
        start = clean.index('EUNO_CASE_BEGIN name=' + name + '\n', position) if 'EUNO_CASE_BEGIN name=' + name + '\n' in clean[position:] else clean.index('EUNO_CASE_BEGIN name=' + name + '\r\n', position)
        finish = clean.index('EUNO_CASE_END name=' + name + ' status=0', start)
        position = finish
        case_text = clean[start:finish]
        values = re.findall(r'(?m)^R-Rhealstone: ' + label + r', [^\r\n]+ - (-?\d+) count\r?$', case_text)
        if len(values) != 1: raise ValueError("Missing or repeated legacy measurement: " + name)
        legacy[name] = int(values[0])
    switches = rows('EUNO_SWITCH')
    if [(r.get('ectx'), r.get('workers')) for r in switches] != [(e, n) for e in [0, 1] for n in WORKERS]:
        raise ValueError("Switch grid missing, repeated or reordered")
    for r in switches:
        n = r['workers']
        if r.get('rounds') != rounds or r.get('entries') != n * rounds or r.get('handoffs') != n * rounds - 1 or r.get('errors') != 0 or r.get('elapsed_counts', 0) <= 0:
            raise ValueError("Worker/handoff facts failed")
    timers = rows('EUNO_TIMER')
    if [r.get('timers') for r in timers] != TIMERS: raise ValueError("Timer grid incomplete")
    for r in timers:
        if r.get('callbacks') != r['timers'] or r.get('errors') != 0 or r.get('irq_count', 0) < 1 or r.get('irq_handler_counts', 0) <= 0 or r.get('arm_counts', 0) <= 0 or r.get('max_late_counts', -1) < 0:
            raise ValueError("Timer callbacks/IRQ facts failed")
    return {"pass": True, "meta": meta[0], "boot": boot[0], "legacy": legacy,
            "switches": switches, "timers": timers, "ranking_eligible": False,
            "legacy_validation": "return status and output completeness; not independent adapter-equivalence certification"}


def boot(image, folder, mode, rounds, iterations, timeout):
    folder.mkdir(parents=True, exist_ok=False)
    argv = ['qemu-system-aarch64', '-machine', 'virt,gic-version=2', '-accel', 'tcg', '-cpu', 'cortex-a72',
            '-smp', '1', '-m', '128M', '-nographic', '-monitor', 'none', '-nic', 'none', '-no-reboot', '-kernel', str(image)]
    started = time.monotonic()
    stopped_after_completion = False
    with (folder / 'guest.stdout').open('wb') as out, (folder / 'guest.stderr').open('wb') as err:
        proc = subprocess.Popen(argv, stdout=out, stderr=err)
        try:
            while proc.poll() is None:
                text = (folder / 'guest.stdout').read_text(errors='replace')
                if 'EUNO_DONE ' in text:
                    try: proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.terminate(); stopped_after_completion = True
                    break
                if time.monotonic() - started > timeout:
                    raise TimeoutError('Guest exceeded deadline; partial logs retained at ' + str(folder))
                time.sleep(0.1)
            proc.wait(timeout=5)
        finally:
            if proc.poll() is None: proc.kill(); proc.wait()
    status = {'argv': argv, 'returncode': proc.returncode, 'fresh_process': True,
              'stopped_after_completion': stopped_after_completion, 'host_process_elapsed_s': time.monotonic() - started,
              'image_sha256': sha(image), 'stdout_sha256': sha(folder / 'guest.stdout'),
              'stderr_sha256': sha(folder / 'guest.stderr'), 'ranking_eligible': False}
    save(folder / 'process.json', status)
    if proc.returncode != 0 and not (stopped_after_completion and proc.returncode == -15):
        raise ValueError('QEMU process failed: ' + str(proc.returncode))
    verdict = validate((folder / 'guest.stdout').read_text(errors='replace'), mode, rounds, iterations)
    save(folder / 'verdict.json', verdict)
    return verdict


def csv_file(path, columns, rows):
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader(); writer.writerows(rows)


def summarize(output, runs):
    switches, timers, boots, legacy = [], [], [], []
    for mode, trials in runs.items():
        for index, trial in enumerate(trials, 1):
            hz = trial['meta']['frequency_hz']
            ns = lambda v: v * 1e9 / hz
            boots.append({'mode': mode, 'guest': index, 'elapsed_ns': ns(trial['boot']['elapsed_counts']),
                          'boundary': trial['boot']['boundary']})
            for r in trial['switches']:
                switches.append({'mode': mode, 'guest': index, 'workers': r['workers'], 'ectx': r['ectx'],
                    'handoffs': r['handoffs'], 'elapsed_counts': r['elapsed_counts'],
                    'ns_per_verified_handoff': ns(r['elapsed_counts']) / r['handoffs']})
            for r in trial['timers']:
                timers.append({'mode': mode, 'guest': index, **r,
                    'arm_ns': ns(r['arm_counts']), 'irq_handler_ns': ns(r['irq_handler_counts']),
                    'max_late_ns': ns(r['max_late_counts'])})
            for name, value in trial['legacy'].items():
                legacy.append({'mode': mode, 'guest': index, 'case': name, 'raw_counts': value,
                               'ns': ns(value), 'measurement_valid': value >= 0})
    for name, data in [('switches', switches), ('timers', timers), ('boot', boots), ('legacy-six', legacy)]:
        csv_file(output / (name + '.csv'), list(data[0]), data)
    receipt = {'schema': 1, 'pass': True, 'modes': list(runs), 'fresh_guests': sum(map(len, runs.values())),
        'new_board_measurements': 0, 'new_model_calls': 0, 'ranking_eligible': False,
        'scope': 'Native Tenon ARM64 cross-build and TCG functional validation. Guest timer elapsed counts are not CPU cycles or hardware real-time results.',
        'unmeasured': ['physical_reset_to_ready', 'board_performance_energy', 'Mortise_Linux_colocation',
                       'full_architectural_ISR_save_dispatch_restore', 'FreeRTOS_Zephyr_port_execution'],
        'files': {p.name: sha(p) for p in output.glob('*.csv')}}
    save(output / 'receipt.json', receipt)
    report(output, runs)
    return receipt


def report(output, runs):
    lines = ['# Tenon Prototype extension: simulation results', '',
        '**TCG functional validation only. These values are not board performance or EunoBench leaderboard inputs.**', '',
        'Fresh QEMU processes are independent simulation runs; iterations inside one guest are not independent experiments.', '',
        '| Mode | Guests | Entry-to-main median (ms) | Range (ms) |', '| --- | ---: | ---: | --- |']
    for mode, trials in runs.items():
        values = [t['boot']['elapsed_counts'] * 1000 / t['meta']['frequency_hz'] for t in trials]
        lines.append(f'| {mode} | {len(trials)} | {statistics.median(values):.6f} | {min(values):.6f}–{max(values):.6f} |')
    lines += ['', 'Boot boundary: first C-level ukplat_entry hook to first main timestamp; excludes earlier platform initialization and physical reset.', '',
        'Switch endpoint: first worker entry to final worker entry, divided by verified changes of worker ID. Includes loop and timestamp overhead; raw values are not baseline-subtracted.', '',
        'Timer workload: 1/10/20/50/100 native one-shot timers, 20 native ticks delay. Timers are armed in one masked section. Total arm cost and timer-handler entry-to-return time are separate metrics; the latter excludes architectural IRQ save/restore.', '',
        'Every timer must fire exactly once. Mode is checked against the resolved Kconfig and guest output. All counts use CNTVCT with CNTFRQ, not PMU cycles.', '',
        'ELF allocated sections include the new observer. They do not measure dynamic peak RAM. Legacy-six verdicts check native return status and output completeness; no claim of new independent behavioral qualification is made.', '',
        'See switches.csv, timers.csv, boot.csv, legacy-six.csv, each guest log/verdict, and each build identity/sections.json.', '']
    (output / 'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')
    svg_plot(output / 'switches.svg', runs, 'switch')
    svg_plot(output / 'timers.svg', runs, 'timer')


def seal(output):
    members = {str(p.relative_to(output)): sha(p) for p in output.rglob('*')
               if p.is_file() and p.name != 'evidence.json'}
    save(output / 'evidence.json', {'schema': 1, 'members': members,
        'scope': 'Self-consistency manifest, not an external signature or hardware attestation'})


def replay(source, output):
    if source == output or source in output.parents or output in source.parents:
        raise ValueError('Replay output must be new and separate from captured evidence')
    evidence = json.loads((source / 'evidence.json').read_text())
    for name, expected in evidence['members'].items():
        path = (source / name).resolve()
        if not path.is_relative_to(source) or not path.is_file() or sha(path) != expected:
            raise ValueError('Changed or missing evidence: ' + name)
    actual = {str(p.relative_to(source)) for p in source.rglob('*') if p.is_file() and p.name != 'evidence.json'}
    if actual != set(evidence['members']): raise ValueError('Unlisted/missing evidence member')
    plan = json.loads((source / 'plan.json').read_text())
    if plan['accelerator'] != 'tcg' or plan['ranking_eligible'] is not False:
        raise ValueError('Simulation cannot be promoted to hardware/leaderboard evidence')
    results = {}
    for mode in plan['modes']:
        build = source / mode / 'build'
        identity = json.loads((build / 'identity.json').read_text())
        if identity['mode'] != mode or identity['image_sha256'] != sha(build / 'runtime.elf') or identity['boot_image_sha256'] != sha(build / 'runtime.img') or identity['config_sha256'] != sha(build / 'resolved.config') or identity['source_manifest_sha256'] != sha(source / 'source-manifest.json') or identity['sections_sha256'] != sha(build / 'sections.json'):
            raise ValueError('Build identity mismatch')
        tickless = 'CONFIG_LIBTNSYSTICK_TICKLESS=y' in (build / 'resolved.config').read_text()
        if tickless != (mode == 'tickless'): raise ValueError('Resolved tick-mode mismatch')
        if elf_sections(build / 'runtime.elf') != json.loads((build / 'sections.json').read_text()):
            raise ValueError('ELF section replay differs')
        results[mode] = []
        for i in range(1, plan['runs'] + 1):
            guest = source / mode / f'guest-{i}'
            process = json.loads((guest / 'process.json').read_text())
            if process['image_sha256'] != sha(build / 'runtime.img') or process['stdout_sha256'] != sha(guest / 'guest.stdout') or process['stderr_sha256'] != sha(guest / 'guest.stderr') or process['fresh_process'] is not True or process['ranking_eligible'] is not False or process['argv'][process['argv'].index('-accel')+1] != 'tcg':
                raise ValueError('Guest process/raw-log binding mismatch')
            if process['returncode'] != 0 and not (process['stopped_after_completion'] and process['returncode'] == -15):
                raise ValueError('Failed guest process')
            verdict = validate((guest / 'guest.stdout').read_text(), mode, plan['rounds'], plan['legacy_iterations'])
            if verdict != json.loads((guest / 'verdict.json').read_text()): raise ValueError('Guest verdict replay differs')
            results[mode].append(verdict)
    output.mkdir(parents=True, exist_ok=False)
    receipt = summarize(output, results)
    for name, expected in receipt['files'].items():
        if sha(output / name) != sha(source / name): raise ValueError('Recomputed table differs: ' + name)
    save(output / 'replay.json', {'pass': True, 'new_guests': 0, 'new_board_measurements': 0,
        'source_evidence_sha256': sha(source / 'evidence.json'), 'recomputed_csv_files': list(receipt['files'])})
    return {'pass': True, 'new_guests': 0, 'recomputed_csv_files': list(receipt['files'])}


def export_capture(source, output):
    native_storage({'captured_evidence': source})
    export_root = Path('/mnt/e/learn/benchmark/output').resolve()
    if output == export_root or not output.is_relative_to(export_root):
        raise ValueError('Export destination must be a new directory inside ' + str(export_root))
    sidecar = output.with_name(output.name + '.export.json')
    if output.exists() or sidecar.exists(): raise ValueError('Export destination/receipt already exists')
    checks = Path.home() / 'eunobench/export-checks'
    checks.mkdir(parents=True, exist_ok=True)
    # Revalidate raw evidence before any Windows writes. No guest is active here.
    with tempfile.TemporaryDirectory(prefix='check-', dir=checks) as temp:
        replay(source, Path(temp) / 'replayed')
    expected = {str(p.relative_to(source)): sha(p) for p in source.rglob('*') if p.is_file()}
    if not json.loads((source / 'receipt.json').read_text()).get('pass'):
        raise ValueError('Only a completed successful capture may be exported')
    for p in source.rglob('*'):
        if p.is_symlink(): raise ValueError('Evidence export cannot follow symlinks')
    shutil.copytree(source, output)
    actual = {str(p.relative_to(output)): sha(p) for p in output.rglob('*') if p.is_file()}
    if actual != expected: raise ValueError('Post-copy hash verification failed')
    proof = {'pass': True, 'source': str(source), 'destination': str(output),
             'files_verified': len(actual), 'evidence_sha256': sha(source / 'evidence.json'),
             'copied_after_completion': True, 'new_guests': 0,
             'scope': 'Byte-identical post-run Windows export; canonical evidence remains in WSL'}
    save(sidecar, proof)
    return proof


def svg_plot(path, runs, metric):
    import html
    series = []
    for mode, trials in runs.items():
        for ectx in ([0, 1] if metric == 'switch' else [None]):
            points = []
            for n in (WORKERS if metric == 'switch' else TIMERS):
                values = []
                for t in trials:
                    for r in t['switches' if metric == 'switch' else 'timers']:
                        if r['workers' if metric == 'switch' else 'timers'] == n and (ectx is None or r['ectx'] == ectx):
                            raw = r['elapsed_counts'] / r['handoffs'] if metric == 'switch' else r['irq_handler_counts']
                            values.append(raw * 1e6 / t['meta']['frequency_hz'])
                points.append((n, statistics.median(values)))
            series.append((mode + (f' ectx={ectx}' if ectx is not None else ''), points))
    peak = max(y for _, ps in series for _, y in ps) * 1.15 or 1
    colors = ['#167c80', '#d07830', '#386eb0', '#ae4c75']
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="900" height="520" viewBox="0 0 900 520">',
        '<rect width="900" height="520" fill="white"/>',
        '<g font-family="sans-serif" font-size="14" fill="#243447">',
        f'<text x="70" y="30" font-size="20">{metric.title()} scaling — TCG FUNCTIONAL VALIDATION ONLY</text>',
        '<text x="70" y="53">Guest timer time; no hardware performance comparison</text>',
        '<path d="M70 80V430H650" fill="none" stroke="#788694"/>']
    for i in range(6):
        v = peak * i / 5; y = 430 - 330 * i / 5
        out += [f'<path d="M70 {y}H650" stroke="#e0e5ea"/>', f'<text x="8" y="{y+4}">{v:.1f}</text>']
    for i, (name, ps) in enumerate(series):
        coords = [(70+x/100*580, 430-y/peak*330) for x,y in ps]
        out.append(f'<polyline points="{" ".join(f"{x:.2f},{y:.2f}" for x,y in coords)}" stroke="{colors[i]}" fill="none" stroke-width="2"/>')
        for x,y in coords: out.append(f'<circle cx="{x}" cy="{y}" r="4" fill="{colors[i]}"/>')
        out.append(f'<text x="675" y="{110+i*28}" fill="{colors[i]}">{html.escape(name)}</text>')
    for n in (WORKERS if metric == 'switch' else TIMERS):
        out.append(f'<text x="{70+n/100*580-7}" y="452">{n}</text>')
    unit = 'microseconds / verified handoff' if metric == 'switch' else 'microseconds: observed timer-handler body total'
    out += [f'<text x="70" y="480">Y: {unit}</text>', f'<text x="70" y="502">X: {"participating workers (coordinator blocked)" if metric == "switch" else "native one-shot timers"}</text>', '</g></svg>']
    path.write_text('\n'.join(out), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('doctor')
    replay_parser = sub.add_parser('replay', help='Revalidate saved raw evidence and regenerate tables without building or running QEMU')
    replay_parser.add_argument('--input', type=Path, required=True)
    replay_parser.add_argument('--output', type=Path, required=True)
    export_parser = sub.add_parser('export', help='After completion, validate and copy evidence to Windows output')
    export_parser.add_argument('--input', type=Path, required=True)
    export_parser.add_argument('--output', type=Path, required=True)
    run = sub.add_parser('run')
    run.add_argument('--output', type=Path, required=True)
    run.add_argument('--runs', type=int, default=3)
    run.add_argument('--rounds', type=int, default=100)
    run.add_argument('--legacy-iterations', type=int, default=50)
    run.add_argument('--modes', choices=['fixed', 'tickless'], nargs='+', default=['fixed', 'tickless'])
    run.add_argument('--timeout', type=int, default=120)
    run.add_argument('--source-root', type=Path, help='Optional exact local mirror of artifact/third_party for faster repeated builds')
    run.add_argument('--work-base', type=Path, default=Path.home() / 'eunobench/prototype-builds',
                     help='Persistent Linux build directory (separate from the existing .venv)')
    args = parser.parse_args()
    if args.action == 'replay':
        print(json.dumps(replay(args.input.resolve(), args.output.resolve()), indent=2)); return
    if args.action == 'export':
        print(json.dumps(export_capture(args.input.resolve(), args.output.resolve()), indent=2)); return
    env = environment()
    if args.action == 'doctor': print(json.dumps(env, indent=2)); return
    if not 1 <= args.runs <= 100 or not 2 <= args.rounds <= 100000 or not 2 <= args.legacy_iterations <= 100000 or len(set(args.modes)) != len(args.modes):
        parser.error('Invalid/duplicate experiment parameters')
    output = args.output.resolve()
    storage = native_storage({'runner_source': HERE, 'artifact_source': ARTIFACT,
        'work_base': args.work_base, 'active_capture': output,
        'native_input_source': args.source_root or ARTIFACT / 'third_party'})
    output.mkdir(parents=True, exist_ok=False)
    save(output / 'environment.json', env)
    save(output / 'storage.json', storage)
    save(output / 'plan.json', {'schema': 1, 'modes': args.modes, 'runs': args.runs,
        'rounds': args.rounds, 'legacy_iterations': args.legacy_iterations, 'timeout': args.timeout,
        'accelerator': 'tcg', 'ranking_eligible': False})
    # Native Linux build tree avoids slow DrvFS compilation and source mutation.
    args.work_base.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='build-', dir=args.work_base))
    save(output / 'invocation.json', {'argv': sys.argv, 'workdir': str(work), 'output': str(output),
         'runner_sha256': sha(Path(__file__)), 'started_unix_s': time.time()})
    try:
        print('Staging supplied native sources into ' + str(work), flush=True)
        source, manifest = stage(work, args.rounds, args.legacy_iterations, args.source_root)
        save(output / 'source-manifest.json', manifest)
        save(output / 'source-lines.json', source_size(source))
        results = {}
        for mode in args.modes:
            print('Building native Tenon: ' + mode, flush=True)
            image = build(source, work, output, mode)
            results[mode] = []
            for i in range(1, args.runs + 1):
                print(f'Booting {mode} fresh guest {i}/{args.runs}', flush=True)
                results[mode].append(boot(image, output / mode / f'guest-{i}', mode, args.rounds, args.legacy_iterations, args.timeout))
        receipt = summarize(output, results)
        seal(output)
        print(json.dumps(receipt, indent=2), flush=True)
    except Exception as error:
        save(output / 'failure.json', {'pass': False, 'error': str(error), 'type': type(error).__name__, 'workdir': str(work), 'ranking_eligible': False})
        raise


if __name__ == '__main__':
    main()
