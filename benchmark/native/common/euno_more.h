/* Shared observer/protocol only. All scheduling and semaphore operations are native OS APIs. */
#ifndef EUNO_MORE_H
#define EUNO_MORE_H
#define MORE_ROUNDS 100
static more_sem_t more_kick, more_ack;
static volatile unsigned more_phase, more_sequence, more_blocked, more_finished;
static volatile uint64_t more_entry;
static void more_peer(void) {
  more_post(&more_ack);
  for(unsigned i=0;i<2*MORE_ROUNDS;i++) {
    more_blocked=1;
    more_wait(&more_kick);
    more_entry=more_now();
    more_blocked=0;
    if(more_phase!=1) more_bad++;
    more_sequence++;
    more_post(&more_ack);
  }
  more_finished=1;
  more_park();
}
static void more_tests(void) {
  uint64_t total=0, maximum=0, minimum=UINT64_MAX, ping_start=0, ping_ns=0;
  unsigned verified=0;
  more_phase=more_sequence=more_blocked=more_finished=more_bad=0;
  more_init(&more_kick);more_init(&more_ack);
  more_launch();more_wait(&more_ack);
  for(unsigned i=0;i<2*MORE_ROUNDS;i++) {
    if(i==MORE_ROUNDS)ping_start=more_now();
    if(more_blocked!=1)more_bad++;
    more_phase=1;
    uint64_t begin=more_now();
    more_post(&more_kick);
    /* A successful preemption has executed the peer before give/post returns. */
    if(more_sequence!=i+1)more_bad++;
    more_phase=0;
    more_wait(&more_ack);
    if(i<MORE_ROUNDS) {
      uint64_t delta=more_entry-begin;
      total+=delta;if(delta>maximum)maximum=delta;if(delta<minimum)minimum=delta;
      verified++;
    }
  }
  ping_ns=more_now()-ping_start;
  if(!more_finished || more_sequence!=2*MORE_ROUNDS)more_bad++;
  more_join();more_destroy(&more_kick);more_destroy(&more_ack);
  printf(MORE_TAG "_PREEMPT rounds=%u verified=%u sum_ns=%llu min_ns=%llu max_ns=%llu errors=%u mechanism=native_semaphore\n",
    MORE_ROUNDS,verified,(unsigned long long)total,(unsigned long long)minimum,(unsigned long long)maximum,more_bad);
  printf(MORE_TAG "_PINGPONG rounds=%u verified=%u elapsed_ns=%llu errors=%u priority=higher_peer\n",
    MORE_ROUNDS,MORE_ROUNDS,(unsigned long long)ping_ns,more_bad);
  failures+=more_bad!=0;
}
#endif
