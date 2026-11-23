"""Build instrumented ESP32 fixed-tick and tickless Zephyr IRQ probes in WSL."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from .version_policy import PINS


# A0/A2/A3 are already on the interrupted stack at the vector stamp.
VECTOR_STAMP = r"""
.if \LVL == 3
	rsr a0, CCOUNT
	movi a2, euno_irq_trace
	l32i a3, a2, 0
	beqz a3, .Leuno_vector_done_\@
	s32i a0, a2, 4
.Leuno_vector_done_\@:
.endif
"""

# A0/A2/A3 are scratch after the full save. A1 is the saved frame handle.
FULL_SAVE_STAMP = r"""
	rsr a0, CCOUNT
	movi a2, euno_irq_trace
	l32i a3, a2, 4
	beqz a3, .Leuno_save_done_\@
	l32i a3, a2, 8
	bnez a3, .Leuno_save_done_\@
	s32i a0, a2, 8
	s32i a1, a2, 28
	l32i a3, a1, 0
	s32i a3, a2, 32
.Leuno_save_done_\@:
"""

# Match the trace's frame before high-register restore and its BSA afterwards.
RESTORE_START_STAMP = """
	rsr a0, CCOUNT
	movi a2, euno_irq_trace
	l32i a3, a2, 28
	bne a3, a1, .Leuno_restore_start_done
	l32i a3, a2, 16
	beqz a3, .Leuno_restore_start_done
	s32i a0, a2, 20
.Leuno_restore_start_done:
"""
RESTORE_END_STAMP = """
	rsr a0, CCOUNT
	movi a2, euno_irq_trace
	l32i a3, a2, 32
	bne a3, a1, .Leuno_restore_end_done
	l32i a3, a2, 20
	beqz a3, .Leuno_restore_end_done
	s32i a0, a2, 24
