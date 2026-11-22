# EunoBench ESP32 能耗与复位计时

本轮使用 POWER-Z KM003C 采集 **9 个真板配置、45 次独立复位、21,242 个功率样本**。FreeRTOS、NuttX 和 RIOT 复用上一轮固件。Zephyr 保持同一版本与 Kconfig，修正完成标记后的空闲路径并重新构建六组固件。镜像 SHA-256 见清单。测试仍使用单核 ESP32 及论文固定的 FreeRTOS、Zephyr、NuttX、RIOT 版本。

- [逐次数据](measurements.csv) · [汇总表](summary.csv) · [原探针复测值](probe-measurements.csv) · [固件清单](firmware-manifest.json)
- [采集脚本](../../benchmark/capture_esp32_power.py) · [复核脚本](../../benchmark/export_esp32_power.py)
- [原真板补充实验](https://github.com/elokuucadiaN/artifact-7c4e9a/blob/main/results/esp32-board-20261122/REPORT_CN.md)

## 实测结果

每格为五次独立复位的中位数，最小值和最大值见汇总表。

| 配置 | 复位到应用标记 ms | 应用标记到完成 ms | 应用窗口能量 mJ | 复位到完成 mJ | 空闲功率 mW |
| --- | ---: | ---: | ---: | ---: | ---: |
| freertos | 109.7 | 226.0 | 34.2 | 48.1 | 136.8 |
| nuttx | 84.8 | 329.1 | 75.1 | 86.1 | 192.3 |
| riot | 161.6 | 232.9 | 38.4 | 58.7 | 137.4 |
| zephyr-autoos_policy-fixed | 163.0 | 318.5 | 57.5 | 80.3 | 131.0 |
| zephyr-autoos_policy-tickless | 163.2 | 318.4 | 57.8 | 80.6 | 131.6 |
| zephyr-baseline-fixed | 162.9 | 308.6 | 55.2 | 78.0 | 131.9 |
| zephyr-baseline-tickless | 163.0 | 308.7 | 54.9 | 77.8 | 132.0 |
| zephyr-qwen_policy-fixed | 162.9 | 218.7 | 37.4 | 60.5 | 132.5 |
| zephyr-qwen_policy-tickless | 163.1 | 218.5 | 37.4 | 60.0 | 132.7 |

## 测量窗口与口径

- 供电通过 KM003C 主口进入 ESP32，电脑通过侧面 HID 数据线读取功率计。串口 115200 baud，RTS 控制板上复位。两个串口使用同一个 Windows 单调时钟。试采 VBUS 约 5.07 V，串口回执与原始功率包均随各次复位保存。
- 电压和电流来自同一 POWER-Z 响应，采样时间取查询与返回时间的中点。全批次采用固定极性 -1，保留原始带符号电流。功率用 V×I，能量按相邻采样作梯形积分，区间边界线性插值。本批次复位到完成和空闲窗口的最长采样间隔为 34.0 ms。仪表使用出厂校准，未在本次实验中做外部校验。
- 复位时间起点为主机完成 RTS 解除，终点为接收应用身份标记的完整一行。时间包含 USB 串口接收和输出排队。物理上电到首任务调度的精确时间需要独立的电气触发和观测信号。
- 应用窗口从固件身份标记收到至测试完成标记收到。串口输出、调度、定时器、整板供电都在观测边界内，各应用情境和运行时间需要与能量一起阅读。空闲功率取完成后 0.5–3.0 s 的平均值，包含板上电源转换、指示灯和串口芯片的负载。
- 上一轮 Zephyr 日志在任务完成标记后出现 CPU 异常。该批记录仅覆盖标记之前的负载。本轮修正后在整个空闲功率窗口继续检查串口异常，并使用新固件重新采集。
- 此实验衡量补充测试套件在 USB 板级输入端的能量。论文 B1 的单位任务能耗需要原公共任务、网络条件及同块参考固件，沿用原论文数据。
- TenonOS 图 8 的架构级 IRQ 分段、AliOS Things 的 ESP32 固件及 Mortise/Linux 共置仍待补测。

在证据包的 source 目录下，用已安装 pySerial 的 Python 运行 python -B -m benchmark.export_esp32_power <证据目录>，可重新校验功率包、串口事件和积分。
