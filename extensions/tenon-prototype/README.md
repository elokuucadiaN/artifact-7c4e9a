# EunoBench：TenonOS Prototype 指标扩展

> 定位更正：本目录是 Tenon 测量方法的参考原型验证，不代表已经在 EunoBench 原有 OS 上补测。正式被测对象与工程准备入口见仓库根目录 benchmark/README.md；原有 OS 的新增实验仍未完成。

本扩展把 TenonOS 第 5 节的部分指标实现为可构建、可运行、可从原始日志重算的测试。目标环境是 **Windows + WSL2 Ubuntu 22.04，x86_64 主机运行 ARM64 QEMU TCG**。

当前交付包含原生 Tenon 的交叉编译与仿真功能验证。**仿真时间不代表真实板卡性能；不进入既有 B1 Overall 排名。** FreeRTOS、Zephyr 的新指标移植、真实冷启动、功耗、Mortise/Linux 共置及完整汇编中断分段仍未测量。

## 直接运行

复用现有 `/home/zyc/eunobench/.venv`，无需重新安装 Python 环境。WSL 中运行：

```bash
cd /home/zyc/eunobench/src/artifact-7c4e9a/extensions/tenon-prototype
/home/zyc/eunobench/.venv/bin/python -B prototype.py doctor
/home/zyc/eunobench/.venv/bin/python -B prototype.py run \
  --output /home/zyc/eunobench/runs/tenon-prototype-my-run \
  --runs 3 --rounds 100 --legacy-iterations 50
```

输出目录必须尚不存在。源码、构建目录、QEMU 读取的镜像、采集中的 stdout/stderr 和报告都必须位于 `/home/zyc/eunobench/` 的 Linux 文件系统。脚本通过真实路径和挂载类型检查，拒绝 `/mnt/e` 等跨文件系统路径及指向它们的符号链接。存储条件保存在 `storage.json`。

脚本创建独立的 Linux 构建目录 `/home/zyc/eunobench/prototype-builds/build-*`，使用项目自带 Tenon 与已修补 TLSF 源码，不下载依赖，不修改原 `artifact/`。**测试全部成功后**再导出：

```bash
/home/zyc/eunobench/.venv/bin/python -B prototype.py export \
  --input /home/zyc/eunobench/runs/tenon-prototype-my-run \
  --output /mnt/e/learn/benchmark/output/tenon-prototype-my-run
```

导出先在 Linux 中重放原始证据，再复制并逐文件核对哈希。Windows 目录只是完成后的副本；正式原始证据留在 WSL。导出记录放在结果目录旁的 `<结果目录>.export.json`，不会改动包内证据清单。

Windows PowerShell 也可以调用；启动器调用 Linux 源码，在 Linux 完成全部测试后才执行导出：

```powershell
& 'E:\learn\benchmark\artifact-7c4e9a-main\extensions\tenon-prototype\run.ps1' `
  -Output 'E:\learn\benchmark\output\tenon-prototype-my-run'
```

正式源码位于 `/home/zyc/eunobench/src/artifact-7c4e9a/`；后续开发与测试均在这里进行。Windows 下保留的源码是便于查看的副本，编辑它不会自动更新 Linux 源码。可选 `--source-root /home/zyc/eunobench/prototype-source-cache` 使用早先的源码缓存；默认读取正式 Linux 源码，推荐使用默认值。每次生成的源码文件身份均保存在 source-manifest.json。

## 已实现的指标

| 指标 | 对应原文 | 本扩展的精确定义 |
| --- | --- | --- |
| 同优先级线程扩展 | §5.2.1 表 4 | 2/10/20/50/100 个参与 worker；协调线程阻塞；每个 worker 执行指定轮数；ectx 开/关分别执行；以真实 worker ID 变化计数 |
| 原有六项测试 | §5.2、§5.3 | 保留原生任务/信号量/IRQ/睡眠路径，派生为 64 位 generic timer 计数版本；逐项检查返回状态及唯一输出 |
| 定时器数量扩展 | §5.2.2 图 9 | 1/10/20/50/100 个原生 one-shot timer；各自延后 20 个原生 tick；每个回调必须恰好执行一次 |
| fixed/tickless 对照 | §5.2.2 图 9 | 两次独立构建，读取解析后的 Kconfig 并与 guest 元数据一致性核对 |
| 定时器建立成本 | 受图 9 启发的新协议 | 一次 IRQ 屏蔽区间内初始化并启动 N 个 timer 的总耗时；不与后续处理成本混为一个数 |
| 定时器 IRQ handler 成本 | 受图 9 启发的新协议 | 从原生 sys_timer_irq_handler C 入口到返回前的累计原始耗时；包括 observer 成本，排除架构级保存/恢复上下文 |
| 定时器迟到量 | 新增辅助正确性指标 | 以每个原生 timer 实际 timeout_tick 为目标，检查没有早触发/重复/遗漏并报告最大迟到量 |
| 初始化耗时 | §5.1.2 表 3 的部分维度 | C 级 ukplat_entry 第一处 hook 至 main 第一条测时语句；不包含更早的架构初始化、QEMU 启动或物理 reset |
| ELF 分段 | §5.1.1 表 1 | 从链接后的 .dbg ELF 列出所有 SHF_ALLOC section，含地址、字节数和权限；与真正启动的 ARM64 Image 分别绑定 |
| 源码规模 | §5.1.1 表 1、2 | 按目录统计分发 Tenon 全源码的 C/汇编物理非空代码行，排除 C 风格注释；包含测试和未链接功能，不声称复现原文 SLoC 范围或 TCB |

所有时间来自 **CNTVCT_EL0**，频率来自 **CNTFRQ_EL0**。输出明确使用 count；转换为 ns 时使用该频率，不使用 24 MHz 常量，不将 generic timer count 称为 CPU cycle。

线程指标区间是首个 worker 入口至最后一次 worker 入口，分母是相邻有效入口的 worker ID 变化次数。它包含循环、计数、测时开销，不是已经扣除全部开销的纯调度器成本。

定时器在同一屏蔽中断区间中启动；tickless 模式读取时钟仍可能前进，各 timer 的实际绝对到期 tick 不保证完全相同。迟到检查使用各自真实 deadline。总 handler 成本包含观察窗口内空 tick 的成本，另存 IRQ 次数；不把它等同单次回调成本。这里的 workload 是明确声明的新协议，不能声称与原文图 9 的未充分定义操作完全一致。

原六项测试的运行检查是原生返回值和输出完整性，不是新增的独立适配器等价性认证。新测试通过不改变原论文覆盖表中其他配置的资格。

## 离线重放与验证

使用生成结果中的真实 stdout、镜像、解析后配置和过程记录重建 CSV，不启动 QEMU：

```bash
/home/zyc/eunobench/.venv/bin/python -B prototype.py replay \
  --input /home/zyc/eunobench/runs/tenon-prototype-nativefs-20261115 \
  --output /home/zyc/eunobench/replays/tenon-prototype-nativefs-replayed
