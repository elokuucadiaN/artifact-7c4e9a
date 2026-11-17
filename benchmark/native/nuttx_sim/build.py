"""Rebuild the exact Apache release with a new native simulator configuration."""
import argparse,hashlib,json,shutil,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--apps',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
src=a.source.resolve();apps=a.apps.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
assert 'CONFIG_VERSION_STRING="12.2.1"' in (src/'.version').read_text()
assert 'CONFIG_VERSION_BUILD="148c631a2d"' in (src/'.version').read_text()
assert subprocess.check_output(['git','-C',str(apps),'write-tree'],text=True).strip()=='b30115d1758295c009b63d2a038df37779eb0b55'
subprocess.run(['git','-C',str(apps),'diff','--exit-code'],check=True)
base=Path.home()/'eunobench/upstream/nuttx-release'
archive=base/'apache-nuttx-12.2.1-complete.tar.gz'
expected=(base/'apache-nuttx-12.2.1.tar.gz.sha512').read_text().split()[0].lower()
assert hashlib.sha512(archive.read_bytes()).hexdigest()==expected
kernel=out/'nuttx';appdir=out/'apps'
kernel.mkdir()
subprocess.run(['tar','-xzf',archive,'--strip-components=1','-C',kernel],check=True)
shutil.copytree(apps,appdir,ignore=shutil.ignore_patterns('.git'))
shutil.copytree(Path(__file__).parent,appdir/'examples/euno')
shutil.copyfile(Path(__file__).parent.parent/'common/euno_more.h',appdir/'examples/euno/euno_more.h')
subprocess.run(['bash','tools/configure.sh','-l','-a','../apps','sim:ostest'],cwd=kernel,check=True)
lines=(kernel/'.config').read_text().splitlines()
lines=[s for s in lines if not s.startswith(('CONFIG_TESTING_OSTEST','CONFIG_MM_KASAN','CONFIG_MM_UBSAN','CONFIG_INIT_ENTRYPOINT='))]
lines+=['CONFIG_INIT_ENTRYPOINT="euno_main"','CONFIG_INIT_ENTRYNAME="euno"','CONFIG_INIT_PRIORITY=120','CONFIG_INIT_STACKSIZE=16384','CONFIG_EXAMPLES_EUNO=y','CONFIG_USEC_PER_TICK=1000','CONFIG_SIG_PREALLOC_IRQ_ACTIONS=128','CONFIG_PREALLOC_TIMERS=100']
(kernel/'.config').write_text('\n'.join(lines)+'\n')
subprocess.run(['make','olddefconfig'],cwd=kernel,check=True)
# Linker-only observation hook in this isolated build; SDK kernel algorithms unchanged.
defs=kernel/'Make.defs'
defs.write_text(defs.read_text()+'\nLDLINKFLAGS += --wrap=nx_start\nLDFLAGS += -Wl,--wrap=nx_start\n')
subprocess.run(['make','-j4'],cwd=kernel,check=True)
(out/'source-identity.json').write_text(json.dumps(dict(nuttx_version='12.2.1',nuttx_commit='148c631a2d252d4d59ae4cd90d1890d2daed381d',release_sha512=expected,apps_commit='86efbcbee77bc0a29af07807080f4804a37f46a3',apps_tree='b30115d1758295c009b63d2a038df37779eb0b55'),indent=2)+'\n')
