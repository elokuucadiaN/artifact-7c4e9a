# 论文补充稿：系统开销与实时机制测试

> 本稿只描述 Tenon 参考原型，不作为 EunoBench 原有操作系统新增实验的主结果。原系统补测的定义/待测状态以主入口生成的 PAPER_UPDATE.md 为准。

以下文字对应本次已完成的实现和仿真验证，不把 TCG 结果写成真实硬件性能结论。主论文没有可编辑 TeX 源文件，故提供独立补充稿。

## 可加入 Benchmark Scope / Design

We extend EunoBench with a separately scoped set of system-overhead and real-time mechanism measurements inspired by Section 5 of TenonOS. The extension includes same-priority worker scaling, native-timer scaling under fixed-tick and tickless configurations, a bounded initialization interval, and ELF-section accounting. Each metric specifies its operation, measurement endpoints, counter, denominator, applicable execution model, and required completion checks. These mechanism measurements are reported separately from the existing common-task leaderboard.

The worker test varies the number of participating workers over 2, 10, 20, 50, and 100, with extended-context preservation enabled and disabled. The coordinator remains blocked during the measured interval. A shared execution witness checks worker progress and changes of worker identity; elapsed time is divided by verified handoffs rather than yield-call count. The interval includes workload and observation overhead and is not claimed to isolate the scheduler's instruction cost.

The timer test varies the number of native one-shot timers over 1, 10, 20, 50, and 100. Each timer has a twenty-tick native delay and must invoke its callback exactly once. Initialization/start cost, the accumulated C-level timer interrupt-handler interval, and maximum callback lateness are separate quantities. The handler interval excludes architectural interrupt entry and context restoration. The protocol is inspired by TenonOS's timer-scaling evaluation; it does not claim an identical operation to the incompletely specified experiment in its Figure 9.

## 可加入 Implementation / Setup

We implement the extension using the distributed Tenon native priority scheduler, timer services, interrupt controller, and allocator. The original six-case suite is retained as a derived, 64-bit generic-counter workload. We read CNTVCT_EL0 and obtain its frequency from CNTFRQ_EL0; reported counts are not labeled as CPU cycles. Fixed-tick and tickless modes use separate builds and are checked against both resolved Kconfig and guest metadata. The initialization interval starts at the first instrumented C-level ukplat_entry statement and ends at the first main timestamp, excluding earlier architecture setup and physical reset. ELF accounting covers SHF_ALLOC sections of the linked debug ELF and is bound separately to the bootable ARM64 Image; it does not substitute for dynamic peak allocated RAM.

## 已完成的功能验证，可加入 Artifact / Limitations

On a Windows/WSL2 Ubuntu 22.04 x86_64 host, we cross-compile the ARM64 images and execute them under QEMU TCG. All active source files, build directories, boot images, and acquisition logs reside on the native Linux ext4 filesystem under /home/zyc/eunobench. Reports and raw evidence are exported to Windows only after completion and replay, with post-copy hash checks. Three fresh guests per mode complete the registered workload grid: 36 legacy-suite outputs, 60 worker-scaling records, and 30 timer-scaling records in total. Raw guest logs, process envelopes, resolved configurations, build identities, and section records are retained. Offline replay reconstructs all four CSV tables, and negative controls reject changed or missing captures, lost callbacks even after hash rebinding, and mismatched boot images.

This campaign validates executable integration and evidence replay. TCG timer values depend on emulation and host scheduling and therefore do not establish physical-board latency, jitter, interrupt determinism, virtualization overhead, or an OS performance ranking. Hardware power, physical reset-to-ready time, complete interrupt context phases, Mortise/Linux co-location, and new FreeRTOS/Zephyr ports remain unmeasured.

## 可以放入附录的验证表

| 模式 | 独立 guest | 原六项输出 | 线程/ectx 记录 | 定时器记录 | 检查结果 |
| --- | ---: | ---: | ---: | ---: | --- |
| fixed | 3 | 18 | 30 | 15 | 全部完成 |
| tickless | 3 | 18 | 30 | 15 | 全部完成 |
| 合计 | 6 | 36 | 60 | 30 | 离线重放一致 |

这是执行和验证表，不是实际板卡性能表。每个 guest 内的迭代次数不增加独立 guest 的数量。原六项检查支持返回状态与输出完整性，不据此新增独立适配器等价性结论。

对应正式原始证据：`/home/zyc/eunobench/runs/tenon-prototype-nativefs-20261115/`。完成后导出的 Windows 副本：`E:/learn/benchmark/output/tenon-prototype-nativefs-20261115/`。图表 `switches.svg` 和 `timers.svg` 在图内标注仿真用途，建议仅作为工程验证附图；后续硬件数据采集完成前不写入主性能比较结论。