```

重放先核对原始证据清单，再检查镜像/配置/日志绑定、完整实验网格、worker 交接数、回调与 IRQ、两种模式和 guest 完成标记。缺失、改动或重复记录会拒绝。清单用于文件自洽检查，不是外部签名或硬件身份认证。

运行协议的负向控制：

```bash
/home/zyc/eunobench/.venv/bin/python -B -m unittest -v test_protocol
```

对本次真实采集包的 4 项改动/缺失/错误绑定控制：

```bash
EUNO_CAPTURE=/home/zyc/eunobench/runs/tenon-prototype-nativefs-20261115 \
  /home/zyc/eunobench/.venv/bin/python -B -m unittest -v test_evidence
```

测试中的 synthetic fixture 只用于检查解析器拒绝缺失完成标记、丢回调、无 IRQ、无切换、模式错误和计数器重命名等情况，不作为实验结果。

## 输出与阅读顺序

1. `receipt.json`：本轮是否完成、实际 guest 数、仿真范围、未测项。
2. `REPORT.md`：端点和口径解释。
3. `switches.svg`、`timers.svg`：标有仿真用途的趋势图。
4. `switches.csv`、`timers.csv`、`boot.csv`、`legacy-six.csv`：每个独立 guest 的结果。
5. `fixed/guest-*`、`tickless/guest-*`：原始 stdout/stderr、QEMU 命令、退出状态、逐项 verdict。
6. 各模式的 `build/`：编译/配置日志、`runtime.img` 启动镜像、`runtime.elf` 调试 ELF、解析后配置、镜像/配置身份和 `sections.json`。
7. `plan.json`、`source-manifest.json`、`source-lines.json`、`environment.json`、`storage.json`、`evidence.json`：参数、派生修改、来源规模、环境、存储布局与哈希。

构建/运行出错时保留日志与 `failure.json`，没有通过的样本不会被补值为成功，也不会生成声称完整成功的 receipt。

## 与现有 benchmark 集成

扩展注册见 `registry.json`。它与原来 `artifact/current/coverage-index.json` 分开，避免将仿真执行写成新的板卡覆盖或修改 70 格冻结基线。原始评分的入口和输入保持原样。

下一阶段有真实板卡时，应按相同端点实现原生适配器、记录实际时钟/IRQ/部署栈并重新采集。不要直接把 TCG CSV 导入主评分器。新 OS 需要独立验证原生操作，尤其 cooperative Contiki 的不适用项。

本轮没有执行生成模型，不对生成器做新的成功率或成本结论；原 EunoBench 的生成配置记录仍通过它原有的工具重放。

## 结果版本

`tenon-prototype-nativefs-20261115` 为源码、镜像、日志均在 ext4 上生成的验证批次。早先 `tenon-prototype-final` 属于构建在 Linux、QEMU 镜像/日志在 Windows 挂载点的混合布局，保留作历史功能验证。两批时间值不混合汇总，也不据此推导文件系统对 guest 计时的因果影响；若要研究该影响，需使用同一镜像和专门的配对实验。
