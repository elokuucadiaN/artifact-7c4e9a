"""Explicit source-scope descriptors, never a trusted-computing-base or whole-SDK claim."""
import hashlib,json,shutil
from pathlib import Path
SCOPES={
 'freertos':['components/freertos/FreeRTOS-Kernel'], 'zephyr':['kernel'],
 'riot':['core'], 'alios':['kernel/rhino'], 'nuttx':['sched'],
 'contiki':['os/sys','os/lib'],
}
def code_lines(text):
    """Count nonblank physical lines with C code; keep comment markers inside literals."""
    text=text.lstrip('\ufeff')
    state='code';quote='';escaped=False;present=False;count=0;i=0
    while i<len(text):
        c=text[i];n=text[i+1] if i+1<len(text) else ''
        if c=='\n':
            count+=present;present=False
            if state=='line' and (i==0 or text[i-1]!='\\'):state='code'
            if state=='string':escaped=False
            i+=1;continue
        if state=='block':
            if c=='*' and n=='/':state='code';i+=2;continue
        elif state=='line':pass
        elif state=='string':
            if not c.isspace():present=True
            if escaped:escaped=False
            elif c=='\\':escaped=True
            elif c==quote:state='code'
        elif c=='/' and n=='*':state='block';i+=2;continue
        elif c=='/' and n=='/':state='line';i+=2;continue
        else:
            if not c.isspace():present=True
            if c in ('"',"'"):state='string';quote=c
        i+=1
    return int(count+present)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def capture_source(source,os,output):
    source=source.resolve();saved=output/'source-scope';saved.mkdir()
    files=[]
    for scope in SCOPES[os]:
        for path in sorted((source/scope).rglob('*')):
            if path.suffix not in ('.c','.h') or not path.is_file():continue
            if not path.resolve().is_relative_to(source):raise ValueError('Source symlink leaves SDK')
            relative=path.relative_to(source);dest=saved/'files'/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
            files.append(dict(path=str(relative),sha256=sha(dest),language='C' if path.suffix=='.c' else 'C-header',code_lines=code_lines(dest.read_text(errors='replace'))))
    result=dict(schema=1,component='+'.join(SCOPES[os]),scope_roots=SCOPES[os],files=files,
        scope='Declared distributed core C/header subtrees, including conditional/unlinked files; excludes other SDK directories and assembly; not TCB or compiled-only LOC')
    (output/'source-scope.json').write_text(json.dumps(result,indent=2)+'\n')
    return result
def verify_source(folder,os=None):
    result=json.loads((folder/'source-scope.json').read_text());totals={};seen=set()
    if os is not None and (result['scope_roots']!=SCOPES[os] or result['component']!='+'.join(SCOPES[os])):raise ValueError('Wrong declared source scope')
    for row in result['files']:
        p=(folder/'source-scope/files'/row['path']).resolve()
        if row['path'] in seen or not p.is_relative_to((folder/'source-scope/files').resolve()):raise ValueError('Invalid source-scope member')
        seen.add(row['path'])
        if not any(Path(row['path']).is_relative_to(root) for root in result['scope_roots']):raise ValueError('File outside declared source scope')
        if row['language']!=('C' if p.suffix=='.c' else 'C-header') or p.suffix not in ('.c','.h'):raise ValueError('Changed source language')
        if sha(p)!=row['sha256'] or code_lines(p.read_text(errors='replace'))!=row['code_lines']:raise ValueError('Changed source-scope descriptor')
        totals[row['language']]=totals.get(row['language'],0)+row['code_lines']
    if not seen:raise ValueError('Empty source scope')
    actual={str(p.relative_to(folder/'source-scope/files')) for p in (folder/'source-scope/files').rglob('*') if p.is_file()}
    if actual!=seen:raise ValueError('Source scope file membership changed')
    return result['component'],totals
