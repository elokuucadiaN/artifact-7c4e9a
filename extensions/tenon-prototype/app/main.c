/* New native Tenon workloads; historical six bodies are generated separately.
 * Single CPU only. Output is a versioned evidence protocol, not a board score.
 */
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <uk/alloc.h>
#include <uk/thread.h>
#include <uk/sched.h>
#include <uk/plat/lcpu.h>
#include <tn/schedprio.h>
#include <tn/timer.h>
#include <tn/systick.h>
#include "rst.h"
#include "rst_ipc.h"
#include "euno_config.h"

extern uint64_t euno_counter(void);
extern uint64_t euno_frequency(void);
static uint64_t boot_start;
static volatile uint64_t timer_irq_count, timer_irq_counts;
static volatile bool observe_timer;
void euno_boot_mark(void) { boot_start = euno_counter(); }
uint64_t euno_timer_irq_begin(void) { return observe_timer ? euno_counter() : 0; }
void euno_timer_irq_end(uint64_t start)
{
	if (start) {
		timer_irq_counts += euno_counter() - start;
		timer_irq_count++;
	}
}

static struct uk_thread *coordinator;
static volatile unsigned entered[100], finished, previous, handoffs, errors;
static volatile uint64_t switch_begin, switch_end;
static unsigned active_workers;

static void worker(void *arg)
{
	unsigned id = (uintptr_t)arg;
	for (unsigned i = 0; i < EUNO_ROUNDS; i++) {
		if (previous == id) errors++;
		if (previous != 1000) handoffs++;
		previous = id;
		entered[id]++;
		if (!switch_begin) switch_begin = euno_counter();
		/* The following entry is the endpoint for a verified worker handoff. */
		switch_end = euno_counter();
		uk_sched_yield();
	}
	if (++finished == active_workers) {
		uk_sched_thread_woken(coordinator);
		uk_sched_reschedule();
	}
	/* Keep the object alive until the coordinator explicitly terminates it. */
	uk_sched_thread_blocked(uk_thread_current(), 0);
	uk_sched_reschedule();
}

static int switches(unsigned n, bool no_ectx)
{
	struct uk_thread *threads[100] = {0};
	active_workers = n; finished = 0; handoffs = 0; errors = 0;
	previous = 1000; switch_begin = 0; switch_end = 0;
	for (unsigned i = 0; i < n; i++) {
		entered[i] = 0;
		threads[i] = uk_thread_create_prio_fn1(uk_alloc_get_default(), worker,
			(void *)(uintptr_t)i, uk_alloc_get_default(), 16384,
			uk_alloc_get_default(), 0, NULL, no_ectx, "euno-worker", 254, NULL, NULL);
		if (!threads[i] || uk_sched_thread_add(uk_sched_get(), threads[i])) {
			printf("EUNO_FAIL case=switch reason=create workers=%u\n", n);
			return 1;
		}
	}
	uk_sched_thread_blocked(coordinator, 0);
	uk_sched_reschedule();
	unsigned total = 0;
	for (unsigned i = 0; i < n; i++) {
		total += entered[i];
		if (entered[i] != EUNO_ROUNDS) errors++;
		uk_sched_thread_terminate(threads[i]);
	}
	printf("EUNO_SWITCH workers=%u ectx=%u rounds=%u entries=%u handoffs=%u errors=%u elapsed_counts=%lu\n",
		n, !no_ectx, EUNO_ROUNDS, total, handoffs, errors,
		(unsigned long)(switch_end - switch_begin));
	return errors || finished != n || handoffs != n * EUNO_ROUNDS - 1;
}

static struct timer timers[100];
static volatile unsigned callbacks, seen[100], timer_errors;
static volatile uint64_t max_late_counts;
static uint64_t expected_count[100];
static void callback(void *arg)
{
	unsigned id = (uintptr_t)arg;
	uint64_t now = euno_counter();
	if (seen[id]++ || now < expected_count[id]) timer_errors++;
	if (now > expected_count[id] && now - expected_count[id] > max_late_counts)
		max_late_counts = now - expected_count[id];
	callbacks++;
}

