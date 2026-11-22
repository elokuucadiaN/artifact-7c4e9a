"""Measure ESP32 reset markers and board-input power on a shared host clock."""
import argparse
import csv
import json
import statistics
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import serial

from benchmark.capture_esp32 import decode_capture


MARKERS = {
    'freertos': (b'EUNO_BOARD ', b'EUNO_DONE '),
    'zephyr': (b'ZOS_META ', b'ZOS_DONE '),
    'nuttx': (b'NOS_META ', b'NOS_DONE '),
    'riot': (b'ROS_META ', b'ROS_DONE '),
}
FIRMWARE_ERRORS = (b'FATAL EXCEPTION', b'FATAL ERROR', b'Guru Meditation', b'RTCWDT_RTC_RESET')


def serial_port(name, timeout):
    port = serial.Serial(port=None, baudrate=115200, timeout=timeout, write_timeout=0.3)
    port.port = name
    port.dtr = port.rts = False
    port.open()
    return port


def meter_trace(name, origin, stop, ready):
    samples = []
    with serial_port(name, 0.3) as meter:
        meter.reset_input_buffer()
        tid = 0
        while not stop.is_set():
            tid = (tid + 1) % 256
            before = time.perf_counter()
            meter.write(bytes((0x0c, tid, 2, 0)))
            packet = meter.read(52)
            after = time.perf_counter()
            if len(packet) != 52 or packet[:4] != bytes((0x41, tid, 0x80, 2)):
                raise ValueError(f'Unexpected POWER-Z reply length/header: {len(packet)}, {packet[:4].hex()}')
            voltage_uv, current_ua = struct.unpack_from('<Ii', packet, 8)
            samples.append((before - origin, after - origin, voltage_uv, current_ua, packet.hex()))
            if len(samples) == 20:
                midpoint = statistics.median(row[2] for row in samples)
                current = statistics.median(row[3] for row in samples)
                if not 4400000 <= midpoint <= 5600000 or abs(current) < 2000:
                    raise ValueError(f'No loaded 5 V meter path: {midpoint / 1e6:.6f} V, {current / 1e6:.6f} A')
                ready.set()
            stop.wait(max(0, 0.005 - (after - before)))
    return samples


def timestamp_uart(uart, origin, os_name, observe_idle):
    uart.rts = True
    time.sleep(0.12)
    uart.reset_input_buffer()
    before = time.perf_counter() - origin
    uart.rts = False
    after = time.perf_counter() - origin
    timings = {'reset_release_begin_s': before, 'reset_release_end_s': after}
    raw = bytearray()
    pending = b''
    events = []
    app, completion = MARKERS[os_name]
    deadline = after + 12
    while time.perf_counter() - origin < deadline:
        chunk = uart.read(max(1, uart.in_waiting))
        if not chunk:
            continue
        receipt = time.perf_counter() - origin
        raw.extend(chunk)
        pending += chunk
        while b'\n' in pending:
            line, pending = pending.split(b'\n', 1)
            events.append(dict(receipt_s=receipt, line_hex=line.hex()))
            if app in line:
                timings.setdefault('app_line_received_s', receipt)
            if completion in line:
                timings.setdefault('suite_done_received_s', receipt)
        if 'suite_done_received_s' in timings and not observe_idle:
            break
        if 'suite_done_received_s' in timings:
            deadline = timings['suite_done_received_s'] + 3.25
    return raw, timings, events


