CONTIKI_PROJECT = euno-probes
all: $(CONTIKI_PROJECT)
TARGET = native
MAKE_NET = MAKE_NET_NULLNET
CONTIKI ?= $(HOME)/eunobench/upstream/contiki-ng-c02eedae
LDFLAGS += -Wl,--wrap=main
include $(CONTIKI)/Makefile.include
