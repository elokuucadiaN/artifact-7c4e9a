#include <zephyr/kernel.h>
#include <zephyr/irq_offload.h>
#include <zephyr/sys/printk.h>
static volatile unsigned irqs,errors,callbacks;
static struct k_timer timer;
static K_SEM_DEFINE(done,0,1);
static void irq(const void *p){if(!k_is_in_isr() || p!=(const void *)&irqs)errors++;irqs++;}
static void expired(struct k_timer *t){if(t!=&timer || !k_is_in_isr())errors++;callbacks++;k_sem_give(&done);}
int main(void){
 printk("QOS_META os=Zephyr version=3.7.0 target=mps2_an385 scope=qemu_functional\n");
 volatile uint32_t canary[4]={0x12345678,0x87654321,0x11223344,0xaabbccdd};
 for(unsigned i=0;i<100;i++){
  irq_offload(irq,(const void *)&irqs);
  if(irqs!=i+1 || k_is_in_isr() || canary[0]!=0x12345678 || canary[1]!=0x87654321 || canary[2]!=0x11223344 || canary[3]!=0xaabbccdd)errors++;
 }
 k_timer_init(&timer,expired,NULL);k_timer_start(&timer,K_MSEC(20),K_NO_WAIT);
 if(k_sem_take(&done,K_SECONDS(2)) || callbacks!=1)errors++;
 printk("QOS_DONE irqs=%u callbacks=%u errors=%u\n",irqs,callbacks,errors);
 return 0;
}
