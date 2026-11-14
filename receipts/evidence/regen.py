"""Strict mechanical check for change 2297: is every generated-snapshot hunk ONLY the expected attribute block?
Usage: python3 -I regen.py <repo> <base> <head> <out_dir>
Pure deterministic; no LLM."""
import json, re, subprocess, sys, os, collections

repo, base, head, out = sys.argv[1:5]
def git(*a): return subprocess.run(["git","-C",repo,*a],capture_output=True,text=True,check=True).stdout

ATTR = re.compile(r'^\s*\[global::System\.Diagnostics\.CodeAnalysis\.ExcludeFromCodeCoverage\]\s*$')
IF   = re.compile(r'^#if !NETSTANDARD2_0 && !NETFRAMEWORK\s*$')
ENDIF= re.compile(r'^#endif\s*$')

def kind(p):
    if p.endswith('.g.cs'): return 'generated'
    if p.endswith('.tt'): return 'template'
    if p.startswith('src/') and p.endswith('.cs') and os.path.exists(os.path.join(repo,p[:-3]+'.tt')) or p.endswith('Template.cs'): return 'template-output'
    if p.startswith('tests/'): return 'test'
    if p.endswith('.md'): return 'doc'
    return 'src'

names = git("diff","--numstat",base,head).strip().splitlines()
files=[]
for l in names:
    a,r,p=l.split('\t'); files.append(dict(path=p,added=int(a),removed=int(r),kind=kind(p)))

def hunks(path):
    d=git("diff","-U0",base,head,"--",path)
    res=[];cur=None
    for ln in d.splitlines():
        if ln.startswith('@@'):
            cur=dict(header=ln,add=[],rem=[]);res.append(cur)
        elif cur is not None and ln.startswith('+') and not ln.startswith('+++'): cur['add'].append(ln[1:])
        elif cur is not None and ln.startswith('-') and not ln.startswith('---'): cur['rem'].append(ln[1:])
    return res

def hunk_ok(h):
    # expected: removed nothing; added exactly [#if, attr, #endif] triples
    if h['rem']: return False,'removes lines'
    a=h['add']
    if len(a)%3: return False,'added-line count not multiple of 3'
    for i in range(0,len(a),3):
        if not(IF.match(a[i]) and ATTR.match(a[i+1]) and ENDIF.match(a[i+2])): return False,'not the attribute block'
    return True,''

match=0; nonmatch=[]; gen=[f for f in files if f['kind']=='generated']
for f in gen:
    bad=[]
    for h in hunks(f['path']):
        ok,why=hunk_ok(h)
        if not ok: bad.append(dict(header=h['header'],why=why,added=h['add'][:6],removed=h['rem'][:6]))
    if bad: nonmatch.append(dict(path=f['path'],hunks=bad))
    else: match+=1

# H6: .tt vs .cs template consistency (every changed .tt has its .cs counterpart changed, and vice versa)
changed={f['path'] for f in files}
templates=[]
for f in files:
    if f['kind']=='template':
        cs=f['path'][:-3]+'.cs'
        templates.append(dict(tt=f['path'],cs=cs,cs_changed=cs in changed,tt_lines=f['added']+f['removed']))
orphan_cs=[f['path'] for f in files if f['kind']=='template-output' and f['path'][:-3]+'.tt' not in changed and f['path'].endswith('Template.cs')]
other=[f for f in files if f['kind'] in('src','doc','test')]
# counting attribute blocks
attr_total=sum(f['added'] for f in gen)//3 if gen else 0
reading=sum(f['added']+f['removed'] for f in files if f['kind'] in('src','template','template-output','doc','test'))
nonmatch_lines=0
for n in nonmatch:
    f=next(x for x in files if x['path']==n['path']); nonmatch_lines+=f['added']+f['removed']
res=dict(change='2297',base=base,head=head,files_total=len(files),
 counts=dict(collections.Counter(f['kind'] for f in files)),
 generated_total=len(gen),generated_matching=match,generated_nonmatching=nonmatch,
 expected_pattern='added lines come in triples: "#if !NETSTANDARD2_0 && !NETFRAMEWORK" / "[global::System.Diagnostics.CodeAnalysis.ExcludeFromCodeCoverage]" / "#endif"; nothing removed',
 templates=templates,template_cs_without_tt_change=orphan_cs,
 non_snapshot_files=[f['path'] for f in other],
 verdict=None,reading_budget_lines=None)
res['verdict']=f"{match}/{len(gen)} generated snapshot files contain only the expected attribute block; {len(nonmatch)} do not."
res['reading_budget_lines']=reading+nonmatch_lines
os.makedirs(out,exist_ok=True)
json.dump(res,open(os.path.join(out,'regen.json'),'w'),indent=1)
# files.json for the treemap
nm={n['path'] for n in nonmatch}
fj=[]
for f in files:
    k=f['kind']
    lane='L0' if k=='generated' and f['path'] not in nm else ('L1' if k in('doc',) else ('L1' if k=='test' else 'L2'))
    if k=='generated' and f['path'] in nm: lane='L2'
    fj.append(dict(path=f['path'],kind=k,lines=f['added']+f['removed'],lane=lane))
json.dump(fj,open(os.path.join(out,'files.json'),'w'),indent=1)
print(res['verdict']); print('files',len(files),res['counts']); print('reading budget lines',res['reading_budget_lines'])
