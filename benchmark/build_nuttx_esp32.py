"""Build the pinned NuttX 12.2.1 release for a single-core ESP32-WROOM-32."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from .version_policy import PINS


def build(output):
    home = Path.home() / 'eunobench'
    upstream = home / 'upstream'
    release = upstream / 'nuttx-release'
    archive = release / 'apache-nuttx-12.2.1-complete.tar.gz'
    digest = (release / 'apache-nuttx-12.2.1.tar.gz.sha512').read_text().split()[0].lower()
    if hashlib.sha512(archive.read_bytes()).hexdigest() != digest:
        raise ValueError('NuttX release checksum mismatch')
    apps = upstream / 'nuttx-apps-12.2.1'
    apps_tree = 'b30115d1758295c009b63d2a038df37779eb0b55'
    if subprocess.check_output(['git', '-C', apps, 'write-tree'], text=True).strip() != apps_tree:
        raise ValueError('NuttX apps tree differs from the pinned release')
    subprocess.run(['git', '-C', apps, 'diff', '--exit-code'], check=True)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    kernel, appdir = output / 'nuttx', output / 'apps'
    native = Path(__file__).resolve().parent / 'native'
    kernel.mkdir(exist_ok=True)
    if not (kernel / '.version').exists():
        subprocess.run(['tar', '-xzf', archive, '--strip-components=1', '-C', kernel], check=True)
    shutil.copytree(apps, appdir, ignore=shutil.ignore_patterns('.git'), dirs_exist_ok=True)
    example = appdir / 'examples/euno'
    shutil.copytree(native / 'nuttx_sim', example, dirs_exist_ok=True)
    shutil.copyfile(native / 'common/euno_more.h', example / 'euno_more.h')
    env = os.environ.copy()
    gcc = home / 'tools/esp-idf-v5.2.5/tools/xtensa-esp-elf/esp-13.2.0_20230928/xtensa-esp-elf/bin'
    env['PATH'] = f'{gcc}:{env["PATH"]}'
    with (output / 'build.log').open('w') as log:
        def run(*argv):
            subprocess.run(argv, cwd=kernel, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        run('bash', 'tools/configure.sh', '-l', '-a', '../apps', 'esp32-devkitc:nsh')
        settings = {
            'ARCH_CHIP_ESP32WROVER': 'n', 'ARCH_CHIP_ESP32WROOM32': 'y',
            'SYSTEM_NSH': 'n', 'BUILTIN': 'n', 'INIT_ENTRYPOINT': '"euno_main"',
            'INIT_ENTRYNAME': '"euno"', 'INIT_PRIORITY': '120', 'INIT_STACKSIZE': '4096',
            'EXAMPLES_EUNO': 'y', 'USEC_PER_TICK': '10000', 'MAX_TASKS': '128',
            'SIG_PREALLOC_IRQ_ACTIONS': '128', 'PREALLOC_TIMERS': '100',
            'DEBUG_FEATURES': 'y', 'DEBUG_ASSERTIONS': 'y',
            'SCHED_HPWORK': 'y', 'LIBC_LONG_LONG': 'y',
        }
        config = kernel / '.config'
        with config.open('a') as handle:
            for key, value in settings.items():
                handle.write(f'CONFIG_{key}={value}\n')
        run('make', 'olddefconfig')
        run('make', '-j4')
    (output / 'source-identity.json').write_text(json.dumps(dict(
        nuttx_version='12.2.1', nuttx_commit=PINS['nuttx'], release_sha512=digest,
        apps_tree=apps_tree,
    ), indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    build(parser.parse_args().output)
