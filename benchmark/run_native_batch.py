"""Execute paper-version OS functional probes; keep original B1 scores separate."""
import argparse,hashlib,json,os,shutil,subprocess,sys,time
from pathlib import Path
if __package__:
    from .version_policy import PINS,TAGS,META,require_paper_version
    from .extended_protocol import validate_extended
    from .source_scope import capture_source
else:
    from version_policy import PINS,TAGS,META,require_paper_version
    from extended_protocol import validate_extended
    from source_scope import capture_source
BASE=Path.home()/'eunobench'
ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'benchmark/native'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,indent=2)+'\n')
def command(argv,out,name,env=None,timeout=300):
    start=time.monotonic()
    with (out/(name+'.stdout')).open('wb') as stdout,(out/(name+'.stderr')).open('wb') as stderr:
        p=subprocess.run(list(map(str,argv)),stdout=stdout,stderr=stderr,env=env,timeout=timeout)
    save(out/(name+'.json'),dict(argv=list(map(str,argv)),returncode=p.returncode,elapsed_s=time.monotonic()-start,
        environment={k:env[k] for k in ('IDF_PATH','IDF_TOOLS_PATH','IDF_PYTHON_ENV_PATH','IDF_SKIP_CHECK_SUBMODULES','ESP_ROM_ELF_DIR','ZEPHYR_BASE','ZEPHYR_TOOLCHAIN_VARIANT') if env and k in env},
        stdout_sha256=sha(out/(name+'.stdout')),stderr_sha256=sha(out/(name+'.stderr'))))
    if p.returncode:raise RuntimeError(name+' failed; see '+str(out/(name+'.stdout'))+' and .stderr')

def validate(text,tag,extended=False):
    if text.count(tag+'_DONE failures=0')!=1 or tag+'_FAIL' in text:raise ValueError('Missing or failed native completion')
    if text.count(tag+'_META '+META[tag])!=1:raise ValueError('Wrong OS/version metadata')
    result={}
    for group,grid,key in [('DISPATCH' if tag=='COS' else 'SWITCH',[2,10,20,50,100],'workers'),('TIMER',[1,10,20,50,100],'timers')]:
        rows=[]
        for line in text.splitlines():
            if not line.startswith(tag+'_'+group+' '):continue
            r=dict(token.split('=',1) for token in line.split()[1:])
            r={k:int(v) if v.lstrip('-').isdecimal() else v for k,v in r.items()}
            if r['errors']!=0:raise ValueError('Native progress/context errors')
            if group in ('SWITCH','DISPATCH'):
                if r['entries']!=r['workers']*100 or not r['workers']-1<=r['handoffs']<=r['entries']-1:raise ValueError('Worker progress mismatch')
                elapsed=r['elapsed_us'] if tag=='ROS' else r['elapsed_ns']
                if tag=='FOS' and r['same_worker_entries']+r['handoffs']!=r['entries']-1:raise ValueError('Changed transition accounting')
            else:
                if r['callbacks']!=r['timers']:raise ValueError('Missing timer callbacks')
                if r['context']!={'ZOS':'isr','ROS':'irq','COS':'owner_process','AOS':'timer_task','NOS':'signal_handler','FOS':'timer_service_task'}[tag]:raise ValueError('Changed native callback context')
                elapsed=r['arm_enqueue_ns'] if tag=='FOS' else r['arm_ns'] if tag in ('ZOS','AOS','NOS') else r['arm_us'] if tag=='ROS' else r['elapsed_ns']
            if not isinstance(elapsed,int) or elapsed<=0:raise ValueError('Invalid elapsed clock interval')
            rows.append(r)
        if [r[key] for r in rows]!=grid:raise ValueError('Missing/repeated parameter-grid cell')
        result[group]=rows
    if extended:result['EXTENDED']=validate_extended(text,tag)
    return result

def sections(image,out):
    from elftools.elf.elffile import ELFFile
    with image.open('rb') as f:
        elf=ELFFile(f)
        rows=[dict(name=s.name,bytes=s['sh_size'],type=s['sh_type']) for s in elf.iter_sections() if s['sh_flags']&2]
    save(out/'sections.json',dict(image_sha256=sha(image),sections=rows,
        scope='host-linked image; excludes dynamic allocation; not original ESP32 Flash footprint'))

def git_source(source,target,folder):
    commit=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    require_paper_version(dict(os=target,upstream_commit=commit))
    subprocess.run(['git','-C',str(source),'diff','--exit-code','HEAD','--'],check=True,stdout=subprocess.DEVNULL)
    save(folder/'source-identity.json',dict(upstream_commit=commit,tracked_source_clean=True))
    return commit

