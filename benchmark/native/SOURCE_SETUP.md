# 源码与依赖

本机工作根目录 `/home/zyc/eunobench`，构建执行位置是 WSL ext4。Windows 只保存已完成导出。现有 `.venv` 保持不变，本轮独立使用 `.venv-os-tests`。

## 源码身份

`version_policy.py` 是六 OS 修订号准入表。FreeRTOS 使用 ESP-IDF 5.2.5 内的内核及 Linux port；不接受上游同号 FreeRTOS 内核替代 IDF fork。Zephyr、RIOT、Contiki 通过官方 GitHub 修订核对镜像仓库 HEAD，运行前要求 tracked source clean。

可从公开镜像获取源码，再校验指定 SHA：

```bash
# 在 /home/zyc/eunobench/upstream 下操作；已有目录不需重复下载。
git clone --depth 1 --branch v5.2.5 https://gitee.com/EspressifSystems/esp-idf.git esp-idf-v5.2.5
git clone --depth 1 --branch v3.7.0 https://gitee.com/zephyr-rtos/zephyr.git zephyr-v3.7.0-mirror
# RIOT 镜像与 Contiki 镜像：fetch 指定修订，不能停留在其他 release。
git init RIOT-dd06b372
git -C RIOT-dd06b372 fetch --depth 1 https://gitee.com/mirrors/riot-os.git dd06b3727c41c2c44bf93f47ff7831fdd501d68b
git -C RIOT-dd06b372 checkout --detach FETCH_HEAD
git init contiki-ng-c02eedae
git -C contiki-ng-c02eedae fetch --depth 1 https://gitee.com/electron/contiki-ng.git c02eedae8b187123069891f81a7111b833701f9c
git -C contiki-ng-c02eedae checkout --detach FETCH_HEAD
```

NuttX 使用 [Apache 12.2.1 发布目录](https://archive.apache.org/dist/nuttx/12.2.1/) 的 `apache-nuttx-12.2.1.tar.gz` 与 `.sha512`。本机完整包名为 `upstream/nuttx-release/apache-nuttx-12.2.1-complete.tar.gz`，已校验官方 SHA-512。构建直接从该包重新解压 kernel，避免只核对版本文本。

NuttX apps 来自官方 `nuttx-12.2.1` tag，commit 为 `86efbcbee77bc0a29af07807080f4804a37f46a3`。本机 `upstream/nuttx-apps-12.2.1` 是完整归档恢复的 Git index，`git write-tree` 必须等于官方 tree `b30115d1758295c009b63d2a038df37779eb0b55`。修改工作树会被拒绝。

AliOS 使用 `upstream/alios-bacc-subset`，从官方固定 commit 获取 Rhino 核心、include、Linux CPU port、Linuxhost 配置及 SoC hooks。`alios_linux/source-files.json` 枚举全部 89 个源文件及其官方 Git blob SHA-1；每个源文件下载后和构建前均校验。可按清单的 `url` 获取文件，并将同一清单保存为该源码根的 `source-identity.json`。不使用自制调度器替代 Rhino。

## 本机依赖

Ubuntu 22.04 上使用 GCC/G++、CMake、Ninja、make、Git、kconfig-frontends、libc6-dev-i386、lib32gcc-11-dev。AliOS Linux 端口按 32 位构建，其他目标为 native64。Python 环境保留 PyYAML、pyelftools、packaging、pykwalify、west，并安装 ESP-IDF 的 core requirements，约束文件来自 [Espressif v5.2 constraints](https://dl.espressif.com/dl/esp-idf/espidf.constraints.v5.2.txt)。

IDF Linux 构建仅选择所需组件。`IDF_SKIP_CHECK_SUBMODULES=1` 避免获取未参与 Linux 构建的 ESP32 bootloader、无线和 MQTT 子模块；实际 freertos 等 tracked sources 仍检查干净。所有环境变量和实际命令保存在 capture 中，不需要 Xtensa 编译器来构建 Linux target。

## 明确的适配变化

- AliOS：仅对生成的 CPU port 副本将私有 `gettid` 改名，解决新 glibc 同名声明冲突；保留原文件及变更前后哈希。禁用 MM debug 时不链接 debug 文件；致命错误 hook 直接令测试失败。应用提供 malloc/free 外观，调度、信号量和定时器仍运行原 Rhino 实现。
- NuttX：使用 NuttX 原生 pthread，避免每个独立 task group 复制三个串口句柄，在 100-worker 档触及 8 位串口 open count 限制。计时仅调用官方 sim host monotonic clock；不替换 NuttX scheduler/timer。预分配 128 个 IRQ signal actions 支持 100 个 POSIX timer 同时到期。
- RIOT：MAXTHREADS=128 支持 100 worker。
- Contiki：使用其 native 进程/事件模型，线程抢占和硬件 IRQ 不由 host 服务代替。

这些是论文版本上的新仿真构建配置；完整原八个 ESP32 部署和两个生成的 Zephyr 工程仍需原配置及硬件。不能把 host ELF 当作 MCU Flash，也不能从本轮 host 时间得出板卡性能排序。
