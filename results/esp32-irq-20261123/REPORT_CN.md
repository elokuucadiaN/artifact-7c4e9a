# EunoBench ESP32 硬件 IRQ 分段

在 ESP32-D0WDQ6 rev 1.1 上使用 Zephyr 3.7.0 单核基线内核，固定节拍和 tickless 各采集五次独立复位，每次 512 个硬件中断，合计 **5120 个硬件 IRQ**。每次复位还记录了 128 个计数器读数与存储校准样本。

硬件 IRQ 由 Xtensa CCOMPARE1 和 IRQ 15 触发，优先级为 3。固件核对挂起位、比较寄存器和执行次数，Zephyr 系统定时仍使用 CCOMPARE0。所有周期来自同核 240 MHz CCOUNT，串口在采样完毕后输出记录。

- [TenonOS §5.2.1 图 8](https://arxiv.org/pdf/2512.00400#page=31)
- [全部 IRQ 样本](irq-samples.csv) · [独立复位统计](per-reset.csv) · [汇总表](summary.csv) · [校准样本](calibration.csv)
- [测点补丁](zephyr-irq.patch) · [固件身份](firmware.json) · [构建脚本](../../benchmark/build_zephyr_irq.py)

## 实测结果

每格为五个复位中位数的中位数。括号给出复位中位数的最小值和最大值，单位是 CPU 周期。

| 测量区间 | fixed-tick | tickless |
| --- | ---: | ---: |
| 上下文保存观测段 | 75（75–75） | 75（75–75） |
| ISR 分派至 C 处理器测点 | 120（120–120） | 120（120–120） |
| 上下文恢复观测段 | 67（67–67） | 67（67–67） |
| 硬件比较到入口测点 | 17（17–17） | 17（17–17） |
| ISR 本体 | 35（35–35） | 35（35–35） |
| ISR 结束到恢复例程 | 87（87–87） | 87（87–87） |
| 恢复尾部到线程观测 | 33（33–33） | 33（33–33） |
| CCOUNT 读数与存储校准 | 2（2–2） | 2（2–2） |

## 三段的测点

- 保存从中断入口已压入 A0/A2/A3 时读数，到保存高位通用寄存器返回时读数。最初的向量跳转、栈指针调整和三次压栈处于这个窗口之前。
- 分派从保存完成到 C ISR 内首个计时读数，涵盖切换中断栈、查找与跳转，以及 C ABI 入口。
- 恢复从匹配同一栈帧的恢复例程入口，到完成高位寄存器和特殊寄存器恢复后的读数。最后三次寄存器装载、栈指针恢复、RFI 和线程轮询观察属于单列的恢复尾部。ISR 返回、嵌套计数维护及选择恢复的线程也单列。

测量使用带汇编插桩的 ESP32 移植，并启用短中断向量跳板为测点留出空间。校准区间以两次 CCOUNT 读取夹一次存储；它给出读数与存储的局部开销，原始值保留各测点及其分支的影响。图 8 用于定义分段，表中周期对应本机 Xtensa、优先级 3、当前固件和明确的观测端点。

## 复现

在具有已固定 Zephyr 和工具链的 WSL 环境，运行 python -B -m benchmark.build_zephyr_irq --output <构建目录>。用固件清单中的镜像烧录 ESP32。Windows 采集命令为 python -B -m benchmark.capture_esp32_irq --port COM6 --mode fixed --output <证据目录>/captures/fixed。tickless 镜像使用对应模式。证据包的 source 目录可运行 python -B -m benchmark.capture_esp32_irq --output <证据目录>，从原始串口日志复核全部样本。
