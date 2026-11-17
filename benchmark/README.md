# EunoBench 完整测试

本项目将 TenonOS §5 的若干指标接入 EunoBench，实际被测对象为论文版本的 FreeRTOS（ESP-IDF 5.2.5）、Zephyr 3.7.0、NuttX 12.2.1、RIOT dd06b372、AliOS bacc144b、Contiki-NG c02eedae。

2026-11-17 完整测试包含 36 个 native 进程、3 个 ARM QEMU guest；18 个单元测试和 258 个负向检查通过。八个核心数据文件从原始输入重放后逐字节一致。

## 内容

- 六 OS：worker/timer 数量扩展、指定初始化区间、适用的 semaphore 唤醒/往返、native-clock 请求截止偏移、callback C 函数体窗口、ELF 分段及声明源码行数。
- Zephyr 三策略×fixed/tickless：100 Hz，time-slice size/priority=0，每对解析配置只差 tickless 设置；另测 sys_clock_announce 窗口和 native irq_offload 入口/返回。
- Zephyr ARM mps2/an385：交叉编译 ELF/map、链接器 FLASH/RAM 占用，3 个 QEMU guest 验证 IRQ 上下文、返回后 canary 和原生 timer。

## 结果和复现

完整报告及统计见 `results/full-test-20261117/`。Release 提供原始 stdout/stderr、配置、版本身份、源码统计快照、链接镜像和哈希 manifest。保留测量字节与记录绑定，省略不参与结果重放的编译缓存和宿主机活动记录。

在 WSL Linux 工作目录准备 `native/SOURCE_SETUP.md` 所列版本和依赖后运行：

```bash
python -B benchmark/run_native_batch.py --output "$HOME/eunobench/runs/full-test-base"
python -B -m benchmark.run_zephyr_matrix --output "$HOME/eunobench/runs/full-test-matrix"
python -B -m benchmark.run_qemu_probe --output "$HOME/eunobench/runs/full-test-qemu"
python -B eunobench.py evaluate --native-capture "$HOME/eunobench/runs/full-test-base" --zephyr-matrix "$HOME/eunobench/runs/full-test-matrix" --qemu-capture "$HOME/eunobench/runs/full-test-qemu" --output "$HOME/eunobench/results/full-test"
python -B eunobench.py verify --input "$HOME/eunobench/results/full-test"
python -B -m unittest -v benchmark.test_metrics benchmark.test_subjects benchmark.test_versions benchmark.test_source_scope
```

## 范围

完整测试指本项目已实现的上述测试矩阵。host 端口不等于原 ESP32 部署；两种生成的 Zephyr 只重建公开 ready/wait 策略，不声称恢复完整原工程。native irq_offload 和 kernel C 窗口不等于硬件 IRQ 保存/分发/恢复分段。初始化入口逐 OS 声明，不含统一物理 reset；源码子树行数不是 TCB，ARM 固件 footprint 不属于 ESP32。原八配置及板卡启动、完整 IRQ、能耗仍需原工程/硬件，原四类 Overall 不变。
