"""Paper-pinned Zephyr policy/mode reconstruction; never original ESP32 deployments."""
import argparse,json,os,shutil,subprocess,sys
from pathlib import Path
from .run_native_batch import APP,BASE,command,save,sha,sections,validate,git_source
POLICIES={'baseline':('DUMB','DUMB'),'qwen_policy':('MULTIQ','SCALABLE'),'autoos_policy':('SCALABLE','SCALABLE')}
def extra(text):
    def rows(tag):return [dict(s.split('=',1) for s in line.split()[1:]) for line in text.splitlines() if line.startswith(tag+' ')]
    irq=rows('ZOS_OFFLOAD');timers=rows('ZOS_ANNOUNCE')
    if len(irq)!=1 or irq[0]['verified']!='100' or irq[0]['errors']!='0':raise ValueError('IRQ context/progress failed')
    if not 0<int(irq[0]['entry_sum_ns'])<=int(irq[0]['roundtrip_sum_ns']):raise ValueError('IRQ interval failed')
    if [int(r['timers']) for r in timers]!=[1,10,20,50,100] or any(int(r['calls'])<1 or int(r['elapsed_ns'])<1 for r in timers):raise ValueError('Kernel announce window missing')
    return dict(irq=irq[0],timers=timers)
def run(output):
    output=output.resolve();assert output.is_relative_to(BASE)
    output.mkdir(exist_ok=False)
    source=BASE/'upstream/zephyr-v3.7.0-mirror';env=dict(os.environ,ZEPHYR_BASE=str(source),ZEPHYR_TOOLCHAIN_VARIANT='host')
    subjects=[]
    for policy,(scheduler,waitq) in POLICIES.items():
      for mode in ('fixed','tickless'):
        name=policy+'-'+mode;folder=output/name;folder.mkdir();print('Testing '+name,flush=True)
        git_source(source,'zephyr',folder)
        app=folder/'application';shutil.copytree(APP/'zephyr_native',app);shutil.copytree(APP/'common',folder/'common')
        conf=(app/'prj.conf').read_text().splitlines()
        conf=[s for s in conf if not s.startswith(('CONFIG_SYS_CLOCK_TICKS_PER_SEC=','CONFIG_TIMESLICE_SIZE=','CONFIG_TIMESLICE_PRIORITY='))]
        conf+=['CONFIG_SYS_CLOCK_TICKS_PER_SEC=100','CONFIG_TIMESLICE_SIZE=0','CONFIG_TIMESLICE_PRIORITY=0','CONFIG_SPEED_OPTIMIZATIONS=y','CONFIG_TEST=y','CONFIG_IRQ_OFFLOAD=y','CONFIG_TICKLESS_KERNEL='+('y' if mode=='tickless' else 'n'),'CONFIG_SCHED_'+scheduler+'=y','CONFIG_WAITQ_'+waitq+'=y']
        (app/'prj.conf').write_text('\n'.join(conf)+'\n')
        command(['cmake','-S',app,'-B',folder/'build','-GNinja','-DBOARD=native_posix/native/64','-DZEPHYR_MODULES=','-DEUNO_MATRIX=ON','-DPython3_EXECUTABLE='+sys.executable],folder,'configure',env)
        command(['cmake','--build',folder/'build','-j4'],folder,'build',env)
        resolved=(folder/'build/zephyr/.config').read_text()
        assert 'CONFIG_SCHED_'+scheduler+'=y' in resolved and 'CONFIG_WAITQ_'+waitq+'=y' in resolved
        assert ('CONFIG_TICKLESS_KERNEL=y' in resolved)==(mode=='tickless')
        assert 'CONFIG_SYS_CLOCK_TICKS_PER_SEC=100\n' in resolved and 'CONFIG_IRQ_OFFLOAD=y\n' in resolved
        trials=[];image=folder/'build/zephyr/zephyr.exe'
        for i in range(1,4):
          command([image],folder,'run-'+str(i),env,timeout=90)
          text=(folder/f'run-{i}.stdout').read_text();validate(text,'ZOS',extended=True);trials.append(extra(text))
        sections(image,folder)
        save(folder/'trials.json',trials)
        row=dict(id=name,policy=policy,scheduler=scheduler,waitq=waitq,mode=mode,tick_hz=100,independent_processes=3,status='passed',image_sha256=sha(image),resolved_config_sha256=sha(folder/'build/zephyr/.config'))
        save(folder/'receipt.json',row);subjects.append(row)
    save(output/'receipt.json',dict(subjects=subjects,pass_=True,independent_processes=18,scope='Native policy-only reconstruction, not complete Qwen/AutoOS saved builds; CPU times are host diagnostic intervals'))
    save(output/'evidence.json',{'members':{str(p.relative_to(output)):sha(p) for p in output.rglob('*') if p.is_file() and p.name!='evidence.json'}})
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.output)

