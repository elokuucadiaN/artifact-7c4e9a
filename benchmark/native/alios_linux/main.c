/* Rhino task/semaphore/timer APIs on the upstream Linux CPU port. */
#include <k_api.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
static ktask_t coordinator, workers[100];
static cpu_stack_t main_stack[4096], worker_stacks[100][256];
static ktimer_t timers[100];
static ksem_t done;
static unsigned progress[100], fired[100], callbacks, errors, failures, entries, handoffs, count;
static int previous;
static uint64_t first_ns,last_ns;
static uint64_t boot_start,boot_end,expected[100],body_ns;
static int64_t max_offset;
static const unsigned wg[]={2,10,20,50,100},tg[]={1,10,20,50,100};
extern void cpu_tmr_sync(void);
/* Fail-stop diagnostic hook replaces the unlinked AliOS debug component. */
void debug_fatal_error(kstat_t err, char *file, int line) {
  fprintf(stderr,"AOS_FAIL fatal=%d at=%s:%d\n",err,file,line);exit(5);
}
void *aos_malloc(unsigned int n) {return malloc(n);}
void aos_free(void *p) {free(p);}
static uint64_t now_ns(void) {struct timespec t; if(clock_gettime(CLOCK_MONOTONIC,&t)) exit(3);return (uint64_t)t.tv_sec*1000000000ULL+t.tv_nsec;}
static void ok(kstat_t r) {if(r!=RHINO_SUCCESS) {printf("AOS_FAIL status=%d\n",r);fflush(stdout);exit(2);}}
typedef ksem_t more_sem_t;
static unsigned more_bad;
static ktask_t more_task;
static cpu_stack_t more_stack[4096];
static void more_peer(void);
static void more_entry_task(void *p){(void)p;more_peer();}
static void more_init(more_sem_t *s){ok(krhino_sem_create(s,"more",0));}
static void more_wait(more_sem_t *s){ok(krhino_sem_take(s,RHINO_WAIT_FOREVER));}
static void more_post(more_sem_t *s){ok(krhino_sem_give(s));}
static void more_launch(void){ok(krhino_task_create(&more_task,"more",NULL,9,0,more_stack,4096,more_entry_task,1));}
static void more_park(void){ok(krhino_task_suspend(krhino_cur_task_get()));}
static void more_join(void){ok(krhino_task_del(&more_task));}
static void more_destroy(more_sem_t *s){ok(krhino_sem_del(s));}
#define more_now now_ns
#define MORE_TAG "AOS"
#include "euno_more.h"
static void worker(void *arg) {
  unsigned id=(unsigned)(uintptr_t)arg;
  for(unsigned r=0;r<100;r++) {
    uint64_t stamp=now_ns();
    if(!entries)first_ns=stamp;
    if(previous>=0 && previous!=(int)id)handoffs++;
    previous=id;entries++;progress[id]++;last_ns=stamp;
    ok(krhino_task_yield());
  }
  ok(krhino_sem_give(&done));
  ok(krhino_task_suspend(krhino_cur_task_get()));
  exit(4);
}
static void callback(void *timer,void *arg) {
  uint64_t begin=now_ns();
  sys_time_t native_at_entry=krhino_sys_tick_get();
  unsigned id=(unsigned)(uintptr_t)arg;
  if(id>=count || timer!=&timers[id] || strcmp(krhino_cur_task_get()->task_name,"timer_task") || fired[id]++) errors++;
  callbacks++;
  if(callbacks==count)ok(krhino_sem_give(&done));
  int64_t offset=((int64_t)native_at_entry-(int64_t)expected[id])*(1000000000LL/RHINO_CONFIG_TICKS_PER_SECOND);
  if(offset>max_offset)max_offset=offset;
  body_ns+=now_ns()-begin;
}
static void main_task(void *arg) {
  boot_end=now_ns();
  (void)arg;
  puts("AOS_META os=AliOS version=bacc144b clock=host_monotonic_ns cpus=1");
  printf("AOS_MORE_META profile=extended-v2\nAOS_BOOT elapsed_ns=%llu entry=benchmark_main_before_krhino_init end=coordinator_task valid=%u\n",(unsigned long long)(boot_end-boot_start),boot_start>0 && boot_end>=boot_start);
  more_tests();
  ok(krhino_sem_create(&done,"done",0));
  for(unsigned g=0;g<5;g++) {
    count=wg[g];entries=handoffs=errors=0;previous=-1;
    memset(progress,0,sizeof(progress));
    for(unsigned i=0;i<count;i++)ok(krhino_task_create(&workers[i],"worker",(void *)(uintptr_t)i,20,0,worker_stacks[i],256,worker,1));
    for(unsigned i=0;i<count;i++)ok(krhino_sem_take(&done,RHINO_WAIT_FOREVER));
    ok(krhino_task_sleep(1));
    for(unsigned i=0;i<count;i++) {if(progress[i]!=100)errors++;ok(krhino_task_del(&workers[i]));}
    printf("AOS_SWITCH workers=%u rounds=100 entries=%u handoffs=%u elapsed_ns=%llu errors=%u\n",count,entries,handoffs,(unsigned long long)(last_ns-first_ns),errors);
    failures+=errors;
  }
  for(unsigned g=0;g<5;g++) {
    count=tg[g];callbacks=errors=0;memset(fired,0,sizeof(fired));body_ns=0;max_offset=INT64_MIN;
    for(unsigned i=0;i<count;i++)ok(krhino_timer_create(&timers[i],"probe",callback,20,0,(void *)(uintptr_t)i,0));
    uint64_t start=now_ns();
    for(unsigned i=0;i<count;i++){expected[i]=krhino_sys_tick_get()+20;ok(krhino_timer_start(&timers[i]));}
    uint64_t elapsed=now_ns()-start;
    ok(krhino_sem_take(&done,RHINO_WAIT_FOREVER));
    for(unsigned i=0;i<count;i++){if(fired[i]!=1)errors++;ok(krhino_timer_del(&timers[i]));}
    printf("AOS_TIMER timers=%u delay_ms=20 arm_ns=%llu callbacks=%u errors=%u context=timer_task max_offset_ns=%lld callback_body_ns=%llu deadline_clock=kernel_ticks\n",count,(unsigned long long)elapsed,callbacks,errors,(long long)max_offset,(unsigned long long)body_ns);
    failures+=errors;
  }
  printf("AOS_DONE failures=%u\n",failures);fflush(stdout);exit(failures?1:0);
}
int main(void) {
  boot_start=now_ns();
  setvbuf(stdout,NULL,_IONBF,0);
  ok(krhino_init());
  ok(krhino_task_create(&coordinator,"coordinator",NULL,10,0,main_stack,4096,main_task,1));
  cpu_tmr_sync();
  ok(krhino_start());return 3;
}