def run(args):
    out=args.output.resolve()
    if not all(p.resolve().is_relative_to(BASE.resolve()) for p in [ROOT,out]):raise ValueError('Keep source and active outputs in native Linux home')
    out.mkdir(parents=True,exist_ok=False);results=[]
    for target in args.targets:
        folder=out/target;folder.mkdir();print('Testing paper version: '+target,flush=True)
        try:
            source_app=APP/({'freertos':'freertos_idf_linux','zephyr':'zephyr_native','riot':'riot_native','contiki':'contiki_native','alios':'alios_linux','nuttx':'nuttx_sim'}[target])
            save(folder/'input-identity.json',dict(runner_sha256=sha(Path(__file__)),version_policy_sha256=sha(Path(__file__).with_name('version_policy.py')),
                application_files={str(p.relative_to(source_app)):sha(p) for p in source_app.rglob('*') if p.is_file()},
                common_observer_sha256=sha(APP/'common/euno_more.h')))
            env=dict(os.environ);source=getattr(args,target+'_root').resolve()
            if not source.is_relative_to(BASE.resolve()):raise ValueError('SDK must stay on native Linux filesystem')
            commit=PINS[target]
            if target=='alios':
                command([sys.executable,source_app/'build.py','--source',source,'--output',folder/'build'],folder,'build')
                image=folder/'build/alios-probe'
                shutil.copyfile(source/'source-identity.json',folder/'source-identity.json')
            elif target=='nuttx':
                command([sys.executable,source_app/'build.py','--source',source,'--apps',args.nuttx_apps,'--output',folder/'build'],folder,'build')
                image=folder/'build/nuttx/nuttx'
                shutil.copyfile(folder/'build/source-identity.json',folder/'source-identity.json')
            else:
                commit=git_source(source,target,folder)
                if target=='freertos':
                    app=folder/'application';shutil.copytree(source_app,app)
                    env.update(IDF_PATH=str(source),IDF_TOOLS_PATH=str(BASE/'tools/esp-idf-v5.2.5'),
                        ESP_ROM_ELF_DIR=str(source/'components/esp_rom'),IDF_PYTHON_ENV_PATH=str(Path(sys.executable).parent.parent),
                        IDF_SKIP_CHECK_SUBMODULES='1',PATH=str(Path(sys.executable).parent)+os.pathsep+env['PATH'])
                    command(['cmake','-S',app,'-B',folder/'build','-GNinja','-DIDF_TARGET=linux','-DPYTHON='+sys.executable,'-DEUNO_COMMON='+str(APP/'common')],folder,'configure',env)
                    command(['cmake','--build',folder/'build','-j4'],folder,'build',env)
                    image=folder/'build/euno_idf_probe.elf'
                elif target=='zephyr':
                    env.update(ZEPHYR_BASE=str(source),ZEPHYR_TOOLCHAIN_VARIANT='host')
                    command(['cmake','-S',source_app,'-B',folder/'build','-GNinja','-DBOARD=native_posix/native/64','-DZEPHYR_MODULES=','-DPython3_EXECUTABLE='+sys.executable],folder,'configure',env)
                    command(['cmake','--build',folder/'build','-j4'],folder,'build',env)
                    image=folder/'build/zephyr/zephyr.exe'
                elif target=='riot':
                    app=folder/'application';shutil.copytree(source_app,app)
                    command(['make','-C',app,'BOARD=native64','RIOTBASE='+str(source),'EUNO_COMMON='+str(APP/'common'),'-j4'],folder,'build',env)
                    images=list((app/'bin/native64').glob('*.elf'))
                    if len(images)!=1:raise ValueError('Expected one native RIOT executable')
                    image=images[0]
                else:
                    app=folder/'application';shutil.copytree(source_app,app)
                    command(['make','-C',app,'TARGET=native','CONTIKI='+str(source),'-j4'],folder,'build',env)
                    image=app/'build/native/euno-probes.native'
            trials=[]
            for i in range(1,4):
                command([image],folder,'run-'+str(i),env,timeout=45)
                trials.append(validate((folder/f'run-{i}.stdout').read_text(),TAGS[target],extended=True))
            save(folder/'trials.json',trials);sections(image,folder)
            capture_source(source,target,folder)
            result=dict(os=target,status='passed',upstream_commit=commit,paper_version_match=True,independent_processes=3,
                worker_records=15,timer_records=15,probe_profile='extended-v2',image_sha256=sha(image),scope='paper OS revision; new host simulator configuration; not original ESP32 B1')
            require_paper_version(result)
        except Exception as e:
            result=dict(os=target,status='blocked' if isinstance(e,FileNotFoundError) else 'failed',error=str(e))
        result['original_overall_eligible']=False
        save(folder/'receipt.json',result);results.append(result)
    for target in PINS:
        if target not in args.targets:results.append(dict(os=target,status='not_executed',reason='not selected',original_overall_eligible=False))
    receipt=dict(schema=2,subjects=results,selected_targets_pass=all(r['status']=='passed' for r in results[:len(args.targets)]),
        all_six_OS_families_complete=len(args.targets)==6 and all(r['status']=='passed' for r in results),
        original_eight_B1_deployments_complete=False,new_board_measurements=0,
        scope='Paper source versions; native functional reconstruction; excludes original ESP32 B1 score admission')
    save(out/'receipt.json',receipt)
    save(out/'evidence.json',{'members':{str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.name!='evidence.json'}})
    print(json.dumps(receipt,indent=2),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--targets',choices=list(PINS),nargs='+',default=list(PINS))
    for key,dirname in dict(freertos='esp-idf-v5.2.5',zephyr='zephyr-v3.7.0-mirror',riot='RIOT-dd06b372',contiki='contiki-ng-c02eedae',alios='alios-bacc-subset',nuttx='nuttx-12.2.1-release').items():
        p.add_argument('--'+key+'-root',type=Path,default=BASE/'upstream'/dirname)
    p.add_argument('--nuttx-apps',type=Path,default=BASE/'upstream/nuttx-apps-12.2.1')
    run(p.parse_args())

