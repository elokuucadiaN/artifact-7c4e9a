"""Strict admission of the additional endpoint pairs in extended-v2 captures."""
BOOT={
 'FOS':('idf_linux_main','app_main'), 'ZOS':('z_cstart','benchmark_main'),
 'ROS':('kernel_init','benchmark_main'), 'AOS':('benchmark_main_before_krhino_init','coordinator_task'),
 'NOS':('nx_start','euno_main'), 'COS':('native_main','coordinator_process'),
}
DEADLINE_CLOCKS={'FOS':'kernel_ticks','ZOS':'kernel_uptime','ROS':'ztimer_msec','AOS':'kernel_ticks','NOS':'kernel_monotonic','COS':'contiki_clock'}
def parse_rows(text,tag,group):
    rows=[]
    for line in text.splitlines():
        if line.startswith(tag+'_'+group+' '):
            fields=dict(s.split('=',1) for s in line.split()[1:])
            rows.append({k:int(v) if v.lstrip('-').isdecimal() else v for k,v in fields.items()})
    return rows
def validate_extended(text,tag):
    if text.count(tag+'_MORE_META profile=extended-v2')!=1:raise ValueError('Missing extended protocol identity')
    def single(group):
        rows=parse_rows(text,tag,group)
        if len(rows)!=1:raise ValueError('Missing/repeated extended group: '+group)
        return rows[0]
    boot=single('BOOT')
    if boot['valid']!=1 or boot['elapsed_ns']<=0 or (boot['entry'],boot['end'])!=BOOT[tag]:raise ValueError('Invalid native entry/boot hook')
    result={'BOOT':boot}
    if tag=='COS':
        if text.count('COS_NOT_APPLICABLE metrics=preempt,pingpong reason=no_priority_threads_or_blocking_native_semaphore')!=1:raise ValueError('Missing cooperative applicability declaration')
    else:
        pre=single('PREEMPT');ping=single('PINGPONG')
        for r in (pre,ping):
            if r['rounds']!=100 or r['verified']!=100 or r['errors']!=0:raise ValueError('Failed native semaphore/preemption progress')
        if pre['mechanism']!='native_semaphore' or not 0<=pre['min_ns']<=pre['sum_ns']/100<=pre['max_ns'] or pre['sum_ns']<=0:raise ValueError('Invalid wakeup endpoint accounting')
        if ping['priority']!='higher_peer' or ping['elapsed_ns']<=0:raise ValueError('Invalid pingpong endpoint accounting')
        result.update(PREEMPT=pre,PINGPONG=ping)
    timers=parse_rows(text,tag,'TIMER')
    if [r['timers'] for r in timers]!=[1,10,20,50,100]:raise ValueError('Missing extended timer grid')
    for r in timers:
        if not isinstance(r.get('max_offset_ns'),int) or not isinstance(r.get('callback_body_ns'),int) or r['callback_body_ns']<0:raise ValueError('Missing/invalid callback observation')
        if r.get('deadline_clock')!=DEADLINE_CLOCKS[tag]:raise ValueError('Wrong deadline clock domain')
    result['TIMER']=timers
    return result

