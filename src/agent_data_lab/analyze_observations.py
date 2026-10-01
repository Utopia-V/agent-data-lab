"""Export source-discovery and continuation evidence without hiding failed runs."""

import argparse
from collections import defaultdict
import gzip
from hashlib import sha256
import io
import json
from pathlib import Path
import tarfile

from .analyze import metrics
from .fixtures import dataset_digest,write_json


CAMPAIGNS=['raw-discovery-probe','retained-work-v1','retained-work-v2',
    'observation-factorial-v1','retained-instructions-v1',
    'layout-1-v1','layout-32-v1','layout-256-v1','repa-understanding-v1','compaction-probe-v1',
    'retained-artifacts-v2','workspace-artifacts-v2','composed-work-v1','local-contract-v1','compaction-artifacts-v2']


def archive_files(files,destination):
    content=io.BytesIO()
    with tarfile.open(fileobj=content,mode='w',format=tarfile.GNU_FORMAT) as archive:
        for name,path in sorted(files):
            data=path.read_bytes();info=tarfile.TarInfo(name)
            info.size=len(data);info.mode=0o644;info.mtime=0
            archive.addfile(info,io.BytesIO(data))
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_bytes(gzip.compress(content.getvalue(),mtime=0))
    return sha256(destination.read_bytes()).hexdigest()


def quote_check(row,root):
    evidence=row.get('artifact',{}).get('evidence',[])
    checks=[]
    for item in evidence:
        path=root/item.get('path','').removeprefix('/work/')
        quote=item.get('quote','')
        valid=path.resolve().is_relative_to(root.resolve()) and path.is_file() and len(quote)>=10 and quote in path.read_text()
        checks.append({'claim':item.get('claim'),'exact_source_match':valid})
    selected={part.strip() for part in row.get('artifact',{}).get('answer','').split(',')}
    covered={item['claim'] for item in checks if item['exact_source_match']}
    return {'checks':checks,'all_selected_claims_have_exact_quotes':bool(selected) and selected<=covered,
            'semantic_support':'reviewed separately against source context'}


