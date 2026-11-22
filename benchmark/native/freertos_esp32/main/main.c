#include <inttypes.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "esp_cpu.h"
#include "esp_idf_version.h"
#include "esp_system.h"
#include "esp_private/esp_clk.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "freertos/timers.h"

#define MAX_WORKERS 100
#define ROUNDS 100
#define STACK_BYTES 1536
#define DELAY_MS 20

static TaskHandle_t coordinator;
static unsigned active_count, finished, handoffs, previous;
static unsigned visits[MAX_WORKERS];
static uint32_t first_cycle, last_cycle;
static unsigned errors;

static uint32_t cycles(void)
{
    return esp_cpu_get_cycle_count();
}

static void worker(void *arg)
{
    const unsigned id = (unsigned)(uintptr_t)arg;
    for (unsigned i = 0; i < ROUNDS; i++) {
        const uint32_t stamp = cycles();
        if (previous == MAX_WORKERS) first_cycle = stamp;
        else if (previous != id) handoffs++;
        previous = id;
        last_cycle = stamp;
        visits[id]++;
        taskYIELD();
    }
    if (++finished == active_count) xTaskNotifyGive(coordinator);
    vTaskSuspend(NULL);
}

static void switch_test(unsigned count)
{
    TaskHandle_t tasks[MAX_WORKERS];
    unsigned created = 0, failures = 0, entries = 0;
    active_count = count;
    finished = handoffs = 0;
    previous = MAX_WORKERS;
    memset(visits, 0, sizeof(visits));
    for (; created < count; created++) {
        if (xTaskCreate(worker, "worker", STACK_BYTES, (void *)(uintptr_t)created,
                        2, &tasks[created]) != pdPASS) break;
    }
    if (created == count && !ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(5000))) failures++;
    for (unsigned i = 0; i < created; i++) {
        entries += visits[i];
        if (visits[i] != ROUNDS) failures++;
        vTaskDelete(tasks[i]);
    }
    if (created != count || finished != count || handoffs < count - 1 || handoffs >= entries) failures++;
    printf("EUNO_SWITCH workers=%u rounds=%u entries=%u handoffs=%u cycles=%" PRIu32 " errors=%u\n",
           count, ROUNDS, entries, handoffs, last_cycle - first_cycle, failures);
    errors += failures;
    vTaskDelay(2);
}

static SemaphoreHandle_t request, reply;
static unsigned observed_round;
static uint32_t peer_entry;

static void peer(void *arg)
{
    (void)arg;
    for (unsigned i = 0; i < 2 * ROUNDS; i++) {
        if (xSemaphoreTake(request, portMAX_DELAY) != pdTRUE) break;
        peer_entry = cycles();
        observed_round++;
        xSemaphoreGive(reply);
    }
    vTaskSuspend(NULL);
}

static void ipc_test(void)
{
    TaskHandle_t task;
    request = xSemaphoreCreateBinary();
    reply = xSemaphoreCreateBinary();
    if (!request || !reply || xTaskCreate(peer, "peer", STACK_BYTES, NULL, 9, &task) != pdPASS) {
        errors++;
        return;
    }
    uint32_t ping_start = 0, wake_sum = 0;
    unsigned failures = 0, rounds = 0;
    for (; rounds < 2 * ROUNDS; rounds++) {
        if (rounds == ROUNDS) ping_start = cycles();
        const uint32_t start = cycles();
        if (xSemaphoreGive(request) != pdTRUE || observed_round != rounds + 1) failures++;
        if (rounds < ROUNDS) wake_sum += peer_entry - start;
        if (xSemaphoreTake(reply, pdMS_TO_TICKS(1000)) != pdTRUE) {
            failures++;
            break;
        }
    }
    const uint32_t ping_cycles = cycles() - ping_start;
    printf("EUNO_IPC wake_rounds=%u ping_rounds=%u wake_cycles=%" PRIu32 " ping_cycles=%" PRIu32 " errors=%u\n",
           rounds < ROUNDS ? rounds : ROUNDS, rounds > ROUNDS ? rounds - ROUNDS : 0,
           wake_sum, ping_cycles, failures);
    vTaskDelete(task);
    vSemaphoreDelete(request);
    vSemaphoreDelete(reply);
    errors += failures;
}

static unsigned callbacks, timer_errors;
static unsigned seen[MAX_WORKERS];
static uint32_t callback_cycles;
static TickType_t expected[MAX_WORKERS];
static int32_t max_offset;

static void timer_callback(TimerHandle_t timer)
{
    const uint32_t start = cycles();
    const unsigned id = (unsigned)(uintptr_t)pvTimerGetTimerID(timer);
    if (id >= active_count) {
        timer_errors++;
        return;
    }
    if (seen[id]++ || xTaskGetCurrentTaskHandle() != xTimerGetTimerDaemonTaskHandle()) timer_errors++;
    const int32_t offset = (int32_t)(xTaskGetTickCount() - expected[id]);
    if (offset > max_offset) max_offset = offset;
    callbacks++;
    if (callbacks == active_count) xTaskNotifyGive(coordinator);
    callback_cycles += cycles() - start;
}

static void timer_test(unsigned count)
{
    TimerHandle_t timers[MAX_WORKERS];
    unsigned created = 0;
    active_count = count;
    callbacks = timer_errors = callback_cycles = 0;
    max_offset = INT32_MIN;
    memset(seen, 0, sizeof(seen));
    for (; created < count; created++) {
        timers[created] = xTimerCreate("euno", pdMS_TO_TICKS(DELAY_MS), pdFALSE,
                                       (void *)(uintptr_t)created, timer_callback);
        if (!timers[created]) break;
    }
    const uint32_t start = cycles();
    if (created == count) {
        for (unsigned i = 0; i < count; i++) {
            expected[i] = xTaskGetTickCount() + pdMS_TO_TICKS(DELAY_MS);
            if (xTimerStart(timers[i], portMAX_DELAY) != pdPASS) timer_errors++;
        }
    }
    const uint32_t arm_cycles = cycles() - start;
    if (created != count || !ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(2000))) timer_errors++;
    for (unsigned i = 0; i < created; i++) {
        if (seen[i] != 1) timer_errors++;
        if (xTimerDelete(timers[i], portMAX_DELAY) != pdPASS) timer_errors++;
    }
    printf("EUNO_TIMER timers=%u delay_ms=%u callbacks=%u arm_cycles=%" PRIu32
           " callback_cycles=%" PRIu32 " max_offset_ticks=%" PRId32 " errors=%u\n",
           count, DELAY_MS, callbacks, arm_cycles, callback_cycles, max_offset, timer_errors);
    errors += timer_errors;
}

void app_main(void)
{
    const int64_t startup_us = esp_timer_get_time();
    printf("EUNO_BOARD os=FreeRTOS idf=%s clock_hz=%d tick_hz=%u core=%d mode=fixed\n",
           esp_get_idf_version(), esp_clk_cpu_freq(), configTICK_RATE_HZ, xPortGetCoreID());
    printf("EUNO_START timer_zero_to_app_us=%" PRId64 "\n", startup_us);
    coordinator = xTaskGetCurrentTaskHandle();
    vTaskPrioritySet(NULL, 8);
    ipc_test();
    const unsigned workers[] = {2, 10, 20, 50, 100};
    const unsigned timers[] = {1, 10, 20, 50, 100};
    for (unsigned i = 0; i < 5; i++) switch_test(workers[i]);
    for (unsigned i = 0; i < 5; i++) timer_test(timers[i]);
    printf("EUNO_DONE errors=%u\n", errors);
    fflush(stdout);
}
