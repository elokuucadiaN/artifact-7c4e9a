APPLICATION = eunobench_probes
BOARD ?= native64
RIOTBASE ?= $(HOME)/eunobench/upstream/RIOT-dd06b372
USEMODULE += ztimer_usec ztimer_msec core_thread_flags sema
INCLUDES += -I$(EUNO_COMMON)
ifeq ($(BOARD),esp32-wroom-32)
CFLAGS += -DEUNO_ESP32 -DCONFIG_ESP32_DEFAULT_CPU_FREQ_MHZ_240=1
DISABLE_MODULE += newlib_nano
FLASH_SIZE = 4
FLASH_MODE = dio
else
LINKFLAGS += -Wl,--wrap=kernel_init
endif
CFLAGS += -DMAXTHREADS=128
include $(RIOTBASE)/Makefile.include
