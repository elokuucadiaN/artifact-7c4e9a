/* Actual NuttX scheduler and POSIX timer implementation in the 12.2.1 simulator. */
#include <nuttx/config.h>
#include <sys/boardctl.h>
#include <nuttx/sched.h>
#include <sched.h>
#include <pthread.h>
#include <semaphore.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <errno.h>
/* Upstream sim_internal.h host clock: observation only, not a host timer substitute. */
extern uint64_t host_gettime(bool rtc);
static uint64_t native_now(void){struct timespec t;if(clock_gettime(CLOCK_MONOTONIC,&t))boardctl(BOARDIOC_POWEROFF,8);return (uint64_t)t.tv_sec*1000000000ULL+t.tv_nsec;}
static sem_t done;
static unsigned progress[100],entries,handoffs,failures;
static volatile sig_atomic_t fired[100],count,callbacks,errors;
static int previous;
static uint64_t first,last;
static uint64_t boot_start,boot_end;
static unsigned boot_seen;
static volatile uint64_t expected[100],body_ns;
static volatile int64_t max_offset;
static pthread_t tasks[100];
static pid_t coordinator_pid;
static timer_t timers[100];
static const unsigned wg[]={2,10,20,50,100},tg[]={1,10,20,50,100};
static void fail(const char *reason) {printf("NOS_FAIL reason=%s errno=%d\n",reason,errno);fflush(stdout);boardctl(BOARDIOC_POWEROFF,2);}
static void wait_done(void) {while(sem_wait(&done)<0)if(errno!=EINTR)fail("sem_wait");}
void __real_nx_start(void);
void __wrap_nx_start(void){boot_start=host_gettime(false);boot_seen=1;__real_nx_start();}
typedef sem_t more_sem_t;
static unsigned more_bad;
static pthread_t more_task;
static void more_peer(void);
static void *more_entry_task(void *p){(void)p;more_peer();return NULL;}
static void more_init(more_sem_t *s){if(sem_init(s,0,0))fail("more_init");}
static void more_wait(more_sem_t *s){while(sem_wait(s)<0)if(errno!=EINTR)fail("more_wait");}
static void more_post(more_sem_t *s){if(sem_post(s))fail("more_post");}
static void more_launch(void){
  pthread_attr_t a;struct sched_param p={130};
  if(pthread_attr_init(&a) || pthread_attr_setstacksize(&a,8192) || pthread_attr_setinheritsched(&a,PTHREAD_EXPLICIT_SCHED) || pthread_attr_setschedparam(&a,&p) || pthread_create(&more_task,&a,more_entry_task,NULL))fail("more_create");
  pthread_attr_destroy(&a);
}
static void more_park(void){}
static void more_join(void){if(pthread_join(more_task,NULL))fail("more_join");}
static void more_destroy(more_sem_t *s){if(sem_destroy(s))fail("more_destroy");}
static uint64_t more_now(void){return host_gettime(false);}
#define MORE_TAG "NOS"
#include "euno_more.h"
static void *worker(void *arg) {
  unsigned id=(unsigned)(uintptr_t)arg;
  for(unsigned r=0;r<100;r++) {
    uint64_t stamp=host_gettime(false);
    if(!entries)first=stamp;
    if(previous>=0 && previous!=(int)id)handoffs++;
    previous=id;entries++;progress[id]++;last=stamp;
    sched_yield();
  }
  if(sem_post(&done))fail("sem_post");
  return NULL;
}
static void callback(int signo,siginfo_t *info,void *ctx) {
  uint64_t begin=host_gettime(false);
  uint64_t native_at_entry=native_now();
  (void)ctx;
  unsigned id=(unsigned)info->si_value.sival_int;
  if(signo!=SIGRTMIN || info->si_code!=SI_TIMER || getpid()!=coordinator_pid || id>=count || fired[id]++)errors++;
  callbacks++;
  if(callbacks==count && sem_post(&done))fail("callback_sem");
  int64_t offset=(int64_t)native_at_entry-(int64_t)expected[id];
  if(offset>max_offset)max_offset=offset;
  body_ns+=host_gettime(false)-begin;
}
int euno_main(int argc,char **argv) {
  boot_end=host_gettime(false);
  (void)argc;(void)argv;
  puts("NOS_META os=NuttX version=12.2.1 clock=sim_host_monotonic_ns");
  printf("NOS_MORE_META profile=extended-v2\nNOS_BOOT elapsed_ns=%llu entry=nx_start end=euno_main valid=%u\n",(unsigned long long)(boot_end-boot_start),boot_seen && boot_end>=boot_start);
  more_tests();
  coordinator_pid=getpid();
  if(sem_init(&done,0,0))fail("sem_init");
  for(unsigned g=0;g<5;g++) {
    count=wg[g];entries=handoffs=errors=0;previous=-1;memset(progress,0,sizeof(progress));
    pthread_attr_t attr;struct sched_param priority={100};
    if(pthread_attr_init(&attr) || pthread_attr_setstacksize(&attr,4096) || pthread_attr_setinheritsched(&attr,PTHREAD_EXPLICIT_SCHED) || pthread_attr_setschedparam(&attr,&priority))fail("pthread_attr");
    for(unsigned i=0;i<count;i++) {
      if(pthread_create(&tasks[i],&attr,worker,(void *)(uintptr_t)i))fail("pthread_create");
    }
    pthread_attr_destroy(&attr);
    for(unsigned i=0;i<count;i++)wait_done();
    for(unsigned i=0;i<count;i++)if(pthread_join(tasks[i],NULL))fail("pthread_join");
    for(unsigned i=0;i<count;i++)if(progress[i]!=100)errors++;
    printf("NOS_SWITCH workers=%u rounds=100 entries=%u handoffs=%u elapsed_ns=%llu errors=%u\n",count,entries,handoffs,(unsigned long long)(last-first),errors);
    failures+=errors;
  }
  struct sigaction action;memset(&action,0,sizeof(action));action.sa_sigaction=callback;action.sa_flags=SA_SIGINFO;sigemptyset(&action.sa_mask);
  if(sigaction(SIGRTMIN,&action,NULL))fail("sigaction");
  for(unsigned g=0;g<5;g++) {
    count=tg[g];callbacks=errors=0;for(unsigned i=0;i<100;i++)fired[i]=0;body_ns=0;max_offset=INT64_MIN;
    for(unsigned i=0;i<count;i++) {
      struct sigevent event;memset(&event,0,sizeof(event));event.sigev_notify=SIGEV_SIGNAL;event.sigev_signo=SIGRTMIN;event.sigev_value.sival_int=i;
      if(timer_create(CLOCK_MONOTONIC,&event,&timers[i]))fail("timer_create");
    }
    struct itimerspec spec={{0,0},{0,20000000}};
    uint64_t start=host_gettime(false);
    for(unsigned i=0;i<count;i++){expected[i]=native_now()+20000000ULL;if(timer_settime(timers[i],0,&spec,NULL))fail("timer_settime");}
    uint64_t elapsed=host_gettime(false)-start;
    wait_done();
    for(unsigned i=0;i<count;i++){if(fired[i]!=1)errors++;if(timer_delete(timers[i]))fail("timer_delete");}
    printf("NOS_TIMER timers=%u delay_ms=20 arm_ns=%llu callbacks=%u errors=%u context=signal_handler max_offset_ns=%lld callback_body_ns=%llu deadline_clock=kernel_monotonic\n",count,(unsigned long long)elapsed,callbacks,errors,(long long)max_offset,(unsigned long long)body_ns);
    failures+=errors;
  }
  printf("NOS_DONE failures=%u\n",failures);fflush(stdout);
  boardctl(BOARDIOC_POWEROFF,failures?1:0);return failures?1:0;
}
