/* EunoBench native adapter contract; implementations require real target SDKs.
 * This header is an interface, not a completed OS port or evidence of execution.
 */
#ifndef EUNO_OS_ADAPTER_H
#define EUNO_OS_ADAPTER_H
#include <stddef.h>
#include <stdint.h>

enum euno_status { EUNO_OK, EUNO_UNSUPPORTED, EUNO_RESOURCE_EXHAUSTED, EUNO_NATIVE_ERROR };
enum euno_callback_context { EUNO_ISR_CONTEXT, EUNO_SERVICE_THREAD_CONTEXT, EUNO_EVENT_LOOP_CONTEXT };
typedef void *euno_thread;
typedef void *euno_timer;
typedef void (*euno_entry)(void *);

struct euno_native_binding {
    const char *configuration_id;
    const char *native_kernel_provider;
    const char *tested_component; /* e.g. native kernel, FreeRTOS host, Contiki process loop */
    const char *resolved_config_sha256;
    const char *context_profile; /* original native setting; ARM ectx is not universal */
    enum euno_callback_context timer_context;
    unsigned preemptive_workers_supported;
    unsigned fixed_tick_supported;
    unsigned tickless_supported;
};

/* read_counter must be monotonic under IRQ masking and bound to the real clock.
 * Do not label generic ticks as CPU cycles; declare wrap and conversion policy.
 */
uint64_t euno_read_counter(void);
uint64_t euno_counter_hz(void);
uintptr_t euno_native_irq_save(void);
void euno_native_irq_restore(uintptr_t state);

/* Must use target-owned stackful workers, not adapter-owned scheduling queues.
 * Priority direction and stack-size units must be translated explicitly.
 */
enum euno_status euno_native_thread_create(euno_thread *out, euno_entry entry,
                                         void *arg, unsigned priority, size_t stack_bytes);
void euno_native_thread_yield(void);
void euno_native_thread_block_self(void);
enum euno_status euno_native_thread_wake(euno_thread thread);
enum euno_status euno_native_thread_destroy(euno_thread thread);

/* callbacks must be native scheduled callbacks. Capture each actual deadline;
 * IRQ and service-thread execution costs are distinct metric boundaries.
 */
enum euno_status euno_native_timer_create(euno_timer *out, euno_entry callback, void *arg);
enum euno_status euno_native_timer_start(euno_timer timer, uint64_t native_delay_ticks);
enum euno_status euno_native_timer_cancel(euno_timer timer);
enum euno_status euno_native_timer_destroy(euno_timer timer);

/* Startup endpoint must be explicitly named: physical reset, kernel entry, or
 * first application instruction. All these endpoints are different quantities.
 */
void euno_record_startup_marker(const char *boundary, uint64_t counter);
#endif
