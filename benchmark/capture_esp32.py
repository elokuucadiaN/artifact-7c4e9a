"""Capture and validate independent ESP32 resets through a Windows serial port."""
import argparse
import csv
import json
import statistics
import time
from pathlib import Path

WORKERS = [2, 10, 20, 50, 100]
TIMERS = [1, 10, 20, 50, 100]


def point(metric, parameter, value, unit):
    return dict(metric=metric, parameter=parameter, value=value, unit=unit)


def decode_trial(raw):
    rows = {}
    for line in raw.decode('ascii', errors='replace').splitlines():
        key, _, fields = line.strip().partition(' ')
        if key.startswith('EUNO_'):
            rows.setdefault(key, []).append(dict(token.split('=', 1) for token in fields.split()))

    def one(tag):
        if len(rows.get(tag, [])) != 1:
            raise ValueError(f'Expected one {tag} record')
        return rows[tag][0]

    board = one('EUNO_BOARD')
    if (board['os'] != 'FreeRTOS' or board['idf'] not in ('v5.2.5', 'v5.2.5-dirty')
            or board['clock_hz'] != '240000000' or board['tick_hz'] != '100'
            or board['core'] != '0' or board['mode'] != 'fixed'):
        raise ValueError(f'Unexpected board runtime: {board}')
    if one('EUNO_DONE')['errors'] != '0':
        raise ValueError('Firmware reported failures')

    def metric(name, parameter, value, unit):
        return dict(metric=name, parameter=parameter, value=value, unit=unit)

    start = int(one('EUNO_START')['timer_zero_to_app_us'])
    if start <= 0:
        raise ValueError('Invalid startup interval')
    data = [metric('boot.esp_timer_zero_to_app', '', start, 'us')]
    ipc = one('EUNO_IPC')
    if ipc['errors'] != '0' or (ipc['wake_rounds'], ipc['ping_rounds']) != ('100', '100'):
        raise ValueError('IPC progress check failed')
    for label, raw_cycles in [('scheduler.semaphore_wakeup', ipc['wake_cycles']),
                              ('ipc.semaphore_roundtrip', ipc['ping_cycles'])]:
        value = int(raw_cycles)
        if value <= 0:
            raise ValueError('Invalid IPC interval')
        data.append(metric(label, 'rounds=100', value / 100, 'cycles/round'))

    switch_rows = rows.get('EUNO_SWITCH', [])
    if [int(row['workers']) for row in switch_rows] != WORKERS:
        raise ValueError('Worker scale grid is incomplete')
    for row in switch_rows:
        workers, entries, handoffs, cycles = (int(row[k]) for k in ('workers', 'entries', 'handoffs', 'cycles'))
        if row['errors'] != '0' or row['rounds'] != '100' or entries != workers * 100:
            raise ValueError(f'Invalid worker progress: {row}')
        if not workers - 1 <= handoffs < entries or cycles <= 0:
            raise ValueError(f'Invalid handoff interval: {row}')
        data.append(metric('scheduler.worker_handoff', f'workers={workers}', cycles / handoffs, 'cycles/handoff'))

    timer_rows = rows.get('EUNO_TIMER', [])
    if [int(row['timers']) for row in timer_rows] != TIMERS:
        raise ValueError('Timer scale grid is incomplete')
    for row in timer_rows:
        if row['errors'] != '0' or row['callbacks'] != row['timers'] or row['delay_ms'] != '20':
            raise ValueError(f'Invalid callback progress: {row}')
        param = f'timers={row["timers"]},delay_ms=20'
        for label, key in [('timer.start_api_window', 'arm_cycles'),
                           ('timer.callback_body_window', 'callback_cycles')]:
            value = int(row[key])
            if value <= 0:
                raise ValueError(f'Invalid timer interval: {row}')
            data.append(metric(label, param, value, 'cycles'))
        data.append(metric('timer.requested_deadline_offset', param, int(row['max_offset_ticks']), 'tick@100Hz'))
    return board, data


