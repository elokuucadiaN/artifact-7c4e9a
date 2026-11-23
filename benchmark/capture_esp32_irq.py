"""Capture and replay ESP32 Xtensa IRQ phase traces."""
import argparse
import csv
import json
import re
import statistics
import time
from pathlib import Path

from .capture_esp32_power import FIRMWARE_ERRORS, serial_port


MODES = {'fixed': 0, 'tickless': 1}
STAMPS = ('compare', 'vector', 'saved', 'isr', 'isr_end', 'restore', 'restored', 'resumed')
WINDOWS = ('compare_to_vector', 'save', 'dispatch', 'isr_body',
           'return_bookkeeping', 'restore', 'restore_tail_to_resumed')
SAMPLES = 512
CALIBRATIONS = 128


def decode(raw, mode):
    if any(marker in raw for marker in (*FIRMWARE_ERRORS, b'IRQ_FAIL')):
        raise ValueError('ESP32 reported an IRQ probe failure')
    records = [line.strip() for line in raw.decode('ascii', errors='replace').splitlines()
               if line.lstrip().startswith('IRQ_')]
    expected = (f'IRQ_META os=Zephyr version=3.7.0 source=CCOMPARE1 cpu_irq=15 level=3 cpu=0 '
                f'clock_hz=240000000 tickless={MODES[mode]} samples={SAMPLES} calibrations={CALIBRATIONS}')
    if len(records) != SAMPLES + CALIBRATIONS + 2 or records[0] != expected or records[-1] != 'IRQ_DONE hits=512 errors=0':
        raise ValueError(f'Incomplete or unexpected IRQ identity: {len(records)} records')
    calibration, samples = [], []
    for index, line in enumerate(records[1:CALIBRATIONS + 1]):
        tag, ordinal, cycles = line.split()
        if tag != 'IRQ_CAL' or int(ordinal) != index or not 0 < int(cycles) <= 20000:
            raise ValueError(f'Invalid calibration: {line}')
        calibration.append(int(cycles))
    for index, line in enumerate(records[CALIBRATIONS + 1:-1]):
        tag, ordinal, *values = line.split()
        if tag != 'IRQ_ROW' or int(ordinal) != index or len(values) != len(STAMPS) + 1:
            raise ValueError(f'Invalid IRQ trace row: {line}')
        if not all(re.fullmatch('[0-9a-f]{8}', value) for value in values):
            raise ValueError(f'Malformed cycle counter: {line}')
        *stamps, pending = (int(value, 16) for value in values)
        phases = [(end - start) & 0xffffffff for start, end in zip(stamps, stamps[1:])]
        if not pending & (1 << 15) or not all(0 < cycles <= 1200000 for cycles in phases):
            raise ValueError(f'Invalid IRQ source or cycle order: {line}')
        samples.append(dict(sample=index, pending_mask=f'0x{pending:08x}',
                            **{f'stamp_{name}': stamp for name, stamp in zip(STAMPS, stamps)},
                            **dict(zip(WINDOWS, phases))))
    return calibration, samples


def capture(port, root, mode, resets):
    root.mkdir(parents=True, exist_ok=False)
    with serial_port(port, 0.075) as uart:
        for reset in range(1, resets + 1):
            uart.rts = True
            time.sleep(.12)
            uart.reset_input_buffer()
            uart.rts = False
            raw = bytearray()
            deadline = time.monotonic() + 18
            while time.monotonic() < deadline:
                raw.extend(uart.read(4096))
                if b'IRQ_DONE ' in raw or b'IRQ_FAIL ' in raw:
                    time.sleep(.18)
                    raw.extend(uart.read(uart.in_waiting))
                    break
            (root / f'reset-{reset:02}.log').write_bytes(raw)
            calibration, samples = decode(raw, mode)
            print(f'{mode} reset {reset}/{resets}: {len(samples)} hardware IRQs, '
                  f'calibration median {statistics.median(calibration):g} cycles', flush=True)
    (root / 'receipt.json').write_text(json.dumps(dict(mode=mode, resets=resets,
        irqs_per_reset=SAMPLES, calibrations_per_reset=CALIBRATIONS, original_overall_eligible=False),
        indent=2) + '\n')


def csv_write(path, rows):
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def summarize(root, resets):
    all_samples, all_calibration, per_reset, summary = [], [], [], []
    for mode in MODES:
        capture_dir = root / 'captures' / mode
        receipt = json.loads((capture_dir / 'receipt.json').read_text())
        if receipt['resets'] != resets or receipt['mode'] != mode:
            raise ValueError(f'Unexpected capture receipt for {mode}')
        grouped = {}
        for reset in range(1, resets + 1):
            calibration, samples = decode((capture_dir / f'reset-{reset:02}.log').read_bytes(), mode)
            all_samples.extend(dict(mode=mode, reset=reset, **point) for point in samples)
            all_calibration.extend(dict(mode=mode, reset=reset, sample=index, cycles=value)
                                   for index, value in enumerate(calibration))
            series = {window: [point[window] for point in samples] for window in WINDOWS}
            series['ccount_store_calibration'] = calibration
            for window, values in series.items():
                median = statistics.median(values)
                grouped.setdefault(window, []).append(median)
                per_reset.append(dict(mode=mode, reset=reset, window=window, samples=len(values),
                                      median_cycles=median, min_cycles=min(values), max_cycles=max(values)))
        for window, values in grouped.items():
            summary.append(dict(mode=mode, window=window, independent_resets=len(values),
                                median_cycles=statistics.median(values), min_reset_median_cycles=min(values),
                                max_reset_median_cycles=max(values)))
    for name, rows in [('irq-samples', all_samples), ('calibration', all_calibration),
                       ('per-reset', per_reset), ('summary', summary)]:
        csv_write(root / f'{name}.csv', rows)
    print(f'Verified {len(all_samples)} hardware IRQ traces and {len(all_calibration)} calibration samples')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port')
    parser.add_argument('--mode', choices=MODES)
    parser.add_argument('--resets', type=int, default=5)
    args = parser.parse_args()
    if args.resets < 1 or bool(args.port) != bool(args.mode):
        parser.error('Use positive resets and supply both --port and --mode for capture')
    if args.port:
        capture(args.port, args.output, args.mode, args.resets)
    else:
        summarize(args.output, args.resets)
