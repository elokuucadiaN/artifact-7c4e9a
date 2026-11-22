# EunoBench ESP32 hardware supplement

The suite runs thread handoff, higher-priority semaphore wakeup, semaphore round-trip and one-shot timer scaling workloads on an ESP32-WROOM-32-class target. The scheduler grid is 2, 10, 20, 50 and 100 workers at 100 iterations each. The timer grid is 1, 10, 20, 50 and 100 callbacks, each requested at 20 ms. The hardware measurements form a separate EunoBench panel using reconstructed application builds with the paper's pinned upstream revisions.

| Target | Native timer path | Clock for short intervals |
| --- | --- | --- |
| FreeRTOS, ESP-IDF 5.2.5 | FreeRTOS timer daemon task | Xtensa CCOUNT at 240 MHz |
| Zephyr 3.7.0 | Kernel timer callback in ISR; wrapped `sys_clock_announce` | Zephyr `k_cycle_get_32` at 240 MHz |
| NuttX 12.2.1 | POSIX timer signal handler | Xtensa CCOUNT at 240 MHz |
| RIOT dd06b372 | ztimer callback in IRQ | `ZTIMER_USEC` |

The FreeRTOS, Zephyr and NuttX configurations use 100 Hz logical ticks. RIOT uses ztimer for deadlines and has a millisecond observer for deadline offsets. All variants run on one core at 240 MHz. The observer's tick granularity limits the deadline offset measurement even when a CSV stores nanoseconds.

## Build and flash

Keep the source trees, build products and measurements on WSL's Linux filesystem. The build commands below assume the paper revisions and tools listed in the release evidence. The Windows side uses `esptool==4.8.1`, `bitstring<5` and `pyserial==3.5` to access the serial bridge. Determine the board's COM port and preserve its current firmware before flashing.

- **FreeRTOS**. Use ESP-IDF v5.2.5 and the ESP-IDF tools environment, then build `benchmark/native/freertos_esp32` with `idf.py -DIDF_TARGET=esp32 -B <run>/freertos/build build`. Flash the files and offsets from the generated `flasher_args.json`.
- **Zephyr**. Run `python -m benchmark.build_zephyr_esp32 --output <run>/zephyr` from the artifact root. The runner uses the `esp32_devkitc_wroom/esp32/procpu` target. Flash the generated `zephyr.bin` at `0x1000` and pass the matching `--tickless 0` or `--tickless 1` when capturing. The two additional policy pairs change scheduler and wait-queue implementations.
- **NuttX**. Run `python -m benchmark.build_nuttx_esp32 --output <run>/nuttx`. Flash the FreeRTOS build's ESP-IDF bootloader at `0x1000` and partition table at `0x8000`, then the NuttX `nuttx.bin` at `0x10000`.
- **RIOT**. Pre-seed `<run>/riot/pkg/esp32_sdk` with the ESP-IDF repository checked out at `1329b19fe494500aeb79d19b27cfd99b40c37aec`. With the Xtensa GCC 12.2.0 toolchain from RIOT's ESP32 installer and the Python environment on PATH, run `make -C benchmark/native/riot_native BOARD=esp32-wroom-32 RIOTBASE=<riot-source> PKGDIRBASE=<run>/riot/pkg BINDIRBASE=<run>/riot/bin-gcc12-full-libc EUNO_COMMON=<artifact>/benchmark/native/common`. The board build uses full newlib for 64-bit UART values. Use the generated bootloader, partitions and `eunobench_probes.elf.bin` at `0x1000`, `0x8000` and `0x10000`, respectively.

## Collect and verify

```powershell
python benchmark/capture_esp32.py --port COM6 --os zephyr --tickless 0 --resets 5 --output "<run UNC path>\measurements\zephyr-baseline-fixed"
```

Use `freertos`, `nuttx` or `riot` for the other `--os` options and matching output directory names. Each run opens the serial port at 115200 baud and drives RTS for five independent resets. The capture checks the runtime identity, task progress, timer counts and test completion. A failed capture preserves the raw log and produces no pass receipt. Keep the physical setup and firmware fixed within a five-reset series.

```bash
python -m benchmark.export_esp32 --run <run> --output <export>
python -m benchmark.export_esp32 --output <export> --package
```

The exporter uses pyelftools. It replays UART records, reconciles them with the recorded CSV, then exports per-reset values, medians and ranges, firmware hashes and allocated ELF sections. Each point in a summary has five independent reset-level samples. See the result report for per-probe endpoints and scope.
