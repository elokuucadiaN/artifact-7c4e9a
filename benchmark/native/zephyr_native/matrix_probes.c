#include <zephyr/kernel.h>
#include <zephyr/irq_offload.h>
#include <stdint.h>
#include <stdio.h>
#include <time.h>
static volatile unsigned active, calls, errors, irq_seen;
static volatile uint64_t handler_ns, entered;
static uint64_t stamp(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (uint64_t)t.tv_sec*1000000000ULL+t.tv_nsec;}
void __real_sys_clock_announce(int32_t ticks);
void __wrap_sys_clock_announce(int32_t ticks){
 uint64_t start=stamp();unsigned observe=active;
 __real_sys_clock_announce(ticks);
 if(observe){handler_ns+=stamp()-start;calls++;}
}
void euno_matrix_timer_begin(void){calls=0;handler_ns=0;active=1;}
void euno_matrix_timer_end(unsigned n){active=0;printf("ZOS_ANNOUNCE timers=%u calls=%u elapsed_ns=%llu\n",n,calls,(unsigned long long)handler_ns);}
static void irq_probe(const void *arg){entered=stamp();if(!k_is_in_isr() || arg!=(const void *)&irq_seen)errors++;irq_seen++;}
int euno_matrix_irq(void){
 uint64_t entry_sum=0,roundtrip_sum=0;
 errors=irq_seen=0;
 for(unsigned i=0;i<100;i++){
  uint64_t start=stamp();irq_offload(irq_probe,(const void *)&irq_seen);uint64_t end=stamp();
  if(irq_seen!=i+1 || entered<start || end<entered || k_is_in_isr())errors++;
  entry_sum+=entered-start;roundtrip_sum+=end-start;
 }
 printf("ZOS_OFFLOAD rounds=100 verified=%u errors=%u entry_sum_ns=%llu roundtrip_sum_ns=%llu\n",irq_seen,errors,(unsigned long long)entry_sum,(unsigned long long)roundtrip_sum);
 return errors!=0;
}
