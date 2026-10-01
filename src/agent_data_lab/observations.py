"""Source-derived observations, without domain interpretation or model calls."""

from difflib import unified_diff
from hashlib import sha256
import json
from pathlib import Path

from .catalog import Catalog,fingerprint


def source_snapshot(root):
    """The root is the declared query domain; no authority over other sources."""
    root=Path(root).resolve(); result={}
    for path in sorted(root.rglob('*')):
        if any(part.startswith('.') for part in path.relative_to(root).parts):continue
        if not path.is_symlink() and not path.is_file(): continue
        try:
            if not path.resolve().is_relative_to(root):
                raise ValueError('Source resolves outside the declared root; an explicit source binding is required.')
            size=path.stat().st_size
            if size<=65536:
                content=path.read_bytes()
                entry={'revision':sha256(content).hexdigest(),'bytes':len(content)}
                try: entry['text']=content.decode('utf-8')
                except UnicodeDecodeError: pass
            else:
                entry={'revision':fingerprint(path),'bytes':size}
        except (OSError,ValueError) as error:
            entry={'revision':None,'error':str(error)}
        result[str(path.relative_to(root))]=entry
    return result


def source_changes(before,after):
    changes=[]
    for path in sorted(before.keys()|after.keys()):
        old,new=before.get(path),after.get(path)
        if old is not None and new is not None and old['revision']==new['revision'] and old.get('error')==new.get('error'): continue
        item={'path':path,'change':'added' if old is None else 'removed' if new is None else 'modified',
              'before':old and old['revision'],'after':new and new['revision']}
        if old is not None and new is not None and 'text' in old and 'text' in new:
            diff=''.join(unified_diff(old['text'].splitlines(True),new['text'].splitlines(True),
                fromfile=path+' (previous)',tofile=path+' (current)',n=3))
            item.update(diff=diff[:8000],diff_truncated=len(diff)>8000)
        changes.append(item)
    return {'scope':'non-hidden source files below the declared root; scratch artifacts are excluded',
            'changes':changes,'unchanged_count':len(after)-sum(x['change']!='removed' for x in changes),
            'unavailable':[{'path':path,'error':item['error']} for path,item in after.items() if 'error' in item]}


def discover(root,cache,question):
    catalog=Catalog(root,cache)
    try:
        result=catalog.find(question)
        # Internal SQL names are not needed when only passing source observations.
        for item in result['matches']:
            if item['line']==0:
                description=json.loads(item['text'])
                description.pop('table',None)
                item['text']=json.dumps(description,ensure_ascii=False)
        return {'selection':'lexical search over document sections and inferred schemas; not an exhaustive interpretation',
                'observations':result['matches'],'unprofiled':result.get('unprofiled',[]),
                'candidate_count':result['match_count'],'truncated':result['truncated'],'searches':result['searches']}
    finally: catalog.close()
