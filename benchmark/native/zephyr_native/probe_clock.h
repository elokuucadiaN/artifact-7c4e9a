#pragma once
#include <stdint.h>

static inline uint64_t probe_now(void)
{
#ifdef EUNO_ESP32
    return k_cyc_to_ns_floor64(k_cycle_get_32());
#else
    extern uint64_t euno_host_now(void);
    return euno_host_now();
#endif
}
