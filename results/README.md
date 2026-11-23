# EunoBench ESP32 实测数据

三轮实验均使用 ESP32 实体板。报告给出操作系统版本、测试固件、测点、重复次数和各项测量的适用范围。

| 实验 | 覆盖 | 报告和数据 | 原始证据 |
| --- | --- | --- | --- |
| 硬件 IRQ 分段 | Zephyr 3.7.0 的 fixed-tick、tickless 基线各五次复位，共 5120 个硬件中断 | [报告](esp32-irq-20261123/REPORT_CN.md) · [汇总](esp32-irq-20261123/summary.csv) · [逐次采样](esp32-irq-20261123/irq-samples.csv) | [IRQ 证据包](https://github.com/elokuucadiaN/artifact-7c4e9a/releases/tag/esp32-irq-20261123) |
| 板级能耗与复位计时 | FreeRTOS、Zephyr、NuttX、RIOT 共九个配置和 45 次复位，21,242 个功率样本 | [报告](esp32-power-20261122/REPORT_CN.md) · [汇总](esp32-power-20261122/summary.csv) · [原探针复测](esp32-power-20261122/probe-measurements.csv) | [能耗证据包](https://github.com/elokuucadiaN/artifact-7c4e9a/releases/tag/esp32-power-20261122) |
| 基础机制与镜像分段 | 同优先级线程扩展、优先级唤醒、信号量往返、定时器规模、Zephyr 原生 IRQ offload 和 ELF 分段 | [报告](esp32-board-20261122/REPORT_CN.md) · [汇总](esp32-board-20261122/summary.csv) · [ELF 分段](esp32-board-20261122/elf-sections.csv) | [基础证据包](https://github.com/elokuucadiaN/artifact-7c4e9a/releases/tag/esp32-board-20261122) |

Zephyr 基础测试的完成标记之后曾出现 CPU 异常。能耗批次修正了结束路径并重新采集了线程、IPC、定时器和原生 IRQ offload，复核这些指标时优先使用该批次的原探针复测表。硬件 IRQ 分段使用单独的插桩固件，通过 CCOMPARE1 触发。

[固件构建和采集说明](../benchmark/ESP32.md)
