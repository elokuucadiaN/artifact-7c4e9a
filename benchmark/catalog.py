"""Cross-OS measurement contracts. No Tenon paper value is an input measurement."""

def metric(key, title, group, unit, reference, boundary, parameters=(), overall=False, origin='new'):
    return dict(id=key, title=title, group=group, unit=unit, reference=reference,
                boundary=boundary, parameters=list(parameters), in_original_overall=overall,
                origin=origin, direction='higher' if key == 'communication.udp' else 'lower')

METRICS = [
    metric('task.response', 'Common-task response', 'Task', 'us', 'EunoBench §3.1–3.2',
           'Submission through verified completion; excludes earlier release/ingress waiting', ['phase'], True, 'existing'),
    metric('communication.udp', 'UDP transactions', 'Communication', 'transaction/s', 'EunoBench §3.2',
           'Complete correct UDP request/reply transaction', (), True, 'existing'),
    metric('energy.per_job', 'Board energy per job', 'Energy', 'J/job', 'EunoBench Eq.1',
           'Integrated whole-board input energy divided by verified foreground completions', ['phase'], True, 'existing'),
    metric('memory.peak_allocated', 'Peak allocated RAM', 'Memory', 'byte', 'EunoBench §3.2',
           'Maximum simultaneous observer-inclusive allocated capacity over declared lifecycle', (), True, 'existing'),
    metric('image.section_bytes', 'Linked section size', 'Footprint', 'byte', 'TenonOS §5.1.1 Table 1',
           'Named SHF_ALLOC section in the actual linked ELF; no runtime heap/stack inference', ['section']),
    metric('image.allocated_bytes', 'Allocated ELF section total', 'Footprint', 'byte', 'TenonOS §5.1.1 Table 1',
           'Sum of SHF_ALLOC section sizes, including the observer; not dynamic peak RAM'),
    metric('boot.entry_to_main', 'Kernel initialization interval', 'Startup', 'ns', 'TenonOS §5.1.2 Table 3 (partial boundary)',
           'First instrumented native kernel C entry to first application/main timestamp; exact entry symbols declared in bindings; excludes physical reset'),
    metric('boot.native_entry_to_app', 'Native simulator initialization interval', 'Startup', 'ns', 'TenonOS §5.1.2 inspired; port-specific C entry boundary',
           'Link-wrapped native SDK entry (or explicit pre-kernel-init statement) to first benchmark application entry; excludes ELF loader and physical reset; differing entry symbols prevent a common hardware-startup interpretation', ['entry','application']),
    metric('scheduler.semaphore_wakeup_entry', 'Semaphore release to higher-priority entry', 'Real-time', 'ns/wakeup', 'TenonOS §5.2.1 Table 5 inspired new endpoint pair',
           'Before native semaphore release to first timestamp in the awakened higher-priority thread, mean of 100 rounds; sequence must advance before release API returns; includes timestamp overhead', ['rounds']),
    metric('ipc.semaphore_pingpong', 'Native semaphore roundtrip', 'Real-time', 'ns/roundtrip', 'TenonOS §5.3 Table 6 inspired new protocol',
           'Total 100 native semaphore request/ack roundtrips divided by 100 with a higher-priority peer; includes four semaphore API calls and native scheduling per round; no switch-baseline subtraction', ['rounds','priority_relation']),
    metric('scheduler.switch_scale', 'Verified worker handoff', 'Real-time', 'ns/handoff', 'TenonOS §5.2.1 Table 4 inspired',
           'First to last worker entry / verified worker-ID changes; coordinator blocked; includes observer overhead', ['workers', 'context_profile', 'rounds']),
    metric('scheduler.cooperative_dispatch_scale', 'Cooperative process dispatch window', 'Real-time', 'ns/handoff', 'TenonOS scaling inspired; separate cooperative-model contract',
           'Poll release through completion of N native cooperative processes / observed process-ID changes; includes native main-loop select and observer overhead; not stackful context switching', ['workers', 'context_profile', 'rounds']),
    metric('scheduler.legacy_switch', 'Two-task switching', 'Real-time', 'ns', 'TenonOS six-case body',
           'Original two-task switch loop average with original baseline arithmetic', ['iterations'], origin='existing_body_new_counter_profile'),
    metric('scheduler.legacy_multi_switch', 'Legacy multi-task switching', 'Real-time', 'ns', 'TenonOS six-case body',
           'Original 50-worker plus head task loop average; not the parameterized worker protocol', ['iterations'], origin='existing_body_new_counter_profile'),
    metric('scheduler.preempt_roundtrip', 'Legacy preemption loop', 'Real-time', 'ns', 'TenonOS §5.2.1 Table 5 inspired',
           'Original resume-high-priority / suspend loop arithmetic; not a new isolated wakeup timestamp pair', ['iterations'], origin='existing_body_new_counter_profile'),
    metric('ipc.semaphore_shuffle', 'Semaphore shuffle', 'Real-time', 'ns', 'TenonOS §5.3 Table 6 inspired',
           'Original semaphore lock/yield/unlock/yield loop with switch-only baseline deduction', ['iterations'], origin='existing_body_new_counter_profile'),
    metric('interrupt.trigger_to_isr', 'IRQ entry response', 'Real-time', 'ns', 'TenonOS §5.2.1 Figure 8 (different boundary)',
           'Before native software IRQ trigger to timestamp inside ISR; excludes return/context restoration', origin='existing_body_new_counter_profile'),
    metric('timer.interference_offset', 'Wakeup deviation under IRQ masking', 'Real-time', 'ns', 'TenonOS original timer-offset body',
           'Actual sleeping interval minus requested interval under interrupt masking; signed raw deviation retained', ['iterations'], origin='existing_body_new_counter_profile'),
    metric('timer.arm_cost', 'Native timer arm cost', 'Timer scaling', 'ns', 'TenonOS §5.2.2 Figure 9 inspired new protocol',
           'Total initialize/start cost for N native one-shot timers inside one masked section', ['timers', 'delay_ticks']),
    metric('timer.start_api_window', 'Preallocated timer start API window', 'Timer scaling', 'ns', 'TenonOS §5.2.2 Figure 9 inspired cross-OS protocol',
           'Elapsed window of N native start API calls on preallocated one-shots; includes native dispatch/preemption; asynchronous command enqueue and direct insertion are explicitly attributed', ['timers', 'delay_ms']),
    metric('timer.requested_deadline_offset', 'Maximum requested-deadline deviation', 'Timer scaling', 'ns', 'TenonOS timer scaling auxiliary endpoint',
           'Maximum signed first native callback timestamp minus (native OS clock immediately before individual start API + requested 20 ms), converted to ns in the same native clock domain; includes enqueue delay, tick quantization and dispatch; not deviation from an independently observed internal expiry', ['timers','delay_ms','deadline_clock']),
    metric('timer.callback_body_window', 'Observed callback C-body total', 'Timer scaling', 'ns', 'TenonOS §5.2.2 inspired; smaller explicit boundary',
           'Sum of entry-to-final-timestamp windows in all N benchmark C callbacks, including validation/notification and clock overhead; excludes the OS timer handler outside callbacks and architectural IRQ save/restore', ['timers','delay_ms']),
    metric('timer.handler_window', 'Timer handler window cost', 'Timer scaling', 'ns', 'TenonOS §5.2.2 Figure 9 inspired new protocol',
           'Accumulated C timer IRQ-handler entry-to-return intervals until completion; excludes assembly entry/return', ['timers', 'delay_ticks']),
    metric('timer.kernel_announce_window','Kernel tick/timeout processing window','Timer scaling','ns','TenonOS Figure 9 inspired explicit kernel boundary',
           'Sum of wrapped Zephyr sys_clock_announce entry-to-return host intervals from timer start to all callbacks completed; includes timeout dispatch and instrumented callbacks, excludes driver and assembly IRQ entry/return', ['timers','mode']),
    metric('interrupt.native_offload_entry','Native software IRQ API to ISR entry','Real-time','ns/interrupt','TenonOS Figure 8 inspired partial boundary',
           'Mean before irq_offload API to first timestamp in native ISR; verifies native ISR context; includes simulator API overhead, not isolated hardware context save', ['rounds']),
    metric('interrupt.native_offload_roundtrip','Native software IRQ API roundtrip','Real-time','ns/interrupt','TenonOS Figure 8 inspired aggregate boundary',
           'Mean before irq_offload through its return, 100 verified ISR calls; includes native API and callback timestamps; not a save/dispatch/restore phase decomposition', ['rounds']),
    metric('image.linker_region_bytes','Linked firmware memory-region use','Footprint','byte','TenonOS Table 1 inspired target ELF descriptor',
           'Actual linker-reported FLASH/RAM used bytes for declared firmware target, includes benchmark/observer; not runtime peak allocation or original ESP32 footprint', ['region']),
    metric('timer.max_lateness', 'Maximum callback lateness', 'Timer scaling', 'ns', 'Auxiliary validation of timer scaling',
           'Maximum callback timestamp minus each native timer actual deadline, one value per fresh guest', ['timers', 'delay_ticks']),
    metric('source.physical_lines', 'Source physical code lines', 'Footprint', 'line', 'TenonOS §5.1.1 Tables 1–2 (different source scope)',
           'Declared distributed C/assembly source scope: nonblank physical lines excluding C-style comments; includes tests/unlinked features if declared, not TCB', ['component', 'language'])
]
BY_ID = {m['id']: m for m in METRICS}


def validate_record(row):
    import math
    contract = BY_ID[row['metric_id']]
    if row['unit'] != contract['unit'] or set(row['parameters']) != set(contract['parameters']):
        raise ValueError('Metric unit/parameter contract mismatch: ' + row['metric_id'])
    if type(row['value']) not in (int, float) or not math.isfinite(row['value']):
        raise ValueError('Nonfinite/non-numeric measurement')
    if row['execution_scope'] != 'physical_board' and row['comparison_eligible']:
        raise ValueError('Simulation/static records cannot become board performance evidence')
    if row['overall_eligible'] and not contract['in_original_overall']:
        raise ValueError('New metric cannot silently change the frozen Overall policy')
    if row['sample_kind'] == 'static_build' and row['statistic'] != 'static':
        raise ValueError('Static resource descriptor cannot add runtime trials')
    if not row['evidence'] or not row['evidence_sha256']:
        raise ValueError('Unbound measurement evidence')
