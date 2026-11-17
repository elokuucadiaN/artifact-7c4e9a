"""Run negative admission controls against actual OS logs, never fabricated observations."""
import argparse,json,re,shutil,tempfile
from pathlib import Path
from .run_native_batch import validate,save,sha
from .version_policy import TAGS,META,require_paper_version
from .run_native_batch import BASE
from .source_scope import verify_source
def check(source,output):
    subjects=json.loads((source/'receipt.json').read_text())['subjects'];tests=[]
    for subject in subjects:
        if subject['status']!='passed':continue
        key=subject['os'].lower();require_paper_version(subject)
        wrong=dict(subject,upstream_commit='0'*40)
        try:require_paper_version(wrong)
        except ValueError:tests.append(dict(os=key,control='changed_source_revision',rejected=True))
        else:raise AssertionError('Wrong source version admitted')
        for i in range(1,4):
            extended=subject.get('probe_profile')=='extended-v2'
            raw=source/key/f'run-{i}.stdout';text=raw.read_text();tag=TAGS[key];validate(text,tag,extended=extended)
            lines=text.splitlines()
            mutations={
                'missing_completion':'\n'.join(s for s in lines if not s.startswith(tag+'_DONE')),
                'lost_callback':'\n'.join(s.replace('callbacks=1 ', 'callbacks=0 ') if s.startswith(tag+'_TIMER timers=1 ') else s for s in lines),
                'wrong_os_version':text.replace(tag+'_META '+META[tag],tag+'_META os=wrong version=wrong'),
            }
            if extended:
                mutations.update({
                    'missing_boot_hook':'\n'.join(s for s in lines if not s.startswith(tag+'_BOOT')),
                    'unexecuted_boot_hook':'\n'.join(s.replace('valid=1','valid=0') if s.startswith(tag+'_BOOT') else s for s in lines),
                    'wrong_deadline_clock':re.sub(r'deadline_clock=\S+','deadline_clock=host_wrong_domain',text),
                    'missing_callback_window':re.sub(r' callback_body_ns=\d+','',text),
                    'negative_callback_window':re.sub(r'callback_body_ns=\d+','callback_body_ns=-1',text),
                    'missing_extended_identity':'\n'.join(s for s in lines if not s.startswith(tag+'_MORE_META')),
                })
                if tag!='COS':
                    mutations.update({
                        'lost_preemption':'\n'.join(s.replace('verified=100','verified=99') if s.startswith(tag+'_PREEMPT') else s for s in lines),
                        'lost_pingpong':'\n'.join(s.replace('verified=100','verified=99') if s.startswith(tag+'_PINGPONG') else s for s in lines),
                    })
            for name,altered in mutations.items():
                try:validate(altered,tag,extended=extended)
                except ValueError:tests.append(dict(os=key,run=i,control=name,rejected=True,original_sha256=sha(raw)))
                else:raise AssertionError('Invalid log admitted: '+key+' '+name)
        if (source/key/'source-scope.json').is_file():
            verify_source(source/key,key)
            scratch=BASE/'integration-checks';scratch.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='source-control-',dir=scratch) as temp:
                folder=Path(temp);shutil.copytree(source/key/'source-scope',folder/'source-scope')
                descriptor=json.loads((source/key/'source-scope.json').read_text());descriptor['files'][0]['code_lines']+=1
                save(folder/'source-scope.json',descriptor)
                try:verify_source(folder,key)
                except ValueError:tests.append(dict(os=key,control='altered_source_line_count',rejected=True))
                else:raise AssertionError('Changed source count admitted')
    result=dict(pass_=True,positive_logs=sum(s['status']=='passed' for s in subjects)*3,
                negative_controls=len(tests),controls=tests,new_OS_runs=0)
    result['pass']=result.pop('pass_');save(output,result);return result
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    r=check(a.input,a.output);print(json.dumps({k:v for k,v in r.items() if k!='controls'},indent=2))
