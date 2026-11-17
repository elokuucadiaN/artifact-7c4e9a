APPLICATION = eunobench_probes
BOARD ?= native64
RIOTBASE ?= $(HOME)/eunobench/upstream/RIOT-dd06b372
USEMODULE += ztimer_usec ztimer_msec core_thread_flags sema
INCLUDES += -I$(EUNO_COMMON)
LINKFLAGS += -Wl,--wrap=kernel_init
CFLAGS += -DMAXTHREADS=128
include $(RIOTBASE)/Makefile.include
