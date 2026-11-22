"""Revalidate board captures and export evidence from the WSL build directory."""
import argparse
import csv
import hashlib
import json
import shutil
import statistics
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from elftools.elf.elffile import ELFFile

from .capture_esp32 import decode_capture
from .version_policy import PINS


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def region(address):
    for start, end, name in [
        (0x3F400000, 0x3F800000, 'flash.drom'),
        (0x400D0000, 0x40400000, 'flash.irom'),
        (0x3FF80000, 0x3FFA0000, 'rtc.fast_data'),
        (0x3FFAE000, 0x40000000, 'ram.dram'),
        (0x40080000, 0x400C0000, 'ram.iram'),
        (0x400C0000, 0x400C2000, 'rtc.fast_instr'),
        (0x50000000, 0x50002000, 'rtc.slow'),
    ]:
        if start <= address < end:
            return name
    return 'other'


def sections(path, name):
    with path.open('rb') as handle:
        elf = ELFFile(handle)
        for section in elf.iter_sections():
            address, size, flags = (section[k] for k in ('sh_addr', 'sh_size', 'sh_flags'))
            if size and flags & 0x2:
                yield dict(configuration=name, section=section.name, address=hex(address),
                           region=region(address), section_type=section['sh_type'], bytes=size,
                           content_bytes=0 if section['sh_type'] == 'SHT_NOBITS' else size)


def write_csv(path, rows):
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def staged_evidence(root, configuration):
    if configuration == 'freertos':
        build = root / 'freertos/build'
        return 'freertos', build, 'euno_esp32.elf', [
            'euno_esp32.elf', 'euno_esp32.map', 'euno_esp32.bin', 'bootloader/bootloader.bin',
            'partition_table/partition-table.bin', 'flasher_args.json', 'config/sdkconfig.json',
        ]
    if configuration == 'nuttx':
        build = root / 'nuttx/nuttx'
        return 'nuttx', build, 'nuttx', ['nuttx', 'nuttx.bin', '.config', 'System.map']
    if configuration == 'riot':
        build = root / 'riot/bin-gcc12-full-libc/esp32-wroom-32'
        return 'riot', build, 'eunobench_probes.elf', [
            'eunobench_probes.elf', 'eunobench_probes.map', 'eunobench_probes.elf.bin',
            'esp_bootloader/bootloader.bin', 'partitions.bin',
        ]
    build = root / 'zephyr' / configuration.removeprefix('zephyr-') / 'build/zephyr'
    return 'zephyr', build, 'zephyr.elf', [
        'zephyr.elf', 'zephyr.map', 'zephyr.bin', '.config', 'runners.yaml',
    ]


def export(root, output):
    output.mkdir(parents=True, exist_ok=True)
    all_points, all_summaries, all_sections, configs = [], [], [], []
    for capture in sorted((root / 'measurements').iterdir()):
        if not (capture / 'receipt.json').is_file():
            continue
        name = capture.name
        os_name, build, elf, expected = staged_evidence(root, name)
        tickless = int(name.endswith('-tickless'))
        receipt = json.loads((capture / 'receipt.json').read_text())
        if receipt['status'] != 'passed' or receipt['independent_resets'] != 5:
            raise ValueError(f'Invalid capture receipt for {name}')
        trials, groups = [], {}
        for index, path in enumerate(sorted(capture.glob('reset-*.log')), 1):
            runtime, measurements = decode_capture(path.read_bytes(), os_name, tickless)
            if runtime != receipt['runtime']:
                raise ValueError(f'Runtime metadata mismatch in {path}')
            for record in measurements:
                key = tuple(record[field] for field in ('metric', 'parameter', 'unit'))
                groups.setdefault(key, []).append(record['value'])
                trials.append(dict(reset=index, **record))
        with (capture / 'measurements.csv').open() as handle:
            saved = list(csv.DictReader(handle))
        if [{key: str(value) for key, value in row.items()} for row in trials] != saved:
            raise ValueError(f'Saved CSV disagrees with raw serial logs for {name}')
        if len(trials) != receipt['records'] or any(len(series) != 5 for series in groups.values()):
            raise ValueError(f'Incomplete measurements for {name}')
        for metric, parameter, unit in sorted(groups):
            values = groups[(metric, parameter, unit)]
            all_summaries.append(dict(configuration=name, metric=metric, parameter=parameter,
                                      unit=unit, independent_resets=5, median=statistics.median(values),
                                      min=min(values), max=max(values)))
        all_points.extend(dict(configuration=name, **row) for row in trials)
        destination = output / name
        shutil.copytree(capture, destination, dirs_exist_ok=True)
        target = destination / 'firmware'
        target.mkdir(exist_ok=True)
        for filename in expected:
            shutil.copy2(build / filename, target / Path(filename).name)
        all_sections.extend(sections(build / elf, name))
        configs.append(dict(configuration=name, upstream_commit=PINS[os_name], **receipt,
                            firmware={path.name: {'bytes': path.stat().st_size, 'sha256': sha256(path)}
                                      for path in sorted(target.iterdir())}))
    if not configs:
        raise ValueError('No validated board captures found')
    write_csv(output / 'measurements.csv', all_points)
    write_csv(output / 'summary.csv', all_summaries)
    write_csv(output / 'elf-sections.csv', all_sections)
    manifest = dict(scope='physical_esp32_reconstruction', original_overall_eligible=False,
                    chip='ESP32-D0WDQ6 rev 1.1', flash_bytes=4194304, crystal_mhz=40,
                    configurations=configs, independent_resets=sum(c['independent_resets'] for c in configs),
                    records=len(all_points))
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'{len(configs)} configurations, {manifest["independent_resets"]} resets, {len(all_points)} records')


def package(output):
    hashes = output / 'SHA256SUMS'
    paths = [file for file in sorted(output.rglob('*')) if file.is_file() and file != hashes]
    hashes.write_text(''.join(f'{sha256(file)}  {file.relative_to(output).as_posix()}\n' for file in paths))
    archive = output.with_suffix('.zip')
    with ZipFile(archive, 'w', ZIP_DEFLATED) as zip_file:
        for file in [*paths, hashes]:
            zip_file.write(file, file.relative_to(output))
    with ZipFile(archive) as zip_file:
        if zip_file.testzip() is not None:
            raise ValueError('Archive integrity check failed')
        for file in paths:
            if hashlib.sha256(zip_file.read(file.relative_to(output).as_posix())).hexdigest() != sha256(file):
                raise ValueError(f'Archive hash mismatch for {file}')
    archive.with_suffix('.zip.sha256').write_text(f'{sha256(archive)}  {archive.name}\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--package', action='store_true')
    args = parser.parse_args()
    if args.package:
        package(args.output)
    elif args.run:
        export(args.run, args.output)
    else:
        sys.exit('--run is required for export')