def decode_zephyr(raw, expected_tickless):
    text = raw.decode('ascii', errors='replace')
    if text.count('ZOS_META os=Zephyr version=3.7.0 port=esp32 hardware_measurement=1') != 1:
        raise ValueError('Missing ESP32 Zephyr identity')
    if text.count('ZOS_DONE failures=0') != 1:
        raise ValueError('Firmware reported failures or did not finish')
    rows = {}
    for line in text.splitlines():
        key, _, fields = line.strip().partition(' ')
        if key.startswith('ZOS_') and fields:
            rows.setdefault(key, []).append(dict(token.split('=', 1) for token in fields.split()))

    def one(key):
        if len(rows.get(key, [])) != 1:
            raise ValueError(f'Expected one {key} record')
        return rows[key][0]

    board = one('ZOS_HW')
    if board['tick_hz'] != '100' or board['counter_hz'] != '240000000' or int(board['tickless']) != expected_tickless:
        raise ValueError(f'Unexpected Zephyr clock or tick mode: {board}')
    data = []

    def put(metric, parameter, value, unit):
        data.append(dict(metric=metric, parameter=parameter, value=value, unit=unit))

    preempt, pingpong, offload = (one(key) for key in ('ZOS_PREEMPT', 'ZOS_PINGPONG', 'ZOS_OFFLOAD'))
    for row in (preempt, pingpong, offload):
        if (row['verified'], row['errors'], row['rounds']) != ('100', '0', '100'):
            raise ValueError(f'Progress validation failed: {row}')
    if not 0 < int(offload['entry_sum_ns']) <= int(offload['roundtrip_sum_ns']):
        raise ValueError('Unexpected IRQ offload endpoints')
    put('scheduler.semaphore_wakeup', 'rounds=100', int(preempt['sum_ns']) / 100, 'ns/round')
    put('ipc.semaphore_roundtrip', 'rounds=100', int(pingpong['elapsed_ns']) / 100, 'ns/round')
    put('interrupt.native_offload_entry', 'rounds=100', int(offload['entry_sum_ns']) / 100, 'ns/interrupt')
    put('interrupt.native_offload_roundtrip', 'rounds=100', int(offload['roundtrip_sum_ns']) / 100, 'ns/interrupt')
    for tag, param, grid in [('ZOS_SWITCH', 'workers', WORKERS), ('ZOS_TIMER', 'timers', TIMERS),
                             ('ZOS_ANNOUNCE', 'timers', TIMERS)]:
        if [int(row[param]) for row in rows.get(tag, [])] != grid:
            raise ValueError(f'Incomplete {tag} grid')
    for row in rows['ZOS_SWITCH']:
        count, entries, handoffs, elapsed = (int(row[k]) for k in ('workers', 'entries', 'handoffs', 'elapsed_ns'))
        if row['errors'] != '0' or entries != count * 100 or not count - 1 <= handoffs < entries or elapsed <= 0:
            raise ValueError(f'Invalid worker progress: {row}')
        put('scheduler.worker_handoff', f'workers={count}', elapsed / handoffs, 'ns/handoff')
    for timer, announce in zip(rows['ZOS_TIMER'], rows['ZOS_ANNOUNCE']):
        if timer['errors'] != '0' or timer['callbacks'] != timer['timers'] or timer['context'] != 'isr':
            raise ValueError(f'Invalid timer callbacks: {timer}')
        if int(announce['calls']) < 1:
            raise ValueError('Missing kernel announce calls')
        parameter = f'timers={timer["timers"]},delay_ms=20'
        for metric, value in [('timer.start_api_window', timer['arm_ns']),
                              ('timer.callback_body_window', timer['callback_body_ns']),
                              ('timer.kernel_announce_window', announce['elapsed_ns'])]:
            if int(value) <= 0:
                raise ValueError(f'Invalid {metric} interval')
            put(metric, parameter, int(value), 'ns')
        put('timer.requested_deadline_offset', parameter, int(timer['max_offset_ns']), 'ns@100Hz')
        put('timer.kernel_announce_calls', parameter, int(announce['calls']), 'calls')
    return dict(os='Zephyr', version='3.7.0', **board), data


