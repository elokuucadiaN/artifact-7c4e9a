"""Assemble validated, disjoint OS captures without re-counting or rerunning trials."""
import argparse,json,shutil
from pathlib import Path
from .run_native_batch import sha,save,validate,BASE
from .version_policy import PINS,TAGS,require_paper_version
def merge(inputs,output,replace=()):
    output=output.resolve()
    if not output.is_relative_to(BASE.resolve()):raise ValueError('Use native Linux output')
    chosen={};origins=[]
    for source in inputs:
        source=source.resolve()
        if not source.is_relative_to(BASE.resolve()):raise ValueError('Use native Linux captures')
        manifest=json.loads((source/'evidence.json').read_text())['members']
        for name,digest in manifest.items():
            path=(source/name).resolve()
            if not path.is_relative_to(source) or not path.is_file() or sha(path)!=digest:raise ValueError('Changed capture: '+name)
        origins.append(dict(source=str(source),manifest_sha256=sha(source/'evidence.json')))
        for subject in json.loads((source/'receipt.json').read_text())['subjects']:
            if subject['status']!='passed':continue
            require_paper_version(subject);key=subject['os'].lower()
            if key in chosen and key not in replace:raise ValueError('Repeated OS capture: '+key)
            for i in range(1,4):validate((source/key/f'run-{i}.stdout').read_text(),TAGS[key],extended=subject.get('probe_profile')=='extended-v2')
            chosen[key]=(source,subject)
    output.mkdir(exist_ok=False)
    for key,(source,_) in chosen.items():shutil.copytree(source/key,output/key)
    receipt=dict(schema=2,subjects=[chosen[k][1] for k in PINS if k in chosen],selected_targets_pass=True,
        all_six_OS_families_complete=set(chosen)==set(PINS),original_eight_B1_deployments_complete=False,
        new_board_measurements=0,independent_processes=sum(v[1]['independent_processes'] for v in chosen.values()),
        origin_captures=origins,scope='Paper-pinned OS source versions; separate host simulator functional configurations')
    save(output/'receipt.json',receipt)
    save(output/'evidence.json',{'members':{str(p.relative_to(output)):sha(p) for p in output.rglob('*') if p.is_file() and p.name!='evidence.json'}})
    return receipt
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,nargs='+',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--replace',choices=list(PINS),nargs='*',default=[]);a=p.parse_args()
    print(json.dumps(merge(a.input,a.output,a.replace),indent=2))

