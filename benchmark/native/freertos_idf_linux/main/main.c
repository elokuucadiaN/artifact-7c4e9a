/* Functional reconstruction on ESP-IDF v5.2.5 official Linux port.
 * Not the original ESP-IDF/ESP32 deployment, and not hardware latency evidence.
 */
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/timers.h"
#include "freertos/semphr.h"
#include <stdio.h>
#include <stdint.h>
#include <time.h>
#include <stdlib.h>

static TaskHandle_t coordinator;
static volatile unsigned visits[100], finished, previous, transitions;
static unsigned workers;
static volatile uint64_t first, last;
static volatile unsigned callbacks, seen[100], callback_errors;
static volatile TickType_t max_late;
static int failures;
static uint64_t bootstrap;
static uint64_t boot_start, boot_end, expected[100], body_ns;
static int64_t max_offset;

static uint64_t now(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000000000ull + t.tv_nsec;
}
int __real_main(int argc,const char **argv);
int __wrap_main(int argc,const char **argv){boot_start=now();return __real_main(argc,argv);}
typedef SemaphoreHandle_t more_sem_t;
static unsigned more_bad;
static TaskHandle_t more_task;
static void more_peer(void);
static void more_entry_task(void *p){(void)p;more_peer();}
static void more_init(more_sem_t *s){*s=xSemaphoreCreateBinary();if(!*s)exit(7);}
static void more_wait(more_sem_t *s){if(xSemaphoreTake(*s,pdMS_TO_TICKS(5000))!=pdPASS)more_bad++;}
static void more_post(more_sem_t *s){if(xSemaphoreGive(*s)!=pdPASS)more_bad++;}
static void more_launch(void){if(xTaskCreate(more_entry_task,"more",32768,NULL,9,&more_task)!=pdPASS)exit(7);}
static void more_park(void){vTaskSuspend(NULL);}
static void more_join(void){vTaskDelete(more_task);}
static void more_destroy(more_sem_t *s){vSemaphoreDelete(*s);}
#define more_now now
#define MORE_TAG "FOS"
#include "euno_more.h"

static void worker(void *arg)
{
    unsigned id = (uintptr_t)arg;
    for (unsigned i=0; i<100; i++) {
        if (previous != 1000 && previous != id) transitions++;
        previous=id; visits[id]++;
        if (!first) first=now();
        last=now();
        taskYIELD();
    }
    if (++finished==workers) xTaskNotifyGive(coordinator);
    vTaskSuspend(NULL);
}

static void switch_test(unsigned n)
{
    TaskHandle_t tasks[100];
    workers=n; finished=0; previous=1000; transitions=0; first=0; last=0;
    for (unsigned i=0; i<n; i++) {
        visits[i]=0;
        if (xTaskCreate(worker,"worker",8192,(void *)(uintptr_t)i,2,&tasks[i])!=pdPASS) {
            puts("FOS_FAIL reason=worker_create"); failures++; return;
        }
    }
    unsigned completed=ulTaskNotifyTake(pdTRUE,pdMS_TO_TICKS(10000));
    unsigned entries=0, errors=0;
    for (unsigned i=0; i<n; i++) {
        entries+=visits[i];
        if (visits[i]!=100) errors++;
        vTaskDelete(tasks[i]);
    }
    /* Tick preemption can resume a worker around its explicit yield. Yield-call
     * count therefore is not the count of observed changes of worker identity.
     * Check per-worker work exactly, and preserve the real identity-change count.
     */
    if (!completed || finished!=n || transitions<n-1 || transitions>entries-1) errors++;
    printf("FOS_SWITCH workers=%u rounds=100 entries=%u handoffs=%u same_worker_entries=%u errors=%u elapsed_ns=%llu\n",
           n,entries,transitions,entries-1-transitions,errors,(unsigned long long)(last-first));
    failures+=errors!=0;
}

