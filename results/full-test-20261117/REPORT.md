# EunoBench unified results

The same EunoBench metric layer contains the original common-task measurements and the TenonOS-inspired additions.

## Existing common-task leaderboard

Recomputed by the original replay/production numerical functions. Eight B1 deployment configurations, 48 archived scalars, 235 preference profiles. The original four-category Overall policy is preserved.

| Configuration | Overall | Rank |
| --- | ---: | ---: |
| AliOS Things | 1.0581 | 1 |
| FreeRTOS | 1.0000 | 2 |
| Contiki-NG + ESP-IDF/FreeRTOS | 0.9916 | 3 |
| RIOT | 0.9203 | 4 |
| Zephyr (AutoOS-adapted) | 0.8970 | 5 |
| Zephyr C2-1 (Qwen) | 0.8945 | 6 |
| Zephyr | 0.8910 | 7 |
| NuttX | 0.7884 | 8 |

## Registered system-overhead and real-time metrics

The original eight B1 deployments remain the board subjects. Reconstructed configurations of the same OS families are separately registered for functional testing. TenonOS supplies metric references. Reconstructed simulator records do not fill original ESP32 cells.

| Metric | Reference | Unit | B1 configurations with data | Simulator configurations with data |
| --- | --- | --- | ---: | ---: |
| Linked section size | TenonOS §5.1.1 Table 1 | byte | 0 | 12 |
| Allocated ELF section total | TenonOS §5.1.1 Table 1 | byte | 0 | 12 |
| Kernel initialization interval | TenonOS §5.1.2 Table 3 (partial boundary) | ns | 0 | 0 |
| Native simulator initialization interval | TenonOS §5.1.2 inspired; port-specific C entry boundary | ns | 0 | 6 |
| Semaphore release to higher-priority entry | TenonOS §5.2.1 Table 5 inspired new endpoint pair | ns/wakeup | 0 | 5 |
| Native semaphore roundtrip | TenonOS §5.3 Table 6 inspired new protocol | ns/roundtrip | 0 | 5 |
| Verified worker handoff | TenonOS §5.2.1 Table 4 inspired | ns/handoff | 0 | 11 |
| Cooperative process dispatch window | TenonOS scaling inspired; separate cooperative-model contract | ns/handoff | 0 | 1 |
| Two-task switching | TenonOS six-case body | ns | 0 | 0 |
| Legacy multi-task switching | TenonOS six-case body | ns | 0 | 0 |
| Legacy preemption loop | TenonOS §5.2.1 Table 5 inspired | ns | 0 | 0 |
| Semaphore shuffle | TenonOS §5.3 Table 6 inspired | ns | 0 | 0 |
| IRQ entry response | TenonOS §5.2.1 Figure 8 (different boundary) | ns | 0 | 0 |
| Wakeup deviation under IRQ masking | TenonOS original timer-offset body | ns | 0 | 0 |
| Native timer arm cost | TenonOS §5.2.2 Figure 9 inspired new protocol | ns | 0 | 0 |
| Preallocated timer start API window | TenonOS §5.2.2 Figure 9 inspired cross-OS protocol | ns | 0 | 12 |
| Maximum requested-deadline deviation | TenonOS timer scaling auxiliary endpoint | ns | 0 | 12 |
| Observed callback C-body total | TenonOS §5.2.2 inspired; smaller explicit boundary | ns | 0 | 12 |
| Timer handler window cost | TenonOS §5.2.2 Figure 9 inspired new protocol | ns | 0 | 0 |
| Kernel tick/timeout processing window | TenonOS Figure 9 inspired explicit kernel boundary | ns | 0 | 6 |
| Native software IRQ API to ISR entry | TenonOS Figure 8 inspired partial boundary | ns/interrupt | 0 | 6 |
| Native software IRQ API roundtrip | TenonOS Figure 8 inspired aggregate boundary | ns/interrupt | 0 | 6 |
| Linked firmware memory-region use | TenonOS Table 1 inspired target ELF descriptor | byte | 0 | 0 |
| Maximum callback lateness | Auxiliary validation of timer scaling | ns | 0 | 0 |
| Source physical code lines | TenonOS §5.1.1 Tables 1–2 (different source scope) | line | 0 | 6 |

**Status: 12 paper-version host configurations verified in 36 independent processes for the selected native probes. New measurements on the original eight ESP32 B1 deployments remain pending.**

## Measurement and coverage outputs

- `measurements.jsonl` / `measurements.csv`: one common record schema for all imported quantities, with units, parameters, statistical units and evidence/image/config bindings.
- `summary.csv`: per-configuration, per-parameter summaries. It never pools board/TCG records or counts static sizes and archived aggregates as fresh guests.
- `metric-coverage.csv`: all registered metrics across every registered configuration, including unmeasured and inapplicable cells.
- `legacy-coverage.csv`: original 70-cell workload coverage, preserved separately from new metric acquisition status.
- `catalog.json` / `metric-definitions.csv`: operations, endpoints, denominators, units and paper references.
- `eunobench-new-metrics.tex`: generated paper table; `PAPER_UPDATE.md`: implementation/status text.

Native reconstruction captures are admitted only when their source revisions match the EunoBench paper. Each admitted family has three independent processes, five worker counts and five timer counts, plus one static linked ELF. Contiki cooperative dispatch is a separate contract from stackful worker switching. Timer callback contexts remain OS-specific.

Extended-v2 captures additionally verify port-specific native C-entry startup, semaphore release-to-higher-priority entry, native semaphore request/ack roundtrips, native-clock requested-deadline offset and benchmark C-callback-body windows. Contiki priority-thread tests are inapplicable. Deadline offsets stay in their declared OS clock domain; zero at tick resolution is not zero hardware latency. Declared source-scope C/header lines are replayed from hashed source snapshots and are not TCB size.

The legacy six test bodies already existed in EunoBench. Their new generic-counter profile and the new scaling dimensions are not described as first ports.

No new hardware performance, physical reset-to-ready, energy, Mortise co-location or full architectural ISR phase measurement is claimed. New metrics have not been assigned unmeasured values or silently added to Overall.

Registered metrics: 29; configurations/source objects: 21; measurement records: 1376; summary cells: 780.
