"""Admit actual reconstructed OS-family tests as separate diagnostic configurations."""
import json
import shutil
from pathlib import Path
from .adapters import record, sha
from .run_native_batch import validate
from .version_policy import require_paper_version,TAGS
from .extended_protocol import DEADLINE_CLOCKS

def collect(capture, output):
    capture=capture.resolve()
    expected=json.loads((capture/'evidence.json').read_text())['members']
    for name,digest in expected.items():
        path=(capture/name).resolve()
        if not path.is_relative_to(capture) or not path.is_file() or sha(path)!=digest:raise ValueError('Changed native evidence: '+name)
    saved=output/'evidence/native-batch'
    if saved.resolve()!=capture:shutil.copytree(capture,saved)
    receipts=json.loads((saved/'receipt.json').read_text())['subjects']
    rows,configs=[],[]
    for subject in receipts:
        if subject['status']!='passed':continue
        require_paper_version(subject)
        if subject.get('probe_profile','base-v1') not in ('base-v1','extended-v2'):raise ValueError('Unsupported native observer profile')
        key=subject['os'].lower()
        folder=saved/key
        name={'freertos':'FreeRTOS ESP-IDF 5.2.5 / official Linux reconstruction','zephyr':'Zephyr 3.7.0 / native_posix64 reconstruction','riot':'RIOT dd06b372 / native64 reconstruction','contiki':'Contiki-NG c02eedae / native cooperative reconstruction','alios':'AliOS bacc144b / Rhino Linux32 reconstruction','nuttx':'NuttX 12.2.1 / native simulator reconstruction'}[key]
        configs.append(dict(id=name,kind='deployment',scope='simulation_functional_validation',
            execution_model='cooperative_process' if key=='contiki' else 'threaded',
            platform=('x86 Linux32' if key=='alios' else 'x86_64')+' WSL host simulation; not ESP32 B1',original_leaderboard=False))
        bindings=dict(configuration_kind='reconstructed_simulator',input_identity_sha256=sha(folder/'input-identity.json'),
            probe_profile=subject.get('probe_profile','base-v1'),
            timer_observer='per-start deadline timestamp included in API window' if subject.get('probe_profile')=='extended-v2' else 'base-v1',
            callback_body_clock='ztimer_usec_1us_resolution' if key=='riot' else 'host_monotonic',
            upstream_commit=subject['upstream_commit'],image_sha256=subject['image_sha256'],
            callback_context={'freertos':'timer service task','zephyr':'ISR','riot':'IRQ','contiki':'owner process restored by ctimer event process','alios':'Rhino timer task','nuttx':'NuttX POSIX signal handler'}[key])
        def add(metric,value,unit,params,evidence,sample,static=False):
            rows.append(record(metric,value,unit,name,params,scope='simulation_functional_validation',sample=sample,
                kind='static_build' if static else 'fresh_process',statistic='static' if static else 'per_process',
                evidence=evidence,root=output,platform=configs[-1]['platform'],bindings=bindings))
        for i in range(1,4):
            raw=folder/f'run-{i}.stdout'
            text=raw.read_text()
            facts=validate(text,TAGS[key],extended=subject.get('probe_profile')=='extended-v2');switches,timers=facts['DISPATCH' if key=='contiki' else 'SWITCH'],facts['TIMER']
            if 'EXTENDED' in facts:
                ext=facts['EXTENDED'];boot=ext['BOOT']
                add('boot.native_entry_to_app',boot['elapsed_ns'],'ns',dict(entry=boot['entry'],application=boot['end']),raw,f'process-{i}')
                if 'PREEMPT' in ext:
                    pre=ext['PREEMPT'];ping=ext['PINGPONG']
                    add('scheduler.semaphore_wakeup_entry',pre['sum_ns']/pre['rounds'],'ns/wakeup',dict(rounds=100),raw,f'process-{i}')
                    add('ipc.semaphore_pingpong',ping['elapsed_ns']/ping['rounds'],'ns/roundtrip',dict(rounds=100,priority_relation='higher_peer'),raw,f'process-{i}')
                for r in ext['TIMER']:
                    for metric,field in [('timer.requested_deadline_offset','max_offset_ns'),('timer.callback_body_window','callback_body_ns')]:
                        params=dict(timers=r['timers'],delay_ms=20)
                        if metric=='timer.requested_deadline_offset':params['deadline_clock']=r['deadline_clock']
                        add(metric,r[field],'ns',params,raw,f'process-{i}')
            for r in switches:
                elapsed=r['elapsed_us']*1000 if key=='riot' else r['elapsed_ns']
                add('scheduler.cooperative_dispatch_scale' if key=='contiki' else 'scheduler.switch_scale',elapsed/r['handoffs'],'ns/handoff',
                    dict(workers=r['workers'],context_profile='native-default',rounds=100),raw,f'process-{i}')
            for r in timers:
                elapsed=r['arm_enqueue_ns'] if key=='freertos' else r['arm_ns'] if key in ('zephyr','alios','nuttx') else r['elapsed_ns'] if key=='contiki' else r['arm_us']*1000
                add('timer.start_api_window',elapsed,'ns',dict(timers=r['timers'],delay_ms=20),raw,f'process-{i}')
        resource=folder/'sections.json'
        sections=json.loads(resource.read_text())['sections']
        # ELF may contain multiple section headers with the same name (RIOT's
        # native linker emits two .rodata headers). Preserve raw headers in the
        # evidence and sum by name for this contract, rather than duplicate a sample.
        named={}
        for s in sections:named[s['name']]=named.get(s['name'],0)+s['bytes']
        for name_,size in named.items():add('image.section_bytes',size,'byte',{'section':name_},resource,'linked-image',True)
        add('image.allocated_bytes',sum(s['bytes'] for s in sections),'byte',{},resource,'linked-image',True)
        if (folder/'source-scope.json').is_file():
            from .source_scope import verify_source
            component,totals=verify_source(folder,key)
            for language,value in totals.items():
                add('source.physical_lines',value,'line',dict(component=component,language=language),folder/'source-scope.json','source-tree',True)
    return rows,configs

