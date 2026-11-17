"""Build pinned ARM firmware and verify fresh QEMU guests; no hardware cycle claim."""
import argparse,json,os,selectors,shutil,subprocess,sys,time
from pathlib import Path
from .run_native_batch import APP,BASE,command,git_source,save,sha,sections
def run(out):
 out=out.resolve();assert out.is_relative_to(BASE);out.mkdir(exist_ok=True)
 source=BASE/'upstream/zephyr-v3.7.0-mirror';cmsis=BASE/'upstream/cmsis'
 git_source(source,'zephyr',out)
 pin=subprocess.check_output(['git','-C',str(cmsis),'rev-parse','HEAD'],text=True).strip()
 assert pin=='4b96cbb174678dcd3ca86e11e1f24bc5f8726da0'
 subprocess.run(['git','-C',str(cmsis),'diff','--exit-code','HEAD'],check=True)
 env=dict(os.environ,ZEPHYR_BASE=str(source),ZEPHYR_TOOLCHAIN_VARIANT='cross-compile',CROSS_COMPILE='/usr/bin/arm-none-eabi-')
 command(['cmake','-S',APP/'zephyr_qemu','-B',out/'build-final','-GNinja','-DBOARD=mps2/an385','-DZEPHYR_MODULES='+str(cmsis),'-DPython3_EXECUTABLE='+sys.executable],out,'configure-verified',env)
 command(['cmake','--build',out/'build-final','--clean-first','-j4'],out,'build-verified',env)
 image=out/'build-final/zephyr/zephyr.elf';sections(image,out)
 argv=['qemu-system-arm','-machine','mps2-an385','-cpu','cortex-m3','-nographic','-monitor','none','-serial','stdio','-kernel',str(image)]
 for i in range(1,4):
  data=b'';start=time.monotonic();p=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  selector=selectors.DefaultSelector();selector.register(p.stdout,selectors.EVENT_READ)
  try:
   while time.monotonic()-start<10:
    for key,_ in selector.select(.2):
     chunk=os.read(key.fd,4096)
     if chunk:data+=chunk
    if b'QOS_DONE irqs=100 callbacks=1 errors=0' in data and data.endswith(b'\n'):break
    if p.poll() is not None:break
  finally:
   p.terminate();p.wait(timeout=5);selector.close()
  (out/f'guest-{i}.stdout').write_bytes(data)
  assert data.count(b'QOS_DONE irqs=100 callbacks=1 errors=0')==1 and b'ASSERTION FAIL' not in data,data.decode(errors='replace')
  save(out/f'guest-{i}.json',dict(argv=argv,verified_marker=True,termination='controlled SIGTERM after complete marker',returncode=p.returncode,stdout_sha256=sha(out/f'guest-{i}.stdout')))
 shutil.copytree(APP/'zephyr_qemu',out/'application',dirs_exist_ok=True)
 save(out/'receipt.json',dict(pass_=True,os='Zephyr',version='3.7.0',cmsis_commit=pin,independent_guests=3,image_sha256=sha(image),board='mps2/an385',scope='ARM QEMU IRQ-entry/return and timer functional checks; firmware footprint; not original ESP32 or physical cycles'))
 save(out/'evidence.json',{'members':{str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.name!='evidence.json'}})
 print('ARM QEMU: 3 guests passed',flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.output)