def integrate(points, start, end):
    if not points[0][0] <= start < end <= points[-1][0]:
        raise ValueError('Meter trace does not bracket the measurement window')
    energy = duration = 0.0
    gaps = []
    for (left, start_p), (right, end_p) in zip(points, points[1:]):
        a, b = max(start, left), min(end, right)
        if b <= a:
            continue
        gap = right - left
        gaps.append(gap)
        if not 0 < gap <= 0.04:
            raise ValueError(f'Invalid power sample gap: {gap:.6f} s')
        p_a = start_p + (end_p - start_p) * (a - left) / gap
        p_b = start_p + (end_p - start_p) * (b - left) / gap
        energy += (p_a + p_b) * (b - a) / 2
        duration += b - a
    if len(gaps) < 5:
        raise ValueError('Too few power samples for interval integration')
    return dict(energy_j=energy, average_power_w=energy / duration, duration_s=duration,
                sample_intervals=len(gaps), max_sample_gap_s=max(gaps))


def record(output, uart, meter_port, os_name, tickless):
    output.mkdir(exist_ok=False)
    origin = time.perf_counter()
    stop, ready = Event(), Event()
    samples = None
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(meter_trace, meter_port, origin, stop, ready) if meter_port else None
        try:
            if future and not ready.wait(1.5):
                if future.done():
                    future.result()
                raise TimeoutError('POWER-Z did not deliver the pilot samples')
            raw, timings, events = timestamp_uart(uart, origin, os_name, bool(future))
            (output / 'uart.raw').write_bytes(raw)
            (output / 'uart.jsonl').write_text(''.join(json.dumps(event) + '\n' for event in events))
            if any(marker in raw for marker in FIRMWARE_ERRORS):
                raise ValueError('Firmware fault detected before the observation window ended')
            runtime, _ = decode_capture(raw, os_name, tickless)
        finally:
            stop.set()
            if future:
                samples = future.result()
                with (output / 'meter.csv').open('w', newline='') as handle:
                    writer = csv.writer(handle)
                    writer.writerow(['query_begin_s', 'query_end_s', 'voltage_uv', 'current_ua', 'packet_hex'])
                    writer.writerows(samples)
    start = timings['reset_release_end_s']
    app = timings['app_line_received_s']
    done = timings['suite_done_received_s']
    result = dict(runtime=runtime, **timings, reset_to_app_ms=(app - start) * 1000,
                  app_to_suite_done_ms=(done - app) * 1000)
    if samples:
        active = [row for row in samples if (row[0] + row[1]) / 2 >= start]
        current = statistics.median(row[3] for row in active)
        polarity = 1 if current > 0 else -1
        if abs(current) < 2000 or any(not 4400000 <= row[2] <= 5600000 or polarity * row[3] < -2000
                                     for row in active):
            raise ValueError('Meter supply voltage or current direction changed during the trial')
        power = [((begin + end) / 2, volts * amps * polarity / 1e12)
                 for begin, end, volts, amps, _ in samples]
        result.update(polarity=polarity, power_samples=len(samples),
                      reset_to_suite_done=integrate(power, start, done),
                      app_to_suite_done=integrate(power, app, done),
                      post_suite_idle=integrate(power, done + 0.5, done + 3.0))
        try:
            result['reset_to_app'] = integrate(power, start, app)
        except ValueError as error:
            result['reset_to_app_unresolved'] = str(error)
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--meter-port')
    parser.add_argument('--os', choices=MARKERS, required=True)
    parser.add_argument('--tickless', type=int, choices=(0, 1), default=0)
    parser.add_argument('--resets', type=int, default=5)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.resets < 1 or args.meter_port == args.port:
        parser.error('Use positive resets and distinct ESP32/meter serial ports')
    args.output.mkdir(parents=True, exist_ok=False)
    results = []
    with serial_port(args.port, .002) as uart:
        for reset in range(1, args.resets + 1):
            item = record(args.output / f'reset-{reset:02}', uart, args.meter_port, args.os, args.tickless)
            results.append(item)
            print(f'Reset {reset}/{args.resets} validated', flush=True)
    (args.output / 'receipt.json').write_text(json.dumps(
        dict(status='passed', resets=len(results), meter=bool(args.meter_port),
             scope='benchmarked_test_firmware', original_overall_eligible=False),
        indent=2) + '\n')


if __name__ == '__main__':
    main()
