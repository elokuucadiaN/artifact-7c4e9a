"""Build official pinned Rhino/Linux sources with one glibc symbol compatibility rename."""
import argparse,hashlib,json,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
src=a.source.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
identity=json.loads((src/'source-identity.json').read_text())
assert identity==json.loads(Path(__file__).with_name('source-files.json').read_text())
assert identity['commit']=='bacc144bdc5df8fe8e302e3732675a920aa40bc5'
for row in identity['files']:
    data=(src/row['path']).read_bytes()
    assert hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==row['sha'],row['path']
original=src/'platform/arch/linux/cpu_impl.c'
patched=out/'cpu_impl-glibc.c'
patched.write_text(original.read_text().replace('gettid(', 'euno_private_gettid('))
(out/'compatibility.json').write_text(json.dumps(dict(change='Rename private gettid to euno_private_gettid to avoid glibc 2.35 declaration conflict; no scheduler algorithm changes',upstream=str(original),original_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),patched_sha256=hashlib.sha256(patched.read_bytes()).hexdigest()),indent=2)+'\n')
includes=['include','kernel/rhino/include','platform/arch/linux/include','board/linuxhost']
defines=['OSAL_RHINO','RHINO_CONFIG_CPU_NUM=1','RHINO_CONFIG_SYS_STATS=0','RHINO_CONFIG_HW_COUNT=0','RHINO_CONFIG_MM_DEBUG=0','RHINO_CONFIG_TICKS_PER_SECOND=1000','RHINO_CONFIG_TIMER_MSG_NUM=128']
sources=sorted(src/r['path'] for r in identity['files'] if r['path'].startswith('kernel/rhino/') and r['path'].endswith('.c') and not r['path'].endswith('k_mm_debug.c'))+[patched,src/'platform/mcu/linux/soc/hook_impl.c',src/'platform/mcu/linux/soc/soc_impl.c',Path(__file__).with_name('main.c')]
cmd=['gcc','-m32','-std=gnu11','-O2','-g','-fno-pie','-no-pie','-fno-strict-aliasing','-isystem','/usr/include/x86_64-linux-gnu','-I'+str(Path(__file__).parent.parent/'common')]+['-D'+s for s in defines]+['-I'+str(src/s) for s in includes]+list(map(str,sources))+['-pthread','-lrt','-o',str(out/'alios-probe')]
(out/'compile-argv.json').write_text(json.dumps(cmd,indent=2)+'\n')
subprocess.run(cmd,check=True)