def decode_posix_or_riot(raw, os):
    nuttx = os == 'nuttx'
    prefix = 'NOS' if nuttx else 'ROS'
    identity = ('os=NuttX version=12.2.1 port=esp32 hardware_measurement=1' if nuttx else
                'os=RIOT version=dd06b372 port=esp32 counter=ztimer_usec hardware_measurement=1')
    text = raw.decode('ascii', errors='replace')
    if text.count(f'{prefix}_META {identity}') != 1:
        raise ValueError(f'Missing ESP32 {os} identity')
    if text.count(f'{prefix}_DONE failures=0') != 1 or f'{prefix}_FAIL' in text:
        raise ValueError(f'{os} firmware reported failures or did not finish')
    rows = {}
    for line in text.splitlines():
        key, _, fields = line.strip().partition(' ')
        if key.startswith(f'{prefix}_') and fields:
            rows.setdefault(key.split('_', 1)[1], []).append(dict(token.split('=', 1) for token in fields.split()))
    board, = rows['HW']
    expected_clock = {'counter_hz': '240000000', 'tick_us': '10000'} if nuttx else {'clock_hz': '240000000'}
    if board != expected_clock:
        raise ValueError(f'Unexpected {os} clocks: {board}')
    data = []
    for tag, key, metric in [('PREEMPT', 'sum_ns', 'scheduler.semaphore_wakeup'),
                             ('PINGPONG', 'elapsed_ns', 'ipc.semaphore_roundtrip')]:
        row, = rows[tag]
        elapsed = int(row[key])
        if (row['verified'], row['errors'], row['rounds']) != ('100', '0', '100') or elapsed <= 0:
            raise ValueError(f'Invalid IPC result: {row}')
        data.append(point(metric, 'rounds=100', elapsed / 100, 'ns/round'))
    if [int(row['workers']) for row in rows['SWITCH']] != WORKERS:
        raise ValueError(f'Incomplete {os} worker grid')
    if [int(row['timers']) for row in rows['TIMER']] != TIMERS:
        raise ValueError(f'Incomplete {os} timer grid')
    scale = 1 if nuttx else 1000
    for row in rows['SWITCH']:
        workers, entries, handoffs = (int(row[k]) for k in ('workers', 'entries', 'handoffs'))
        elapsed = int(row['elapsed_ns' if nuttx else 'elapsed_us']) * scale
        if row['errors'] != '0' or entries != workers * 100 or not workers - 1 <= handoffs < entries or elapsed <= 0:
            raise ValueError(f'Invalid worker progress: {row}')
        data.append(point('scheduler.worker_handoff', f'workers={workers}', elapsed / handoffs, 'ns/handoff'))
    for row in rows['TIMER']:
        expected_context = 'signal_handler' if nuttx else 'irq'
        if row['errors'] != '0' or row['callbacks'] != row['timers'] or row['context'] != expected_context:
            raise ValueError(f'Invalid timer callbacks: {row}')
        delay = int(row.get('delay_ms', 20))
        if delay != 20:
            raise ValueError(f'Unexpected timer request: {row}')
        parameter = f'timers={row["timers"]},delay_ms={delay}'
        armed = int(row['arm_ns' if nuttx else 'arm_us']) * scale
        window = int(row['callback_body_ns'])
        if armed <= 0 or window < 0 or (nuttx and window == 0):
            raise ValueError(f'Invalid timer interval: {row}')
        data.append(point('timer.start_api_window', parameter, armed, 'ns'))
        data.append(point('timer.callback_body_window', parameter, window, 'ns'))
        unit = 'ns@100Hz' if nuttx else 'ns@1kHz'
        data.append(point('timer.requested_deadline_offset', parameter, int(row['max_offset_ns']), unit))
    return dict(os='NuttX' if nuttx else 'RIOT', version='12.2.1' if nuttx else 'dd06b372', **board), data


def decode_capture(raw, os, tickless=0):
    if os == 'freertos':
        return decode_trial(raw)
    if os in ('nuttx', 'riot'):
        return decode_posix_or_riot(raw, os)
    return decode_zephyr(raw, tickless)


def capture(port, output, resets, os='freertos', tickless=0):
    import serial

    output.mkdir(parents=True, exist_ok=False)
    measurements = []
    with serial.Serial(port=None, baudrate=115200, timeout=0.1) as uart:
        uart.port = port
        uart.dtr = uart.rts = False
        uart.open()
        for reset in range(1, resets + 1):
            uart.reset_input_buffer()
            uart.rts = True
            time.sleep(0.12)
            uart.rts = False
            deadline = time.monotonic() + 16
            raw = bytearray()
            while time.monotonic() < deadline:
                raw.extend(uart.read(4096))
                markers = (b'EUNO_DONE ', b'ZOS_DONE ', b'NOS_DONE ', b'NOS_FAIL ', b'ROS_DONE ', b'ROS_FAIL ')
                if any(marker in raw for marker in markers) and raw.endswith(b'\n'):
                    break
            (output / f'reset-{reset:02}.log').write_bytes(raw)
            board, data = decode_capture(raw, os, tickless)
            measurements.extend(dict(reset=reset, **point) for point in data)
            print(f'Reset {reset}/{resets} validated', flush=True)
            time.sleep(0.2)

    with (output / 'measurements.csv').open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(measurements[0]))
        writer.writeheader()
        writer.writerows(measurements)
    groups = {}
    for point in measurements:
        key = (point['metric'], point['parameter'], point['unit'])
        groups.setdefault(key, []).append(point['value'])
    with (output / 'summary.csv').open('w', encoding='utf-8', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['metric', 'parameter', 'unit', 'independent_resets', 'median', 'min', 'max'])
        for key, values in sorted(groups.items()):
            writer.writerow([*key, len(values), statistics.median(values), min(values), max(values)])
    receipt = dict(status='passed', scope='physical_esp32_reconstruction', runtime=board,
                   independent_resets=resets, records=len(measurements), original_overall_eligible=False)
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resets', type=int, default=5)
    parser.add_argument('--os', choices=('freertos', 'zephyr', 'nuttx', 'riot'), default='freertos')
    parser.add_argument('--tickless', type=int, choices=(0, 1), default=0)
    args = parser.parse_args()
    if args.resets < 1:
        parser.error('--resets must be positive')
    capture(args.port, args.output, args.resets, args.os, args.tickless)
