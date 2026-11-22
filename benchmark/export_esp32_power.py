"""Replay the ESP32 power capture receipts and summarize five-reset series."""
import argparse
import csv
import hashlib
import json
import statistics
import struct
from pathlib import Path

from .capture_esp32 import decode_capture
from .capture_esp32_power import FIRMWARE_ERRORS, MARKERS, integrate


WINDOWS = ('reset_to_suite_done', 'app_to_suite_done', 'post_suite_idle', 'reset_to_app')


def read_trial(folder, os_name, tickless):
    result = json.loads((folder / 'result.json').read_text())
    raw = (folder / 'uart.raw').read_bytes()
    if any(marker in raw for marker in FIRMWARE_ERRORS):
        raise ValueError(f'Firmware fault in {folder}')
    events = [json.loads(line) for line in (folder / 'uart.jsonl').read_text().splitlines()]
    lines = [bytes.fromhex(event['line_hex']) for event in events]
    if not raw.startswith(b''.join(line + b'\n' for line in lines)):
        raise ValueError(f'UART bytes disagree with events in {folder}')
    for marker, field in zip(MARKERS[os_name], ('app_line_received_s', 'suite_done_received_s')):
        observed = [event['receipt_s'] for event, line in zip(events, lines) if marker in line]
        if observed != [result[field]]:
            raise ValueError(f'Invalid UART phase marker in {folder}')
    board, measurements = decode_capture(raw, os_name, tickless)
    result['probe_measurements'] = measurements
    if board != result['runtime']:
        raise ValueError(f'Invalid runtime identity in {folder}')
    start = result['reset_release_end_s']
    app = result['app_line_received_s']
    done = result['suite_done_received_s']
    if not result['reset_release_begin_s'] <= start < app <= done:
        raise ValueError(f'Invalid timing order in {folder}')
    if result['reset_to_app_ms'] != (app - start) * 1000 or result['app_to_suite_done_ms'] != (done - app) * 1000:
        raise ValueError(f'Invalid timing interval in {folder}')
    if not (folder / 'meter.csv').exists():
        return result

    with (folder / 'meter.csv').open() as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) < 20 or len(rows) != result['power_samples']:
        raise ValueError(f'Invalid sample count in {folder}')
    power = []
    previous_end = 0
    polarity = result['polarity']
    if polarity not in (-1, 1):
        raise ValueError(f'Invalid meter polarity in {folder}')
    for tid, row in enumerate(rows, 1):
        begin, end = (float(row[key]) for key in ('query_begin_s', 'query_end_s'))
        packet = bytes.fromhex(row['packet_hex'])
        voltage, current = struct.unpack_from('<Ii', packet, 8)
        if (len(packet) != 52 or packet[:4] != bytes((0x41, tid % 256, 0x80, 2))
                or (voltage, current) != (int(row['voltage_uv']), int(row['current_ua']))
                or not previous_end <= begin < end):
            raise ValueError(f'Invalid packet or sample time in {folder}')
        previous_end = end
        if (begin + end) / 2 >= start and (not 4400000 <= voltage <= 5600000 or polarity * current < -2000):
            raise ValueError(f'Unexpected VBUS voltage or direction in {folder}')
        power.append(((begin + end) / 2, voltage * current * polarity / 1e12))
    limits = [(start, done), (app, done), (done + 0.5, done + 3.0), (start, app)]
    for window, (begin, end) in zip(WINDOWS, limits):
        if window in result and integrate(power, begin, end) != result[window]:
            raise ValueError(f'Energy replay differs for {window} in {folder}')
    return result


def write_csv(path, rows):
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def export(run):
    series, summary, probes = [], [], []
    campaign_polarities = set()
    for folder in sorted(run.iterdir()):
        receipt_path = folder / 'receipt.json'
        if not receipt_path.exists():
            continue
        receipt = json.loads(receipt_path.read_text())
        if receipt['status'] != 'passed' or receipt['resets'] != 5:
            raise ValueError(f'Incomplete run {folder}')
        name = folder.name
        os_name = 'zephyr' if name.startswith('zephyr-') else name
        groups = {}
        polarities = set()
        for reset in range(1, 6):
            result = read_trial(folder / f'reset-{reset:02}', os_name, int(name.endswith('-tickless')))
            probes.extend(dict(configuration=name, reset=reset, **point) for point in result['probe_measurements'])
            if 'polarity' in result:
                polarities.add(result['polarity'])
            values = {
                'reset_to_app_ms': result['reset_to_app_ms'],
                'app_to_suite_done_ms': result['app_to_suite_done_ms'],
            }
            for window in WINDOWS:
                if window in result:
                    values[f'{window}_energy_mj'] = result[window]['energy_j'] * 1000
                    values[f'{window}_mean_mw'] = result[window]['average_power_w'] * 1000
            for metric, value in values.items():
                groups.setdefault(metric, []).append(value)
                series.append(dict(configuration=name, reset=reset, metric=metric, value=value))
        if len(polarities) > 1:
            raise ValueError(f'Inconsistent power orientation within {name}')
        campaign_polarities.update(polarities)
        for metric, values in sorted(groups.items()):
            summary.append(dict(configuration=name, metric=metric, resets=len(values),
                                median=statistics.median(values), min=min(values), max=max(values)))
    if len(campaign_polarities) > 1:
        raise ValueError('Power polarity changed across configurations')
    if not series:
        raise ValueError('No complete power runs')
    write_csv(run / 'measurements.csv', series)
    write_csv(run / 'summary.csv', summary)
    write_csv(run / 'probe-measurements.csv', probes)
    files = [p for p in sorted(run.rglob('*')) if p.is_file() and p.name != 'SHA256SUMS']
    (run / 'SHA256SUMS').write_text(''.join(
        f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(run).as_posix()}\n' for p in files))
    print(f'Verified {len({row["configuration"] for row in summary})} configurations and {len(series)} observations')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    export(parser.parse_args().run)