.Leuno_restore_end_done:
"""


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f'Architecture anchor changed: {old!r}')
    return source.replace(old, new)


def patch(worktree):
    header = worktree / 'arch/xtensa/include/xtensa_asm2_s.h'
    assembly = worktree / 'arch/xtensa/core/xtensa_asm2_util.S'
    source = header.read_text()
    anchor = '\tcall0 xtensa_save_high_regs\n\n\tl32i a2, a1, 0'
    source = replace_once(source, anchor, '\tcall0 xtensa_save_high_regs\n' + FULL_SAVE_STAMP + '\n\tl32i a2, a1, 0')
    anchor = '\ts32i a3, a1, ___xtensa_irq_bsa_t_a3_OFFSET\n\n\t/* Level "1"'
    source = replace_once(source, anchor, '\ts32i a3, a1, ___xtensa_irq_bsa_t_a3_OFFSET\n' + VECTOR_STAMP + '\n\t/* Level "1"')
    header.write_text(source)
    source = assembly.read_text()
    anchor = '_restore_context:\n\tcall0 xtensa_restore_high_regs'
    source = replace_once(source, anchor, '_restore_context:\n' + RESTORE_START_STAMP + '\tcall0 xtensa_restore_high_regs')
    anchor = '\trsync\n\n\tl32i a0, a1, ___xtensa_irq_bsa_t_a0_OFFSET'
    source = replace_once(source, anchor, '\trsync\n' + RESTORE_END_STAMP + '\n\tl32i a0, a1, ___xtensa_irq_bsa_t_a0_OFFSET')
    assembly.write_text(source)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(output):
    home = Path.home() / 'eunobench'
    upstream = home / 'upstream'
    original = upstream / 'zephyr-v3.7.0-mirror'
    worktree = output / 'zephyr-source'
    app = Path(__file__).resolve().parent / 'native/zephyr_irq'
    hal = upstream / 'hal_espressif-board'
    xtensa = upstream / 'hal_xtensa'
    compiler = home / 'tools/esp-idf-v5.2.5/tools/xtensa-esp-elf/esp-13.2.0_20230928/xtensa-esp-elf/bin/xtensa-esp32-elf-'
    hal_pin = '87e7902d7184a8280b4d13bce79801a723f4ddd8'
    for path, pin in ((original, PINS['zephyr']), (hal, hal_pin)):
        if subprocess.check_output(['git', '-C', path, 'rev-parse', 'HEAD'], text=True).strip() != pin:
            raise ValueError(f'Unexpected SDK revision: {path}')
    output.mkdir(parents=True, exist_ok=True)
    if not worktree.exists():
        subprocess.run(['git', '-C', original, 'worktree', 'add', '--detach', worktree, PINS['zephyr']], check=True)
        patch(worktree)
    include = output / 'core-isa'
    (include / 'zephyr/soc').mkdir(parents=True, exist_ok=True)
    shim = include / 'zephyr/soc/esp32'
    if not shim.exists():
        shim.symlink_to(hal / 'components/xtensa/esp32/include', target_is_directory=True)
    patch_file = output / 'zephyr-irq.patch'
    patch_file.write_bytes(subprocess.check_output(['git', '-C', worktree, 'diff']))
    if not patch_file.stat().st_size:
        raise ValueError('Missing architecture instrumentation')
    env = dict(os.environ, ZEPHYR_BASE=str(worktree), ZEPHYR_TOOLCHAIN_VARIANT='cross-compile',
               CROSS_COMPILE=str(compiler))
    configurations = []
    for name, tickless in (('fixed', 'n'), ('tickless', 'y')):
        folder = output / name
        folder.mkdir(exist_ok=True)
        fragment = folder / 'probe.conf'
        fragment.write_text('\n'.join([
            'CONFIG_MAIN_STACK_SIZE=4096', 'CONFIG_SYS_CLOCK_TICKS_PER_SEC=100',
            'CONFIG_SPEED_OPTIMIZATIONS=y', 'CONFIG_SCHED_DUMB=y', 'CONFIG_WAITQ_DUMB=y',
            'CONFIG_ASSERT=y', 'CONFIG_PRINTK=y', 'CONFIG_XTENSA_SMALL_VECTOR_TABLE_ENTRY=y',
            f'CONFIG_TICKLESS_KERNEL={tickless}',
        ]) + '\n')
        target = folder / 'build'
        with (folder / 'build.log').open('w') as log:
            subprocess.run(['cmake', '-S', app, '-B', target, '-GNinja',
                            '-DBOARD=esp32_devkitc_wroom/esp32/procpu',
                            f'-DZEPHYR_MODULES={hal};{xtensa}', f'-DZEPHYR_XTENSA_MODULE_DIR={include}',
                            f'-DCONF_FILE={fragment}', f'-DPython3_EXECUTABLE={sys.executable}'],
                           env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
            subprocess.run(['cmake', '--build', target, '-j4'], env=env, stdout=log,
                           stderr=subprocess.STDOUT, check=True)
        config = (target / 'zephyr/.config').read_text().splitlines()
        required = {'CONFIG_XTENSA_SMALL_VECTOR_TABLE_ENTRY=y', 'CONFIG_XTENSA_TIMER_ID=0',
                    'CONFIG_SYS_CLOCK_HW_CYCLES_PER_SEC=240000000', 'CONFIG_SYS_CLOCK_TICKS_PER_SEC=100'}
        if not required.issubset(config) or ('CONFIG_TICKLESS_KERNEL=y' in config) != (tickless == 'y'):
            raise ValueError(f'Unexpected resolved Kconfig for {name}')
        paths = [target / 'zephyr' / part for part in ('zephyr.bin', 'zephyr.elf', 'zephyr.map', '.config')]
        configurations.append(dict(name=name, tickless=tickless == 'y',
                                   files={path.name: digest(path) for path in paths}))
        print(f'Built {name}', flush=True)
    manifest = dict(zephyr_commit=PINS['zephyr'], hal_espressif_commit=hal_pin,
                    toolchain=subprocess.check_output([str(compiler) + 'gcc', '--version'], text=True).splitlines()[0],
                    architecture_patch_sha256=digest(patch_file), configurations=configurations)
    (output / 'firmware.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    build(parser.parse_args().output.resolve())
