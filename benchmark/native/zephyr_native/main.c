/* Native Zephyr kernel functional probes. Host time is not MCU cycle time. */
#include <zephyr/kernel.h>
#include <stdio.h>
#include <stdint.h>
#include <time.h>

K_THREAD_STACK_ARRAY_DEFINE(stacks,100,4096);
static struct k_thread threads[100];
static struct k_timer timers[100];
K_SEM_DEFINE(done,0,1);
static volatile unsigned visits[100],finished,previous,transitions;
static volatile uint64_t first,last;
static unsigned workers;
static volatile unsigned seen[100],callbacks,errors;
static int failures;
static uint64_t boot_start, boot_end, expected[100], body_ns;
static int64_t max_offset;
extern void nsi_exit(int status);
#ifdef EUNO_MATRIX
extern void euno_matrix_timer_begin(void);
extern void euno_matrix_timer_end(unsigned n);
extern int euno_matrix_irq(void);
#endif

static uint64_t now(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t);
    return (uint64_t)t.tv_sec*1000000000ull+t.tv_nsec;
}
void __real_z_cstart(void);
void __wrap_z_cstart(void) {boot_start=now();__real_z_cstart();}
typedef struct k_sem more_sem_t;
static unsigned more_bad;
static void more_peer(void);
static void more_entry_thread(void *a,void *b,void *c){(void)a;(void)b;(void)c;more_peer();}
static void more_init(more_sem_t *s){k_sem_init(s,0,1);}
static void more_wait(more_sem_t *s){if(k_sem_take(s,K_SECONDS(5)))more_bad++;}
static void more_post(more_sem_t *s){k_sem_give(s);}
static void more_launch(void){k_thread_create(&threads[0],stacks[0],K_THREAD_STACK_SIZEOF(stacks[0]),more_entry_thread,NULL,NULL,NULL,1,0,K_NO_WAIT);}
static void more_park(void){k_thread_suspend(k_current_get());}
static void more_join(void){k_thread_abort(&threads[0]);}
static void more_destroy(more_sem_t *s){(void)s;}
#define more_now now
#define MORE_TAG "ZOS"
#include "euno_more.h"
static void worker(void *arg,void *b,void *c) {
    (void)b;(void)c;unsigned id=(uintptr_t)arg;
    for(unsigned i=0;i<100;i++) {
        if(previous!=1000 && previous!=id)transitions++;
        previous=id;visits[id]++;
        if(!first)first=now();
        last=now();k_yield();
    }
    if(++finished==workers)k_sem_give(&done);
    k_thread_suspend(k_current_get());
}
static void switch_test(unsigned n) {
    workers=n;finished=0;previous=1000;transitions=0;first=0;last=0;
    k_sem_reset(&done);
    for(unsigned i=0;i<n;i++) {
        visits[i]=0;
        k_thread_create(&threads[i],stacks[i],K_THREAD_STACK_SIZEOF(stacks[i]),worker,
                        (void *)(uintptr_t)i,NULL,NULL,5,0,K_NO_WAIT);
    }
    int err=k_sem_take(&done,K_SECONDS(5));unsigned entries=0;
    for(unsigned i=0;i<n;i++) {entries+=visits[i];if(visits[i]!=100)err=1;k_thread_abort(&threads[i]);}
    if(finished!=n || transitions<n-1 || transitions>entries-1)err=1;
    printf("ZOS_SWITCH workers=%u entries=%u handoffs=%u errors=%u elapsed_ns=%llu\n",n,entries,transitions,err!=0,(unsigned long long)(last-first));
    failures+=err!=0;
}
static void expired(struct k_timer *timer) {
    uint64_t begin=now();
    int64_t native_at_entry=k_uptime_get();
    unsigned id=timer-timers;
    if(seen[id]++ || !k_is_in_isr())errors++;
    if(++callbacks==workers)k_sem_give(&done);
    int64_t offset=native_at_entry*1000000LL-(int64_t)expected[id];
    if(offset>max_offset)max_offset=offset;
    body_ns+=now()-begin;
}
static void timer_test(unsigned n) {
    workers=n;callbacks=0;errors=0;k_sem_reset(&done);
    body_ns=0;max_offset=INT64_MIN;
    for(unsigned i=0;i<n;i++){seen[i]=0;k_timer_init(&timers[i],expired,NULL);}
    uint64_t begin=now();
#ifdef EUNO_MATRIX
    euno_matrix_timer_begin();
#endif
    for(unsigned i=0;i<n;i++){expected[i]=(uint64_t)k_uptime_get()*1000000ULL+20000000ULL;k_timer_start(&timers[i],K_MSEC(20),K_NO_WAIT);}
    uint64_t elapsed=now()-begin;
    if(k_sem_take(&done,K_SECONDS(2)))errors++;
#ifdef EUNO_MATRIX
    euno_matrix_timer_end(n);
#endif
    for(unsigned i=0;i<n;i++){if(seen[i]!=1)errors++;k_timer_stop(&timers[i]);}
    printf("ZOS_TIMER timers=%u callbacks=%u errors=%u arm_ns=%llu context=isr max_offset_ns=%lld callback_body_ns=%llu deadline_clock=kernel_uptime\n",n,callbacks,errors,(unsigned long long)elapsed,(long long)max_offset,(unsigned long long)body_ns);
    failures+=errors!=0;
}
int main(void) {
    boot_end=now();
    puts("ZOS_META os=Zephyr version=3.7.0 port=native_sim hardware_measurement=0");
    printf("ZOS_MORE_META profile=extended-v2\nZOS_BOOT elapsed_ns=%llu entry=z_cstart end=benchmark_main valid=%u\n",(unsigned long long)(boot_end-boot_start),boot_start>0 && boot_end>=boot_start);
    more_tests();
#ifdef EUNO_MATRIX
    failures+=euno_matrix_irq();
#endif
    unsigned n[]={2,10,20,50,100},t[]={1,10,20,50,100};
    for(unsigned i=0;i<5;i++)switch_test(n[i]);
    for(unsigned i=0;i<5;i++)timer_test(t[i]);
    printf("ZOS_DONE failures=%d\n",failures);fflush(stdout);nsi_exit(failures?1:0);return failures;
}
