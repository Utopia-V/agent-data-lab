"""Represent identical current fee records with different file boundaries."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil

from .episodes import CLARIFICATION,reference_answer
from .fixtures import write_json


TASKS=[{'name':'hospitality','amount':'10','account':'H','category':'Eating Places and Restaurants'},
       {'name':'books','amount':'12.75','account':'R','category':'Book Stores'}]


def prepare(source,output,parts,history):
    output.mkdir(parents=True,exist_ok=False)
    root=output/'context'; shutil.copytree(source/'context',root)
    rules=json.loads((root/'fees.json').read_text())
    tasks=[]
    for task in TASKS:
        expected=reference_answer(root,task,10000)['answer']
        tasks.append({'task_id':task['name'],'answer':expected,
            'question':f"Using the current fee schedule, what is the equally weighted average GlobalCard fee for a EUR {task['amount']} transaction, account type {task['account']}, merchant category {task['category']}? Match only those specified characteristics; do not include archived fee schedules.",
            'guidelines':'Answer must be just a number rounded to 6 decimals.'})
    if parts==1:
        source_description='the file `fees.json`'
    else:
        directory=root/'pricing/current'; directory.mkdir(parents=True)
        for part in range(parts):
            write_json(directory/f'part-{part:04d}.json',rules[part::parts])
        (root/'fees.json').unlink()
        source_description='the union of all JSON files in `pricing/current/`. Every part belongs to the current schedule; a single part is incomplete'
    manual=root/'manual.md'
    text=manual.read_text().replace('the annexed file `fees.json`',source_description)
    text+='\n'+CLARIFICATION
    if history:
        archived=root/'archive'; archived.mkdir()
        old=[dict(row,rate=row['rate']+100) for row in rules]
        write_json(archived/'fees.json',old)
        text+='\n## Historical exports\n\nFiles under `archive/` are historical exports and are excluded from the current fee schedule. Identical columns and IDs do not make them current records.\n'
    manual.write_text(text)
    (output/'dev.jsonl').write_text(''.join(json.dumps(task,ensure_ascii=False)+'\n' for task in tasks))
    shutil.copy2(source/'LICENSE',output/'LICENSE')
    files=[{'path':str(path.relative_to(output)),'bytes':path.stat().st_size,
            'sha256':sha256(path.read_bytes()).hexdigest()} for path in sorted(output.rglob('*')) if path.is_file()]
    write_json(output/'manifest.json',{'kind':'controlled-layout-variant','parts':parts,'history':history,
        'upstream':json.loads((source/'manifest.json').read_text()),'files':files,
        'invariant':'identical current rules and answers; only file partitioning and explicitly excluded history vary'})


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,default=Path('datasets/dabstep-8afcb4ee'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--parts',type=int,default=1)
    parser.add_argument('--history',action='store_true')
    args=parser.parse_args()
    if not 1<=args.parts<=1000: raise ValueError('parts must be between 1 and 1000')
    prepare(args.source,args.output,args.parts,args.history)


if __name__=='__main__': main()