static int timer_scale(unsigned n)
{
	callbacks = 0; timer_errors = 0; max_late_counts = 0;
	timer_irq_count = 0; timer_irq_counts = 0;
	uint64_t frequency = euno_frequency();
	/* Align all one-shot deadlines while IRQs are masked: one native tick epoch. */
	unsigned long flags = ukplat_lcpu_save_irqf();
	uint64_t begin = euno_counter();
	for (unsigned i = 0; i < n; i++) {
		seen[i] = 0;
		tn_timer_init(&timers[i], 20, callback, (void *)(uintptr_t)i, TN_TIMER_FLAG_ONE_SHOT);
		tn_timer_start(&timers[i]);
		/* systick deadlines are tick aligned, not 20 ms from this read. */
		expected_count[i] = timers[i].timeout_tick * frequency / CONFIG_LIBTNSYSTICK_FREQ;
	}
	uint64_t arm_counts = euno_counter() - begin;
	observe_timer = true;
	ukplat_lcpu_restore_irqf(flags);
	uint64_t deadline = euno_counter() + frequency * 2;
	while (callbacks < n && euno_counter() < deadline)
		__asm__ volatile("yield" ::: "memory");
	flags = ukplat_lcpu_save_irqf();
	observe_timer = false;
	for (unsigned i = 0; i < n; i++) {
		if (seen[i] != 1) timer_errors++;
		/* Remove pending one-shots before leaving on timeout. */
		if (!seen[i]) tn_timer_delete(&timers[i]);
	}
	ukplat_lcpu_restore_irqf(flags);
	printf("EUNO_TIMER timers=%u callbacks=%u errors=%u arm_counts=%lu irq_count=%lu irq_handler_counts=%lu max_late_counts=%lu\n",
		n, callbacks, timer_errors, (unsigned long)arm_counts,
		(unsigned long)timer_irq_count, (unsigned long)timer_irq_counts,
		(unsigned long)max_late_counts);
	return timer_errors || callbacks != n || !timer_irq_count;
}

int main(int argc __unused, char **argv __unused)
{
	uint64_t ready = euno_counter();
	uint64_t read_min = UINT64_MAX;
	coordinator = uk_thread_current();
	tn_sched_thread_set_priority(coordinator, 255);
	for (unsigned i = 0; i < 100; i++) {
		uint64_t a = euno_counter();
		uint64_t b = euno_counter();
		if (b - a < read_min) read_min = b - a;
	}
	printf("EUNO_META schema=1 mode=%s counter=cntvct frequency_hz=%lu tick_hz=%u rounds=%u legacy_iterations=%u\n",
#ifdef CONFIG_LIBTNSYSTICK_TICKLESS
		"tickless",
#else
		"fixed",
#endif
		(unsigned long)euno_frequency(), CONFIG_LIBTNSYSTICK_FREQ, EUNO_ROUNDS, RST_BENCHMARKS_COUNT);
	printf("EUNO_BOOT boundary=ukplat_entry_to_main elapsed_counts=%lu read_min_counts=%lu\n",
		(unsigned long)(ready - boot_start), (unsigned long)read_min);
	int failed = 0;
#define LEGACY(fn, name) do { \
	printf("EUNO_CASE_BEGIN name=%s\n", name); \
	int result = fn(); \
	printf("EUNO_CASE_END name=%s status=%d\n", name, result); \
	if (result) failed++; \
} while (0)
	LEGACY(rst_task_switch_init, "task_switch");
	LEGACY(rst_task_switch_multi_threaded_init, "multi_switch");
	LEGACY(rst_task_preempt_init, "preempt");
	LEGACY(rst_semaphore_shuffle_init, "semaphore_shuffle");
	LEGACY(rst_interrupt_latency_init, "interrupt_entry");
	LEGACY(rst_set_timer_offset_init, "timer_offset");
	unsigned counts[] = {2, 10, 20, 50, 100};
	for (unsigned ectx = 0; ectx < 2; ectx++)
		for (unsigned i = 0; i < 5; i++)
			failed += switches(counts[i], !ectx);
	unsigned timer_counts[] = {1, 10, 20, 50, 100};
	for (unsigned i = 0; i < 5; i++) failed += timer_scale(timer_counts[i]);
	printf("EUNO_DONE failures=%d\n", failed);
	return failed ? 1 : 0;
}
