"""Fetch public, revision-pinned experimental inputs and verify every file."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
from urllib.request import Request,urlopen


def valid(path,item):
    return (path.is_file() and path.stat().st_size==item['bytes']
            and sha256(path.read_bytes()).hexdigest()==item['sha256'])


def fetch(manifest_path,output):
    manifest=json.loads(manifest_path.read_text())
    output.mkdir(parents=True,exist_ok=True)
    base=f"https://huggingface.co/datasets/{manifest['repository']}/resolve/{manifest['revision']}/"
    for item in manifest['files']:
        path=(output/item['path']).resolve()
        if not path.is_relative_to(output.resolve()): raise ValueError('path outside dataset root')
        if path.exists():
            if valid(path,item): continue
            raise ValueError(f'existing input differs from manifest: {path}')
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_name(path.name+'.part')
        try:
            request=Request(base+item['upstream'],headers={'User-Agent':'agent-data-lab/0.1'})
            with urlopen(request,timeout=60) as response,temporary.open('wb') as destination:
                shutil.copyfileobj(response,destination)
            if not valid(temporary,item): raise ValueError('download hash or length mismatch: '+item['path'])
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--manifest',type=Path,default=Path('data-sources/dabstep.json'))
    parser.add_argument('--output',type=Path,default=Path('datasets/dabstep-8afcb4ee'))
    args=parser.parse_args(); fetch(args.manifest,args.output)


if __name__=='__main__': main()