def export(root,output,campaigns):
    output.mkdir(parents=True,exist_ok=True)
    rows=[];provenance=[];artifact_files=[]
    for name in campaigns:
        campaign=root/name
        manifest=json.loads((campaign/'manifest.json').read_text())
        diagnostic=manifest['kind']!='raw-source-discovery' and manifest.get('artifact_protocol',1)<2
        implementation=campaign/'implementation'
        digest=dataset_digest(implementation)
        if digest!=manifest['implementation_sha256']: raise ValueError('changed experiment implementation: '+name)
        archive=output/'implementations'/f'{digest}.tar.gz'
        archive_hash=archive_files([('agent_data_lab/'+str(p.relative_to(implementation)),p)
            for p in implementation.rglob('*') if p.is_file()],archive)
        provenance.append({'campaign':name,'manifest':manifest,'archive':str(archive.relative_to(output)),
            'archive_sha256':archive_hash,
            'evidence_status':'diagnostic: previous answer artifact removed' if diagnostic else 'current protocol',
            'order':json.loads((campaign/'order.json').read_text()) if (campaign/'order.json').exists() else None})
        if manifest['kind']=='raw-source-discovery':
            result_paths=[p for p in campaign.glob('*.json') if not p.name.endswith('.model.json')
                and p.name not in {'manifest.json','summary.json','order.json'}]
            for path in sorted(result_paths):
                row=json.loads(path.read_text())
                row.update(campaign=name,mode='cold',sequence=None,evidence_status='current protocol')
                if name=='repa-understanding-v1':
                    row['quote_verification']=quote_check(row,Path('datasets/repa-understanding/context'))
                rows.append(row)
            for path in (campaign/'scratch').rglob('*'):
                if path.is_file(): artifact_files.append((name+'/scratch/'+str(path.relative_to(campaign/'scratch')),path))
        else:
            for home in sorted(campaign.glob('gpt*')):
                model=next(model for model in manifest['models'] if home.name.startswith(model+'-'))
                tail=home.name[len(model)+1:].split('-')
                mode=tail[0];condition=tail[1] if len(tail)>2 else 'none'
                for stage in sorted(home.glob('[0-9]-*')):
                    path=stage/'result.json'
                    if not path.exists(): raise ValueError('incomplete task: '+str(stage))
                    row=json.loads(path.read_text())
                    task_input=json.loads((stage/'input.json').read_text())
                    row.update(campaign=name,model=model,condition=condition,mode=mode,sequence=home.name,
                        evidence_status='diagnostic: previous answer artifact removed' if diagnostic else 'current protocol',
                        replicate=int(tail[-1]),task=stage.name,prompt=task_input['question'],
                        expected=task_input['expected'],source_sha256=task_input['source_sha256'])
                    if 'artifact' not in row and (stage/'artifacts/answer.json').exists():
                        row['artifact']=json.loads((stage/'artifacts/answer.json').read_text())
                    if 'trace' not in row and (stage/'trace.jsonl').exists():
                        row['trace']=[json.loads(line) for line in (stage/'trace.jsonl').read_text().splitlines()]
                    rows.append(row)
                    for path in (stage/'artifacts').rglob('*'):
                        if path.is_file(): artifact_files.append((name+'/'+home.name+'/'+stage.name+'/'+str(path.relative_to(stage/'artifacts')),path))
                compact=home/'compaction.json'
                if compact.exists():
                    provenance[-1].setdefault('compactions',[]).append({'sequence':home.name,**json.loads(compact.read_text())})
    groups=defaultdict(list)
    for row in rows:
        row['metrics']=metrics(row) if row.get('usage') is not None and 'wall_seconds' in row else None
        if row.get('unexpected_tools'): raise ValueError('unexpected native tool must be reviewed')
        groups[(row['campaign'],row['model'],row['mode'],row['condition'])].append(row)
    summary=[]
    for key,items in sorted(groups.items()):
        complete=[r for r in items if r['status']=='completed' and r['metrics'] is not None]
        sequences=defaultdict(list)
        for row in complete:
            if row['sequence'] is not None: sequences[row['sequence']].append(row)
        summary.append(dict(zip(['campaign','model','mode','condition'],key),
            evidence_status=items[0]['evidence_status'],recorded_turns=len(items),measured_turns=len(complete),
            correct=sum(r.get('protocol_valid',True) and r.get('grade',{}).get('correct',False) for r in complete),
            sequences=len(sequences),complete_correct_sequences=sum(len(seq)==7 and all(r.get('protocol_valid',True) and r['grade']['correct'] for r in seq) for seq in sequences.values()),
            **{metric:sum(r['metrics'][metric] for r in complete) if complete else None for metric in
               ['input_tokens','cached_tokens','uncached_input_tokens','output_tokens','model_completions','wall_seconds','tool_seconds','observed_bytes','truncated_outputs','tool_failures']},
            observation_seconds=sum(r.get('observation_seconds',0) for r in complete)))
    (output/'runs.jsonl').write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows))
    write_json(output/'summary.json',summary)
    write_json(output/'provenance.json',provenance)
    artifact_hash=archive_files(artifact_files,output/'artifacts.tar.gz')
    write_json(output/'artifacts.json',{'path':'artifacts.tar.gz','sha256':artifact_hash,'files':len(artifact_files)})
    print(json.dumps(summary,ensure_ascii=False,indent=2))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=Path('campaigns'))
    parser.add_argument('--output',type=Path,default=Path('results/2026-10-01-observations'))
    parser.add_argument('--campaigns',default=','.join(CAMPAIGNS))
    parser.add_argument('--plot',action='store_true')
    args=parser.parse_args();export(args.root,args.output,args.campaigns.split(','))
    if args.plot: plot(args.output)


