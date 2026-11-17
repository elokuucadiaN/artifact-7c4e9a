"""Paper source revisions: a simulator rebuild may change its board, never its OS revision."""
PINS = {
    'freertos': '9b74d1aca5f2154c4ea609d6e36d513dcf91148b', # ESP-IDF v5.2.5
    'zephyr': '36940db938a8f4a1e919496793ed439850a221c2', # v3.7.0
    'riot': 'dd06b3727c41c2c44bf93f47ff7831fdd501d68b',
    'contiki': 'c02eedae8b187123069891f81a7111b833701f9c',
    'alios': 'bacc144bdc5df8fe8e302e3732675a920aa40bc5',
    'nuttx': '148c631a2d252d4d59ae4cd90d1890d2daed381d', # 12.2.1
}
TAGS={'freertos':'FOS','zephyr':'ZOS','riot':'ROS','contiki':'COS','alios':'AOS','nuttx':'NOS'}
META={
    'FOS':'os=FreeRTOS version=ESP-IDF-v5.2.5 kernel=V10.5.1 port=idf_linux tick_hz=1000 hardware_measurement=0',
    'ZOS':'os=Zephyr version=3.7.0',
    'ROS':'os=RIOT version=dd06b372',
    'COS':'os=Contiki-NG version=c02eedae',
    'AOS':'os=AliOS version=bacc144b',
    'NOS':'os=NuttX version=12.2.1',
}
def require_paper_version(subject):
    key=subject['os'].lower()
    if subject.get('upstream_commit')!=PINS[key]:
        raise ValueError('OS revision differs from EunoBench paper: '+key)
