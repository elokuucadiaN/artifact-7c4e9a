/* RIOT native target functional probes; ztimer clock is not MCU CPU cycles. */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include "thread.h"
#include "thread_flags.h"
#include "ztimer.h"
#include "irq.h"
#include "sema.h"
#include <time.h>

static char stacks[100][THREAD_STACKSIZE_DEFAULT];
static thread_t *coordinator;
static volatile unsigned visits[100],finished,previous,transitions;
static unsigned workers;
static volatile uint32_t first,last;
static ztimer_t timers[100];
static volatile unsigned seen[100],callbacks,errors;
static int failures;
static uint64_t boot_start,boot_end,expected[100],body_ns;
static int64_t max_offset;
static uint64_t host_now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (uint64_t)t.tv_sec*1000000000ULL+t.tv_nsec;}
void __real_kernel_init(void);
void __wrap_kernel_init(void){boot_start=host_now();__real_kernel_init();}
static uint64_t more_now(void){return (uint64_t)ztimer_now(ZTIMER_USEC)*1000ULL;}
typedef sema_t more_sem_t;
static unsigned more_bad;
static void more_peer(void);
static void *more_entry_task(void *p){(void)p;more_peer();return NULL;}
static void more_init(more_sem_t *s){sema_create(s,0);}
static void more_wait(more_sem_t *s){if(sema_wait(s))more_bad++;}
static void more_post(more_sem_t *s){if(sema_post(s))more_bad++;}
static void more_launch(void){if(thread_create(stacks[0],sizeof(stacks[0]),THREAD_PRIORITY_MAIN-1,0,more_entry_task,NULL,"more")<0)exit(7);}
static void more_park(void){}
static void more_join(void){ztimer_sleep(ZTIMER_MSEC,5);}
static void more_destroy(more_sem_t *s){sema_destroy(s);}
#define MORE_TAG "ROS"
#include "euno_more.h"

static void *worker(void *arg) {
    unsigned id=(uintptr_t)arg;
    for(unsigned i=0;i<100;i++) {
        if(previous!=1000 && previous!=id)transitions++;
        previous=id;visits[id]++;
        if(!first)first=ztimer_now(ZTIMER_USEC);
        last=ztimer_now(ZTIMER_USEC);thread_yield();
    }
    if(++finished==workers)thread_flags_set(coordinator,1);
    return NULL;
}
static void switch_test(unsigned n) {
    workers=n;finished=0;previous=1000;transitions=0;first=0;last=0;
    thread_flags_clear(1);
    for(unsigned i=0;i<n;i++) {
        visits[i]=0;
        if(thread_create(stacks[i],sizeof(stacks[i]),THREAD_PRIORITY_MAIN+1,0,worker,(void *)(uintptr_t)i,"euno-worker")<0){puts("ROS_FAIL reason=worker_create");failures++;return;}
    }
    thread_flags_wait_all(1);
    unsigned entries=0,err=0;
    for(unsigned i=0;i<n;i++){entries+=visits[i];if(visits[i]!=100)err++;}
    if(finished!=n || transitions<n-1 || transitions>entries-1)err++;
    printf("ROS_SWITCH workers=%u entries=%u handoffs=%u errors=%u elapsed_us=%lu\n",n,entries,transitions,err,(unsigned long)(uint32_t)(last-first));
    failures+=err!=0;
    /* Allow the last lower-priority worker to return before stack reuse. */
    ztimer_sleep(ZTIMER_MSEC,5);
}
static void expired(void *arg) {
    uint64_t begin=more_now();
    uint32_t native_at_entry=ztimer_now(ZTIMER_MSEC);
    unsigned id=(uintptr_t)arg;
    if(seen[id]++ || !irq_is_in())errors++;
    if(++callbacks==workers)thread_flags_set(coordinator,1);
    int64_t offset=(int64_t)(int32_t)(native_at_entry-(uint32_t)expected[id])*1000000LL;
    if(offset>max_offset)max_offset=offset;
    body_ns+=more_now()-begin;
}
static void timer_test(unsigned n) {
    workers=n;callbacks=0;errors=0;thread_flags_clear(1);
    body_ns=0;max_offset=INT64_MIN;
    for(unsigned i=0;i<n;i++){seen[i]=0;timers[i].callback=expired;timers[i].arg=(void *)(uintptr_t)i;}
    uint32_t start=ztimer_now(ZTIMER_USEC);
    for(unsigned i=0;i<n;i++){expected[i]=(uint32_t)(ztimer_now(ZTIMER_MSEC)+20);ztimer_set(ZTIMER_MSEC,&timers[i],20);}
    uint32_t elapsed=ztimer_now(ZTIMER_USEC)-start;
    thread_flags_wait_all(1);
    for(unsigned i=0;i<n;i++){if(seen[i]!=1)errors++;ztimer_remove(ZTIMER_MSEC,&timers[i]);}
    printf("ROS_TIMER timers=%u callbacks=%u errors=%u arm_us=%lu context=irq max_offset_ns=%lld callback_body_ns=%llu deadline_clock=ztimer_msec\n",n,callbacks,errors,(unsigned long)elapsed,(long long)max_offset,(unsigned long long)body_ns);
    failures+=errors!=0;
}
int main(void) {
    boot_end=host_now();
    coordinator=thread_get_active();
    puts("ROS_META os=RIOT version=dd06b372 port=native64 counter=ztimer_usec hardware_measurement=0");
    printf("ROS_MORE_META profile=extended-v2\nROS_BOOT elapsed_ns=%llu entry=kernel_init end=benchmark_main valid=%u\n",(unsigned long long)(boot_end-boot_start),boot_start>0 && boot_end>=boot_start);
    more_tests();
    unsigned n[]={2,10,20,50,100},t[]={1,10,20,50,100};
    for(unsigned i=0;i<5;i++)switch_test(n[i]);
    for(unsigned i=0;i<5;i++)timer_test(t[i]);
    printf("ROS_DONE failures=%d\n",failures);fflush(stdout);exit(failures?1:0);
}
