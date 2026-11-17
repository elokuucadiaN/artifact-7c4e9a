# EunoBench 完整测试报告（2026-11-17）

本次完整测试包含论文版本六 OS 的 native 测量、Zephyr 调度策略与 tick 模式对照，以及 ARM 固件的 QEMU 功能验证。源码、构建与采集在 WSL Linux 文件系统内完成，各组顺序执行。host 时间属于仿真诊断，测试范围和未覆盖的硬件实验见下文。

## 测试范围

- 论文版本六 OS 的 extended-v2 全部测试：18 个独立进程，包含调度规模、timer 规模、指定初始化区间、适用系统的 semaphore 唤醒/往返、原生时钟偏移、callback 体计时、ELF 和声明源码统计。
- Zephyr 3.7.0 三个论文公开策略（DUMB/DUMB、MULTIQ/SCALABLE、SCALABLE/SCALABLE）× fixed/tickless：6 个配置、18 个独立进程。100 Hz、时间片 size/priority 均为 0；每一对解析后配置只差 CONFIG_TICKLESS_KERNEL。
- 各策略配置还核对 100 次 native irq_offload 入口/返回，并测量 sys_clock_announce C 函数内核处理窗口。后者包括 timeout 分发和观测 callback，排除驱动及架构 IRQ 保存/恢复。
- Zephyr 3.7.0 ARM Cortex-M3 mps2/an385 固件交叉编译，3 个全新 QEMU guest 各验证 100 次 IRQ offload、返回后栈 canary、1 次原生 timer callback。ELF/map 与链接器 FLASH/RAM 占用另列。

合计 36 个新 native 进程和 3 个新 QEMU guest。原八配置的 48 条归档标量仅作为原榜单重放输入，未冒充本轮重新实测。

## 测量和归属

固定/无周期 tick 的对照见 paired-mode-summary.csv；ARM 链接器 footprint 见 firmware-footprint.csv；全部记录见 measurements.csv、summary.csv。原四类 Overall 未更改。

native ISR API 入口和 roundtrip 不是硬件中断的保存/分发/恢复三个独立阶段。QEMU 栈 canary 是功能检查，不是完整架构寄存器证明，也没有产生 MCU 实测 cycles。ARM mps2 固件与原 ESP32 工程不同。两种生成的 Zephyr 只重建论文公开调度/等待策略，没有声称恢复作者完整私有工程。

本轮保留每配置 3 个独立进程，不把内部 100 轮或各 timer 个数当作额外独立样本。native deadline offset 保留 OS 时钟域和分辨率；启动入口逐 OS 声明，不含统一物理 reset。源码范围、host ELF 和固件 region 各自归属，不混作 TCB、动态 RAM 或同板 footprint。

## 验证与复现

VALIDATION_CONTROLS.json 包含真实日志负向检查及三组配置差异检查；UNIT_TESTS* 是测试输出。八个核心结果文件由原始输入重放并逐字节核对，完整证据 ZIP 具有文件哈希 manifest。

源码：/home/zyc/eunobench/src/artifact-7c4e9a/benchmark/；采集：<workspace>/runs/full-test-20261117/。入口为 run_native_batch.py、run_zephyr_matrix.py、run_qemu_probe.py。统一入口 eunobench.py evaluate 支持 --native-capture、--zephyr-matrix、--qemu-capture。复现代码和原公开审稿输入已附 reproduction/。

## 仍需外部条件

完整原八 ESP32 部署、作者保存的生成配置/Contiki+IDF 组合工程、物理 reset→ready、硬件 IRQ 完整阶段、板卡能耗与同板性能排名仍未完成。当前无板卡且公开仓库缺少原完整工程，不能把这些项标为通过。Mortise/Linux 共置不自动列为本轮必做项。

本包统一结果计数：

```json
{
  "baseline_configurations": 8,
  "baseline_scalars": 48,
  "registered_metrics": 29,
  "added_metric_contracts": 25,
  "imported_records": 1376,
  "summary_cells": 780,
  "coverage_cells": 609,
  "reference_only_records": 0,
  "original_OS_new_metric_records": 0,
  "reconstructed_native_records": 590,
  "supplemental_records": 738,
  "supplemental_configurations": 7,
  "paper_version_simulator_configurations": 6,
  "native_runtime_records": 408,
  "original_OS_new_measurements_complete": false,
  "new_guests": 0,
  "new_board_measurements": 0,
  "original_overall_policy": "unchanged four categories",
  "measurement_scope": "Original eight archived EunoBench configurations plus separately attributed paper-version simulator captures; new original-board metrics remain pending",
  "pass": true
}
```
