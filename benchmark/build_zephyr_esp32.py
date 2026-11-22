"""Build six ESP32 policy/tick variants using the paper-pinned Zephyr sources."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .version_policy import PINS, ZEPHYR_POLICIES


def build(output):
    home = Path.home() / 'eunobench'
    upstream = home / 'upstream'
    zephyr = upstream / 'zephyr-v3.7.0-mirror'
    hal = upstream / 'hal_espressif-board'
    xtensa = upstream / 'hal_xtensa'
    toolchain = home / 'tools/esp-idf-v5.2.5/tools/xtensa-esp-elf/esp-13.2.0_20230928/xtensa-esp-elf/bin'
    assert subprocess.check_output(['git', '-C', zephyr, 'rev-parse', 'HEAD'], text=True).strip() == PINS['zephyr']
    assert subprocess.check_output(['git', '-C', hal, 'rev-parse', 'HEAD'], text=True).strip() == '87e7902d7184a8280b4d13bce79801a723f4ddd8'
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    include_root = output / 'core-isa'
    include_root.joinpath('zephyr/soc').mkdir(parents=True, exist_ok=True)
    link = include_root / 'zephyr/soc/esp32'
    if not link.exists():
        link.symlink_to(hal / 'components/xtensa/esp32/include', target_is_directory=True)
    app = Path(__file__).resolve().parent / 'native/zephyr_native'
    env = dict(os.environ, ZEPHYR_BASE=str(zephyr), ZEPHYR_TOOLCHAIN_VARIANT='cross-compile',
               CROSS_COMPILE=str(toolchain / 'xtensa-esp32-elf-'))
    summary = []
    for name, (scheduler, wait_queue) in ZEPHYR_POLICIES.items():
        for mode, tickless in [('fixed', 'n'), ('tickless', 'y')]:
            name_mode = f'{name}-{mode}'
            folder = output / name_mode
            folder.mkdir(exist_ok=True)
            fragment = folder / 'probe.conf'
            fragment.write_text('\n'.join([
                'CONFIG_MAIN_STACK_SIZE=4096', 'CONFIG_HEAP_MEM_POOL_SIZE=8192',
                'CONFIG_NUM_PREEMPT_PRIORITIES=16', 'CONFIG_MAIN_THREAD_PRIORITY=2',
                'CONFIG_SYS_CLOCK_TICKS_PER_SEC=100', 'CONFIG_ASSERT=y', 'CONFIG_PRINTK=y',
                'CONFIG_TIMESLICING=y', 'CONFIG_TIMESLICE_SIZE=0', 'CONFIG_TIMESLICE_PRIORITY=0',
                'CONFIG_SPEED_OPTIMIZATIONS=y', 'CONFIG_TEST=y', 'CONFIG_IRQ_OFFLOAD=y',
                f'CONFIG_TICKLESS_KERNEL={tickless}', f'CONFIG_SCHED_{scheduler}=y',
                f'CONFIG_WAITQ_{wait_queue}=y',
            ]) + '\n')
            target = folder / 'build'
            argv = ['cmake', '-S', str(app), '-B', str(target), '-GNinja',
                    '-DBOARD=esp32_devkitc_wroom/esp32/procpu',
                    f'-DZEPHYR_MODULES={hal};{xtensa}', f'-DZEPHYR_XTENSA_MODULE_DIR={include_root}',
                    f'-DCONF_FILE={fragment}', '-DEUNO_MATRIX=ON', '-DEUNO_ESP32=ON',
                    f'-DPython3_EXECUTABLE={sys.executable}']
            print(f'Building {name_mode}', flush=True)
            with (folder / 'build.log').open('w') as log:
                subprocess.run(argv, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
                subprocess.run(['cmake', '--build', target, '-j4'], env=env, stdout=log,
                               stderr=subprocess.STDOUT, check=True)
            config = (target / 'zephyr/.config').read_text().splitlines()
            flags = [f'CONFIG_SCHED_{scheduler}=y', f'CONFIG_WAITQ_{wait_queue}=y', 'CONFIG_SYS_CLOCK_TICKS_PER_SEC=100',
                     'CONFIG_SYS_CLOCK_HW_CYCLES_PER_SEC=240000000', 'CONFIG_IRQ_OFFLOAD=y']
            if not all(flag in config for flag in flags) or ('CONFIG_TICKLESS_KERNEL=y' in config) != (tickless == 'y'):
                raise ValueError(f'Resolved Kconfig differs from requested matrix: {name_mode}')
            summary.append(dict(configuration=name_mode, scheduler=scheduler, wait_queue=wait_queue,
                                tickless=tickless == 'y', build=str(target), configure=argv))
            (output / 'builds.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    build(parser.parse_args().output)
