import json,shutil,re
from .adapters import record,sha
from .run_native_batch import validate
from .run_zephyr_matrix import extra,POLICIES
from .version_policy import PINS
def collect(capture,output,kind='matrix'):
    capture=capture.resolve();manifest=json.loads((capture/'evidence.json').read_text())['members']
    for name,digest in manifest.items():
        path=(capture/name).resolve()
        if not path.is_relative_to(capture) or not path.is_file() or sha(path)!=digest:raise ValueError('Changed supplemental evidence '+name)
    saved=output/'evidence'/('zephyr-matrix' if kind=='matrix' else 'arm-qemu');shutil.copytree(capture,saved)
    rows=[];configs=[]
    def add(metric,value,unit,params,evidence,sample,static=False):
        rows.append(record(metric,value,unit,name,params,scope=scope,sample=sample,kind='static_build' if static else 'fresh_process',statistic='static' if static else 'per_process',evidence=evidence,root=output,platform=platform,bindings=bindings))
    if kind=='qemu':
        receipt=json.loads((saved/'receipt.json').read_text());assert receipt['independent_guests']==3
        assert json.loads((saved/'source-identity.json').read_text())['upstream_commit']==PINS['zephyr']
        for i in range(1,4):
            text=(saved/f'guest-{i}.stdout').read_text();assert text.count('QOS_DONE irqs=100 callbacks=1 errors=0')==1
        name='Zephyr 3.7.0 / ARM mps2 QEMU firmware';scope='cross_compiled_firmware';platform='ARM Cortex-M3 mps2/an385, QEMU; not ESP32'
        bindings=dict(image_sha256=receipt['image_sha256'],cmsis_commit=receipt['cmsis_commit'],upstream_commit=PINS['zephyr'])
        configs.append(dict(id=name,kind='deployment',scope=scope,platform=platform,original_leaderboard=False))
        sections=json.loads((saved/'sections.json').read_text())['sections']
        for section in sections:add('image.section_bytes',section['bytes'],'byte',dict(section=section['name']),saved/'sections.json','linked-image',True)
        add('image.allocated_bytes',sum(s['bytes'] for s in sections),'byte',{},saved/'sections.json','linked-image',True)
        log=saved/'build-verified.stdout';text=log.read_text()
        for region in ('FLASH','RAM'):
            value=int(re.search(region+r':\s*(\d+) B',text)[1]);add('image.linker_region_bytes',value,'byte',dict(region=region),log,'linked-image',True)
        return rows,configs
    receipt=json.loads((saved/'receipt.json').read_text());assert len(receipt['subjects'])==6
    assert {(s['policy'],s['mode']) for s in receipt['subjects']}=={(p,m) for p in POLICIES for m in ('fixed','tickless')}
    for subject in receipt['subjects']:
        folder=saved/subject['id'];policy=subject['policy'];mode=subject['mode']
        assert json.loads((folder/'source-identity.json').read_text())['upstream_commit']==PINS['zephyr']
        config=folder/'build/zephyr/.config';text=config.read_text()
        assert sha(config)==subject['resolved_config_sha256']
        assert ('CONFIG_TICKLESS_KERNEL=y' in text)==(mode=='tickless') and 'CONFIG_SYS_CLOCK_TICKS_PER_SEC=100\n' in text
        scheduler,waitq=POLICIES[policy]
        assert (subject['scheduler'],subject['waitq'])==(scheduler,waitq)
        for flag in ['CONFIG_SCHED_'+scheduler+'=y','CONFIG_WAITQ_'+waitq+'=y','CONFIG_TIMESLICE_SIZE=0','CONFIG_TIMESLICE_PRIORITY=0','CONFIG_IRQ_OFFLOAD=y','CONFIG_TEST=y','CONFIG_SPEED_OPTIMIZATIONS=y']:
            assert flag+'\n' in text,flag
        name=f'Zephyr 3.7.0 / {policy} {mode} 100Hz policy reconstruction';scope='simulation_functional_validation';platform='native_posix64 WSL; policy-only, not original saved ESP32 configuration'
        bindings=dict(image_sha256=subject['image_sha256'],resolved_config_sha256=sha(config),upstream_commit=PINS['zephyr'],scheduler=subject['scheduler'],waitq=subject['waitq'],tick_hz=100,mode=mode,observer='kernel announce and native software IRQ probes')
        configs.append(dict(id=name,kind='deployment',scope=scope,execution_model='threaded',platform=platform,original_leaderboard=False))
        for i in range(1,4):
            raw=folder/f'run-{i}.stdout';text=raw.read_text();facts=validate(text,'ZOS',extended=True);ext=extra(text);sample=f'process-{i}'
            for r in facts['TIMER']:
                add('timer.start_api_window',r['arm_ns'],'ns',dict(timers=r['timers'],delay_ms=20),raw,sample)
                add('timer.requested_deadline_offset',r['max_offset_ns'],'ns',dict(timers=r['timers'],delay_ms=20,deadline_clock=r['deadline_clock']),raw,sample)
                add('timer.callback_body_window',r['callback_body_ns'],'ns',dict(timers=r['timers'],delay_ms=20),raw,sample)
            for r in ext['timers']:add('timer.kernel_announce_window',int(r['elapsed_ns']),'ns',dict(timers=int(r['timers']),mode=mode),raw,sample)
            r=ext['irq']
            for metric,field in [('interrupt.native_offload_entry','entry_sum_ns'),('interrupt.native_offload_roundtrip','roundtrip_sum_ns')]:add(metric,int(r[field])/100,'ns/interrupt',dict(rounds=100),raw,sample)
            for r in facts['SWITCH']:add('scheduler.switch_scale',r['elapsed_ns']/r['handoffs'],'ns/handoff',dict(workers=r['workers'],context_profile='native-default',rounds=100),raw,sample)
        resource=folder/'sections.json';sections=json.loads(resource.read_text())['sections']
        for section in sections:add('image.section_bytes',section['bytes'],'byte',dict(section=section['name']),resource,'linked-image',True)
        add('image.allocated_bytes',sum(s['bytes'] for s in sections),'byte',{},resource,'linked-image',True)
    return rows,configs
