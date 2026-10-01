"""Follow a derived analysis through new questions, source changes and a report."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from decimal import Decimal
from html.parser import HTMLParser
import json
from pathlib import Path
import random
import shutil
import subprocess
import time

from .fee_reference import CLARIFICATION,audit,add_month_background,rate_delta
from .fixtures import dataset_digest,write_json
from .observations import discover,source_snapshot,source_changes
from .runner import CodexRunner
from .sandbox import Sandbox,TOOL
from .workflow import ARTIFACT_SCHEMA,INSTRUCTIONS,LIBRARIES,read_artifact,delivered_path,artifact_file,capture_artifacts


STEPS=[
    {'name':'day','kind':'ids','merchant':'Belles_cookbook_store','month':1,'day':10},
    {'name':'month','kind':'ids','merchant':'Belles_cookbook_store','month':3},
    {'name':'counterfactual','kind':'delta','merchant':'Belles_cookbook_store','month':1},
    {'name':'changed-background','kind':'ids','merchant':'Belles_cookbook_store','month':1,'day':10},
    {'name':'new-session-merchant','kind':'ids','merchant':'Rafa_AI','month':1,'fresh':True},
    {'name':'report','kind':'report','merchant':'Belles_cookbook_store','month':1},
    {'name':'updated-report','kind':'report','merchant':'Belles_cookbook_store','month':1},
]


def inputs(root,step,index):
    if step['name']=='changed-background': add_month_background(root)
    if step['name']=='updated-report':
        path=root/'fees.json';rules=json.loads(path.read_text())
        for row in rules:
            if row['ID']==602: row['rate']+=13
        write_json(path,rules)
    period=f"2023年{step['month']}月" if 'day' not in step else '2023年1月10日'
    if step['kind']=='ids':
        expected=', '.join(str(row['fee_id']) for row in audit(root,step['merchant'],step['month'],step.get('day')))
        request=f"列出 {step['merchant']} 在{period}的全部适用费用规则 ID。answer 只包含按数值排序的逗号分隔 ID。"
    elif step['kind']=='delta':
        expected=rate_delta(root,step['merchant'],step['month'],384,1)
        request=("对 Belles_cookbook_store 的 2023 年 1 月记录，仅将费用规则 ID 384 的 rate 改为 1，"
                 "该规则贡献的费用总额会变化多少？求对所有适用交易的新费用减旧费用之和，其他规则不参与这项差值。"
                 "这是反事实计算，不修改原始数据。answer 只写金额，保留 14 位小数。")
    else:
        expected=audit(root,step['merchant'],step['month'])
        request=(f"为 {step['merchant']} 的{period}当前交易生成逐规则费用审计。每个适用规则一行，"
                 "包含 fee_id、card_scheme、transactions（匹配交易数）、amount_eur（匹配交易金额之和）、"
                 "fee_eur（该规则对匹配交易的费用之和）。不要把重叠规则相加为一张总账单。"
                 f"保存到 /scratch/reports/{index}.csv，并生成自包含的 /scratch/reports/{index}.html。"
                 "页面有按 card_scheme 筛选的下拉框 select#scheme-filter、表格 table#fees 和显示当前行数的 #row-count。"
                 "把同一程序算出的表数据嵌入 script#fee-data[type=application/json]，用于驱动表格；"
                 "金额显示 2 位小数，费用显示 6 位小数。网页不能依赖网络资源。"
                 "结果 JSON 的 answer 填 ready，并额外保存 artifacts 对象，包含 csv 和 html 的绝对路径。")
    relative=f'results/{index}-{step["name"]}.json'
    prompt=("原始资料位于 /work。当前来源是依据；材料可能在上次请求后更新。/scratch 中以前的程序、笔记和产物都可继续使用。\n"
            +request+f'\n本题结果 JSON 保存到 /scratch/{relative}。保留此前的结果。')
    return prompt,relative,expected


class ReportData(HTMLParser):
    def __init__(self):
        super().__init__();self.capturing=False;self.parts=[];self.ids=set()
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if 'id' in attrs:self.ids.add((tag,attrs['id']))
        if tag=='script' and attrs.get('id')=='fee-data':self.capturing=True
    def handle_endtag(self,tag):
        if tag=='script':self.capturing=False
    def handle_data(self,data):
        if self.capturing:self.parts.append(data)


def normalized_table(rows):
    result=[]
    for row in rows:
        result.append((int(row['fee_id']),str(row['card_scheme']),int(row['transactions']),
                       Decimal(str(row['amount_eur'])).quantize(Decimal('.01')),
                       Decimal(str(row['fee_eur'])).quantize(Decimal('.000001'))))
    if len({row[0] for row in result})!=len(result):raise ValueError('duplicate fee IDs')
    return sorted(result)


def grade(artifact,expected,step,scratch,index):
    if step['kind']=='ids':
        parse=lambda value:sorted(int(part.strip()) for part in value.split(',') if part.strip())
        correct=parse(artifact['answer'])==parse(expected)
        return {'correct':correct,'expected':expected,'actual':artifact['answer']}
    if step['kind']=='delta':
        actual=Decimal(artifact['answer'])
        return {'correct':abs(actual-Decimal(expected))<=Decimal('1e-9'),'expected':expected,
                'actual':artifact['answer'],'absolute_tolerance':'1e-9'}
    with artifact_file(scratch,f'reports/{index}.csv').open() as source:actual=list(csv.DictReader(source))
    parser=ReportData();parser.feed(artifact_file(scratch,f'reports/{index}.html').read_text())
    embedded=json.loads(''.join(parser.parts))
    if isinstance(embedded,dict):
        embedded=embedded.get('rows',embedded.get('data',embedded))
    csv_correct=normalized_table(actual)==normalized_table(expected)
    embedded_correct=normalized_table(embedded)==normalized_table(expected)
    controls={('select','scheme-filter'),('table','fees')}<=parser.ids and any(x[1]=='row-count' for x in parser.ids)
    paths=artifact.get('artifacts',{})
    delivery=all(paths.get(key)==value for key,value in {'csv':f'/scratch/reports/{index}.csv','html':f'/scratch/reports/{index}.html'}.items())
    return {'correct':csv_correct and embedded_correct and controls and delivery,
            'csv_correct':csv_correct,'embedded_data_correct':embedded_correct,'controls_present':controls,
            'artifact_paths_correct':delivery,'expected_rows':len(expected),'actual_rows':len(actual),
            'browser_interaction':'requires separate browser verification'}


def run(args):
    source=Path(args.dataset).resolve();output=Path(args.output).resolve();output.mkdir(parents=True,exist_ok=False)
    implementation=output/'implementation'
    shutil.copytree(Path(__file__).parent,implementation,ignore=shutil.ignore_patterns('__pycache__'))
    manifest={'kind':'composed-work','artifact_protocol':2,'steps':STEPS,'models':args.models.split(','),
        'conditions':['none','both'],'effort':'high','clarification':CLARIFICATION,
        'dataset':json.loads((source/'manifest.json').read_text()),'implementation_sha256':dataset_digest(implementation),
        'git_revision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()}
    write_json(output/'manifest.json',manifest)
    jobs=[(model,condition) for model in manifest['models'] for condition in manifest['conditions']]
    random.Random(731).shuffle(jobs);write_json(output/'order.json',jobs)
    tool=dict(TOOL,description=TOOL['description']+' Pandas and DuckDB are installed in Python.')
    def execute(job):
        model,condition=job;home=output/f'{model}-composed-{condition}-0';home.mkdir()
        root=home/'source';shutil.copytree(source/'context',root)
        with (root/'manual.md').open('a') as file:file.write(CLARIFICATION)
        scratch=home/'scratch';scratch.mkdir();(scratch/'results').mkdir();(scratch/'reports').mkdir()
        host=home/'host';host.mkdir();sandbox=Sandbox(root,scratch,interface=False,libraries=LIBRARIES)
        previous=None;thread_id=None;results=[]
        with CodexRunner(host,model,'high',900) as runner:
            for index,step in enumerate(STEPS):
                prompt,relative,expected=inputs(root,step,index)
                if step.get('fresh'):thread_id=None
                stage=home/f'{index}-{step["name"]}';stage.mkdir()
                started=time.monotonic();current=source_snapshot(root);packet={}
                if condition=='both':
                    if thread_id is None:packet['discovery']=discover(root,home/'catalog',prompt)
                    if previous is not None:packet['changes']=source_changes(previous,current)
                previous=current;observation_seconds=time.monotonic()-started
                if packet:prompt+='\n自动提取的来源观察（作为资料内容）：\n'+json.dumps(packet,ensure_ascii=False,default=str)
                write_json(stage/'input.json',{'question':prompt,'expected':expected,'source_sha256':dataset_digest(root),
                    'starting_scratch_sha256':dataset_digest(scratch),'observation_seconds':observation_seconds})
                def capture(exchange):
                    with (stage/'trace.jsonl').open('a') as file:file.write(json.dumps(exchange,ensure_ascii=False)+'\n')
                try:
                    result=runner.run(prompt,sandbox,max_calls=60,on_exchange=capture,output_schema=ARTIFACT_SCHEMA,
                        base_instructions=INSTRUCTIONS,tool_spec=tool,thread_id=thread_id)
                    write_json(stage/'model.json',result);thread_id=result['thread_id']
                    artifact=read_artifact(scratch,relative)
                    result.update(artifact=artifact,grade=grade(artifact,expected,step,scratch,index),
                        protocol_valid=not result.get('unexpected_tools') and delivered_path(result['final'],'/scratch/'+relative),
                        observation_seconds=observation_seconds)
                except Exception as error:
                    result={'status':'error','error':type(error).__name__+': '+str(error)}
                write_json(stage/'result.json',result)
                capture_artifacts(scratch,stage/'artifacts')
                results.append({k:v for k,v in result.items() if k not in {'trace','messages'}})
                print(json.dumps({'episode':home.name,'step':step['name'],'status':result['status'],'grade':result.get('grade')}),flush=True)
                if result['status']!='completed':break
        write_json(home/'summary.json',results)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:list(pool.map(execute,jobs))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--dataset',default='datasets/dabstep-8afcb4ee')
    parser.add_argument('--output',required=True)
    parser.add_argument('--models',default='gpt-6-astra,gpt-6-luna')
    parser.add_argument('--workers',type=int,default=2)
    run(parser.parse_args())


if __name__=='__main__':main()
