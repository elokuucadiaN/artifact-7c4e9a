/* New measurement adapter: ARM generic timer counts, never PMU CPU cycles. */
#include "rst_time.h"
#include <stdint.h>
static uint64_t first;
uint64_t euno_counter(void)
{
	uint64_t value;
	__asm__ volatile("isb; mrs %0, cntvct_el0" : "=r"(value) :: "memory");
	return value;
}
uint64_t euno_frequency(void)
{
	uint64_t value;
	__asm__ volatile("mrs %0, cntfrq_el0" : "=r"(value));
	return value;
}
void rst_benchmark_time_init(void) { first = euno_counter(); }
rst_time_t rst_benchmark_time_read(void) { return euno_counter() - first; }
uint64_t rst_time_to_ns(rst_time_t time) { return time; }
const char *rst_time_unit = "count";