static void expired(TimerHandle_t timer)
{
    uint64_t begin=now();
    TickType_t native_at_entry=xTaskGetTickCount();
    unsigned id=(uintptr_t)pvTimerGetTimerID(timer);
    if (seen[id]++) callback_errors++;
    if (xTaskGetCurrentTaskHandle()!=xTimerGetTimerDaemonTaskHandle()) callback_errors++;
    TickType_t tick=xTaskGetTickCount(), deadline=xTimerGetExpiryTime(timer);
    if (tick<deadline) callback_errors++;
    else if (tick-deadline>max_late) max_late=tick-deadline;
    if (++callbacks==workers) xTaskNotifyGive(coordinator);
    int64_t offset=(int64_t)(int32_t)(native_at_entry-(TickType_t)expected[id])*(1000000000LL/configTICK_RATE_HZ);
    if(offset>max_offset)max_offset=offset;
    body_ns+=now()-begin;
}

static void timer_test(unsigned n)
{
    TimerHandle_t timers[100];
    callbacks=0; callback_errors=0; max_late=0; workers=n;
    body_ns=0;max_offset=INT64_MIN;
    for (unsigned i=0; i<n; i++) {
        seen[i]=0;
        timers[i]=xTimerCreate("one-shot",20,pdFALSE,(void *)(uintptr_t)i,expired);
        if (!timers[i]) { puts("FOS_FAIL reason=timer_create"); failures++; return; }
    }
    uint64_t start=now();
    for (unsigned i=0; i<n; i++) {
        expected[i]=(TickType_t)(xTaskGetTickCount()+pdMS_TO_TICKS(20));
        if (xTimerStart(timers[i],portMAX_DELAY)!=pdPASS) callback_errors++;
    }
    uint64_t arm=now()-start;
    unsigned completed=ulTaskNotifyTake(pdTRUE,pdMS_TO_TICKS(2000));
    for (unsigned i=0; i<n; i++) {
        if (seen[i]!=1) callback_errors++;
        if (xTimerDelete(timers[i],portMAX_DELAY)!=pdPASS) callback_errors++;
    }
    if (!completed || callbacks!=n) callback_errors++;
    printf("FOS_TIMER timers=%u callbacks=%u errors=%u arm_enqueue_ns=%llu max_late_ticks=%lu context=timer_service_task max_offset_ns=%lld callback_body_ns=%llu deadline_clock=kernel_ticks\n",
           n,callbacks,callback_errors,(unsigned long long)arm,(unsigned long)max_late,(long long)max_offset,(unsigned long long)body_ns);
    failures+=callback_errors!=0;
}

static void run(void *arg)
{
    (void)arg;
    printf("FOS_META os=FreeRTOS version=ESP-IDF-v5.2.5 kernel=%s port=idf_linux tick_hz=1000 hardware_measurement=0\n",tskKERNEL_VERSION_NUMBER);
    printf("FOS_START boundary=app_main_to_coordinator elapsed_ns=%llu\n",(unsigned long long)(now()-bootstrap));
    printf("FOS_MORE_META profile=extended-v2\nFOS_BOOT elapsed_ns=%llu entry=idf_linux_main end=app_main valid=%u\n",(unsigned long long)(boot_end-boot_start),boot_start>0 && boot_end>=boot_start);
    more_tests();
    unsigned ns[]={2,10,20,50,100}, ts[]={1,10,20,50,100};
    for (unsigned i=0;i<5;i++) switch_test(ns[i]);
    for (unsigned i=0;i<5;i++) timer_test(ts[i]);
    printf("FOS_DONE failures=%d\n",failures);
    fflush(stdout);
    exit(failures ? 1:0);
}

void app_main(void)
{
    boot_end=now();
    bootstrap=now();
    if (xTaskCreate(run,"coordinator",32768,NULL,8,&coordinator)!=pdPASS) exit(2);
    vTaskDelete(NULL);
}