def plot(output):
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    from matplotlib.font_manager import FontProperties
    font=FontProperties(fname='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
    plt.rcParams.update({'font.family':font.get_name(),'axes.unicode_minus':False,
                         'svg.fonttype':'none','svg.hashsalt':'agent-data-observations'})
    rows=[json.loads(line) for line in (output/'runs.jsonl').read_text().splitlines()]
    labels={'none':'普通文件','discovery':'首轮原文','changes':'后续变化','both':'原文＋变化','instructions':'工作规则'}
    sequences=[]
    for condition,label in labels.items():
        campaign='retained-artifacts-v2'
        for replicate in (0,1):
            cases=sorted([row for row in rows if row['campaign']==campaign and row['condition']==condition and row['replicate']==replicate],key=lambda r:r['task'])
            sequences.append((f'{label} · {replicate+1}',[int(row['grade']['correct']) for row in cases]))
    fig,axis=plt.subplots(figsize=(11,6.4),layout='constrained')
    axis.imshow([values for _,values in sequences],cmap=ListedColormap(['#c76b65','#2e8b7c']),vmin=0,vmax=1,aspect='auto')
    for y,(_,values) in enumerate(sequences):
        for x,value in enumerate(values): axis.text(x,y,'✓' if value else '×',ha='center',va='center',color='white',fontsize=15)
    axis.set_xticks(range(7),['初次理解','新金额','数据变更','规则变更','无关改动','移动文件','新业务分类'])
    axis.set_yticks(range(len(sequences)),[label for label,_ in sequences])
    axis.tick_params(length=0)
    axis.set_title('解释如何被沿用，以及来源变化后是否仍正确',fontsize=17,pad=18)
    fig.supxlabel('Luna · high · 每行是一段连续工作；每题独立结果路径，保留全部此前产物',fontsize=11)
    fig.savefig(output/'continuation.png',dpi=180)
    fig.savefig(output/'continuation.svg',metadata={'Date':None})
    plt.close(fig)
    summary=json.loads((output/'summary.json').read_text())
    groups={row['condition']:row for row in summary if row['campaign']=='retained-artifacts-v2'}
    conditions=['none','discovery','changes','both'];colors=['#8492a6','#7298b5','#b38a53','#2e8b7c']
    fig,axes=plt.subplots(1,4,figsize=(13,4.5),layout='constrained')
    for axis,(metric,title,scale) in zip(axes,[('correct','答对任务数',1),('model_completions','模型调用次数',1),
                                              ('uncached_input_tokens','未缓存输入 token（千）',1000),('output_tokens','输出 token（千）',1000)]):
        values=[groups[c][metric]/scale for c in conditions]
        axis.bar(range(4),values,color=colors,width=.62)
        for i,value in enumerate(values):
            label=f'{int(value)}/14' if metric=='correct' else str(int(value)) if scale==1 else f'{value:.1f}'
            axis.text(i,value+max(values)*.025,label,ha='center',fontsize=11)
        axis.set_xticks(range(4),[labels[c] for c in conditions],rotation=28,ha='right',fontsize=10)
        axis.set_ylim(0,max(values)*1.2);axis.set_title(title,fontsize=12)
        axis.spines[['top','right']].set_visible(False);axis.grid(axis='y',alpha=.15);axis.set_axisbelow(True)
    fig.suptitle('首次观察与变化告知的拆分对照',fontsize=18)
    fig.supxlabel('每组两条七步序列，共 14 次请求 · Luna / high · 自动处理耗时另记',fontsize=11)
    fig.savefig(output/'observation-costs.png',dpi=180)
    fig.savefig(output/'observation-costs.svg',metadata={'Date':None})
    plt.close(fig)
    for path in output.glob('*.svg'):
        path.write_text('\n'.join(line.rstrip() for line in path.read_text().splitlines())+'\n')


if __name__=='__main__':main()
