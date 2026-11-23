#include <xtensa/config/core-isa.h>
#include <zephyr/irq.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/util.h>
#include <stddef.h>
#include <stdint.h>

/* Offsets are consumed by the Xtensa assembly in build_zephyr_irq.py. */
struct irq_trace {
    uint32_t armed;
    uint32_t vector;
    uint32_t saved;
    uint32_t isr;
    uint32_t isr_end;
    uint32_t restore;
    uint32_t restored;
    uint32_t frame;
    uint32_t bsa;
};
volatile struct irq_trace euno_irq_trace;

BUILD_ASSERT(offsetof(struct irq_trace, armed) == 0);
BUILD_ASSERT(offsetof(struct irq_trace, vector) == 4);
BUILD_ASSERT(offsetof(struct irq_trace, saved) == 8);
BUILD_ASSERT(offsetof(struct irq_trace, isr) == 12);
BUILD_ASSERT(offsetof(struct irq_trace, isr_end) == 16);
BUILD_ASSERT(offsetof(struct irq_trace, restore) == 20);
BUILD_ASSERT(offsetof(struct irq_trace, restored) == 24);
BUILD_ASSERT(offsetof(struct irq_trace, frame) == 28);
BUILD_ASSERT(offsetof(struct irq_trace, bsa) == 32);
BUILD_ASSERT(CONFIG_XTENSA_TIMER_ID == 0);
BUILD_ASSERT(XCHAL_TIMER1_INTERRUPT == 15 && XCHAL_INT15_LEVEL == 3);
BUILD_ASSERT(!IS_ENABLED(CONFIG_SMP));

#define TRIALS 512
#define CALIBRATION_TRIALS 128
#define IRQ_MASK (1U << XCHAL_TIMER1_INTERRUPT)

static volatile uint32_t hits;
static volatile uint32_t irq_pending;
static volatile uint32_t compare_seen;
static volatile uint32_t calibration_store;
static struct {
    uint32_t compare, vector, saved, isr, isr_end, restore, restored, resumed;
    uint32_t pending;
} samples[TRIALS];
static uint32_t calibration[CALIBRATION_TRIALS];

static inline uint32_t ccount(void)
{
    uint32_t value;
    __asm__ volatile("rsr.ccount %0" : "=a"(value) :: "memory");
    return value;
}

static inline void compare_set(uint32_t value)
{
    __asm__ volatile("wsr.ccompare1 %0; rsync" :: "a"(value) : "memory");
}

static void timer_irq(const void *unused)
{
    ARG_UNUSED(unused);
    euno_irq_trace.isr = ccount();
    __asm__ volatile("rsr.interrupt %0" : "=a"(irq_pending));
    __asm__ volatile("rsr.ccompare1 %0" : "=a"(compare_seen));
    /* Writing the comparator acknowledges the current hardware alarm. */
    compare_set(ccount() + 0x40000000U);
    hits++;
    euno_irq_trace.isr_end = ccount();
}

static uint32_t calibrate(void)
{
    uint32_t start, end;
    __asm__ volatile("rsr.ccount %0\n"
                     "s32i %0, %2, 0\n"
                     "rsr.ccount %1"
                     : "=&a"(start), "=&a"(end) : "a"(&calibration_store) : "memory");
    return end - start;
}

static int measure(void)
{
    compare_set(ccount() + 0x40000000U);
    IRQ_CONNECT(XCHAL_TIMER1_INTERRUPT, 0, timer_irq, NULL, 0);
    irq_enable(XCHAL_TIMER1_INTERRUPT);
    for (unsigned i = 0; i < CALIBRATION_TRIALS; i++) {
        calibration[i] = calibrate();
    }

    for (unsigned i = 0; i < TRIALS; i++) {
        euno_irq_trace = (struct irq_trace){ .armed = 1 };
        uint32_t compare = ccount() + 24000 + (i * 113U % 12000);
        compare_set(compare);
        uint32_t resumed = ccount();
        while (!euno_irq_trace.restored && (int32_t)(resumed - compare) < 1200000) {
            resumed = ccount();
        }
        resumed = ccount();
        euno_irq_trace.armed = 0;
        if (hits != i + 1 || !(irq_pending & IRQ_MASK) || compare_seen != compare ||
            !euno_irq_trace.vector || !euno_irq_trace.saved || !euno_irq_trace.isr ||
            !euno_irq_trace.isr_end || !euno_irq_trace.restore || !euno_irq_trace.restored) {
            irq_disable(XCHAL_TIMER1_INTERRUPT);
            printk("IRQ_FAIL sample=%u hits=%u pending=%08x compare_match=%u "
                   "stamps=%08x,%08x,%08x,%08x,%08x,%08x\n",
                   i, hits, irq_pending, compare_seen == compare,
                   euno_irq_trace.vector, euno_irq_trace.saved, euno_irq_trace.isr,
                   euno_irq_trace.isr_end, euno_irq_trace.restore, euno_irq_trace.restored);
            return -1;
        }
        samples[i].compare = compare;
        samples[i].vector = euno_irq_trace.vector;
        samples[i].saved = euno_irq_trace.saved;
        samples[i].isr = euno_irq_trace.isr;
        samples[i].isr_end = euno_irq_trace.isr_end;
        samples[i].restore = euno_irq_trace.restore;
        samples[i].restored = euno_irq_trace.restored;
        samples[i].resumed = resumed;
        samples[i].pending = irq_pending;
    }
    irq_disable(XCHAL_TIMER1_INTERRUPT);
    return 0;
}

int main(void)
{
    printk("IRQ_META os=Zephyr version=3.7.0 source=CCOMPARE1 cpu_irq=15 level=3 cpu=0 "
           "clock_hz=%u tickless=%d samples=%d calibrations=%d\n",
           sys_clock_hw_cycles_per_sec(), IS_ENABLED(CONFIG_TICKLESS_KERNEL), TRIALS,
           CALIBRATION_TRIALS);
    if (measure() == 0) {
        for (unsigned i = 0; i < CALIBRATION_TRIALS; i++) {
            printk("IRQ_CAL %u %u\n", i, calibration[i]);
        }
        for (unsigned i = 0; i < TRIALS; i++) {
            printk("IRQ_ROW %u %08x %08x %08x %08x %08x %08x %08x %08x %08x\n",
                   i, samples[i].compare, samples[i].vector, samples[i].saved,
                   samples[i].isr, samples[i].isr_end, samples[i].restore,
                   samples[i].restored, samples[i].resumed, samples[i].pending);
        }
        printk("IRQ_DONE hits=%u errors=0\n", hits);
    }
    k_sleep(K_FOREVER);
    return 0;
}
