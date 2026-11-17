/* Actual Contiki-NG processes and ctimers; no replacement host scheduler. */
#include "contiki.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

PROCESS(coordinator, "Euno coordinator");
AUTOSTART_PROCESSES(&coordinator);
static struct process workers[100];
static struct ctimer timers[100];
static unsigned progress[100], fired[100];
static unsigned count, finished, callbacks, errors, failures, entries, handoffs;
static int last_worker;
static uint64_t started, elapsed;
static uint64_t boot_start,boot_end,expected[100],body_ns;
static int64_t max_offset;
static const unsigned worker_grid[] = {2,10,20,50,100};
static const unsigned timer_grid[] = {1,10,20,50,100};

static uint64_t now_ns(void) {
  struct timespec ts;
  if(clock_gettime(CLOCK_MONOTONIC, &ts)) exit(3);
  return (uint64_t)ts.tv_sec*1000000000ULL+ts.tv_nsec;
}
int __real_main(int argc,char **argv);
int __wrap_main(int argc,char **argv){boot_start=now_ns();return __real_main(argc,argv);}

/* Every invocation recomputes id; persistent state lives outside protothread stack. */
static PT_THREAD(worker(struct pt *process_pt, process_event_t ev, process_data_t data)) {
  int id = (int)(PROCESS_CURRENT()-workers);
  (void)data;
  PROCESS_BEGIN();
  PROCESS_WAIT_EVENT_UNTIL(ev == PROCESS_EVENT_POLL);
  while(progress[id] < 100) {
    if(last_worker >= 0 && last_worker != id) handoffs++;
    last_worker = id;
    entries++;
    progress[id]++;
    process_poll(PROCESS_CURRENT());
    PROCESS_YIELD_UNTIL(ev == PROCESS_EVENT_POLL);
  }
  finished++;
  process_poll(&coordinator);
  PROCESS_END();
}

static void callback(void *arg) {
  uint64_t begin=now_ns();
  clock_time_t native_at_entry=clock_time();
  unsigned id = (unsigned)(uintptr_t)arg;
  /* ctimer restores its owner's process context before invoking callback. */
  if(PROCESS_CURRENT() != &coordinator || id >= count || fired[id]++) errors++;
  callbacks++;
  process_poll(&coordinator);
  int64_t offset=((int64_t)native_at_entry-(int64_t)expected[id])*(1000000000LL/CLOCK_SECOND);
  if(offset>max_offset)max_offset=offset;
  body_ns+=now_ns()-begin;
}

PROCESS_THREAD(coordinator, ev, data) {
  static unsigned stage, i;
  (void)data;
  PROCESS_BEGIN();
  boot_end=now_ns();
  printf("COS_META os=Contiki-NG version=c02eedae clock=host_monotonic_ns model=cooperative_process\n");
  printf("COS_MORE_META profile=extended-v2\nCOS_BOOT elapsed_ns=%llu entry=native_main end=coordinator_process valid=%u\n",(unsigned long long)(boot_end-boot_start),boot_start>0 && boot_end>=boot_start);
  printf("COS_NOT_APPLICABLE metrics=preempt,pingpong reason=no_priority_threads_or_blocking_native_semaphore\n");
  for(stage=0; stage<5; stage++) {
    count=worker_grid[stage];
    memset(workers,0,sizeof(workers));
    memset(progress,0,sizeof(progress));
    finished=entries=handoffs=errors=0;
    last_worker=-1;
    for(i=0;i<count;i++) {
      workers[i].thread=worker;
      workers[i].name="Euno worker";
      process_start(&workers[i],NULL);
    }
    started=now_ns();
    for(i=0;i<count;i++) process_poll(&workers[i]);
    PROCESS_WAIT_EVENT_UNTIL(ev==PROCESS_EVENT_POLL && finished==count);
    elapsed=now_ns()-started;
    for(i=0;i<count;i++) if(progress[i]!=100 || process_is_running(&workers[i])) errors++;
    printf("COS_DISPATCH workers=%u rounds=100 entries=%u handoffs=%u elapsed_ns=%llu errors=%u\n",
      count,entries,handoffs,(unsigned long long)elapsed,errors);
    failures+=errors;
  }
  for(stage=0;stage<5;stage++) {
    count=timer_grid[stage];
    callbacks=errors=0;body_ns=0;max_offset=INT64_MIN;
    memset(fired,0,sizeof(fired));
    started=now_ns();
    for(i=0;i<count;i++){expected[i]=clock_time()+CLOCK_SECOND/50;ctimer_set(&timers[i],CLOCK_SECOND/50,callback,(void *)(uintptr_t)i);}
    elapsed=now_ns()-started;
    PROCESS_WAIT_EVENT_UNTIL(callbacks>=count);
    for(i=0;i<count;i++) if(fired[i]!=1) errors++;
    printf("COS_TIMER timers=%u delay_ms=20 elapsed_ns=%llu callbacks=%u errors=%u context=owner_process max_offset_ns=%lld callback_body_ns=%llu deadline_clock=contiki_clock\n",
      count,(unsigned long long)elapsed,callbacks,errors,(long long)max_offset,(unsigned long long)body_ns);
    failures+=errors;
  }
  printf("COS_DONE failures=%u\n",failures);
  fflush(stdout);
  exit(failures?1:0);
  PROCESS_END();
}
