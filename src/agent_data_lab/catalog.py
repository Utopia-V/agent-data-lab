"""Generic source inspection and structural text search over native files."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3

import duckdb
from markdown_it import MarkdownIt


def fingerprint(path: Path) -> str:
    digest=sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(1024*1024): digest.update(chunk)
    return digest.hexdigest()


def sql_string(value):
    return "'"+str(value).replace("'","''")+"'"


def search_terms(text):
    if re.search(r'[\u3400-\u9fff]',text):
        import jieba
        jieba.setLogLevel(40)
        text=' '.join(jieba.cut_for_search(text))
    return re.findall(r'\w+',text)


def markdown_sections(text):
    lines=text.splitlines()
    headings=[]
    tokens=MarkdownIt('commonmark').parse(text)
    for i,token in enumerate(tokens):
        if token.type=='heading_open' and token.map is not None:
            headings.append((token.map[0],int(token.tag[1:]),tokens[i+1].content))
    if not headings:
        return [{'line':1,'end_line':len(lines),'heading':'','text':text}]
    result=[]; chain=[]
    if headings[0][0]>0:
        result.append({'line':1,'end_line':headings[0][0],'heading':'','text':'\n'.join(lines[:headings[0][0]])})
    for i,(start,level,title) in enumerate(headings):
        chain=[entry for entry in chain if entry[0]<level]+[(level,title)]
        end=headings[i+1][0] if i+1<len(headings) else len(lines)
        result.append({'line':start+1,'end_line':end,'heading':' / '.join(x[1] for x in chain),
                       'text':'\n'.join(lines[start:end])})
    return result


class Catalog:
    """Profiles and sections are derived; source bytes remain authoritative.

    File locations identify sources in this prototype. A product content owner
    supplies its stable identities when mapping these observations to content.
    """

    def __init__(self, root='/work', cache='/scratch/catalog'):
        self.root=Path(root).resolve(); self.cache=Path(cache).resolve()
        self.cache.mkdir(parents=True,exist_ok=True)
        self.state_path=self.cache/'sources.json'
        reset=False
        try:
            self.state=json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
            if not isinstance(self.state,dict):raise ValueError('invalid derived profile state')
        except (ValueError,UnicodeError):
            self.state={};reset=True
        self.db=duckdb.connect()
        index_path=self.cache/'text.sqlite'
        self.index=sqlite3.connect(index_path)
        try:version=self.index.execute('PRAGMA user_version').fetchone()[0]
        except sqlite3.DatabaseError:
            self.index.close();index_path.unlink()
            self.index=sqlite3.connect(index_path);version=0
        self.reindex=reset or version!=3
        if self.reindex:
            self.index.execute('DROP TABLE IF EXISTS units')
        self.index.execute('CREATE VIRTUAL TABLE IF NOT EXISTS units USING fts5(path UNINDEXED, revision UNINDEXED, start UNINDEXED, end UNINDEXED, heading UNINDEXED, body UNINDEXED, keywords)')
        self.index.execute('PRAGMA user_version=3')
        self.changes=[]
        self.refresh()

    def refresh(self):
        current={str(path.relative_to(self.root)):path for path in self.root.rglob('*')
                 if (path.is_symlink() or path.is_file()) and not any(part.startswith('.') for part in path.relative_to(self.root).parts)}
        changes=[]
        for location in set(self.state)-set(current):
            self.state.pop(location)
            self.index.execute('DELETE FROM units WHERE path=?',(location,))
            changes.append({'path':location,'change':'removed'})
        for location,path in current.items():
            previous=self.state.get(location)
            try:
                if not path.resolve().is_relative_to(self.root):
                    raise ValueError('Source resolves outside the declared root; an explicit source binding is required.')
                revision=fingerprint(path)
            except (OSError,ValueError) as error:
                profile={'path':location,'revision':None,'format':path.suffix.lower().lstrip('.'),'error':str(error)}
                self.index.execute('DELETE FROM units WHERE path=?',(location,))
                self.state[location]=profile
                if profile!=previous: changes.append({'path':location,'change':'unavailable'})
                continue
            if previous is None or previous.get('revision')!=revision or self.reindex:
                profile={'path':location,'revision':revision,'bytes':path.stat().st_size,
                         'format':path.suffix.lower().lstrip('.')}
                self.index.execute('DELETE FROM units WHERE path=?',(location,))
                try:
                    self._profile(path,profile)
                except (OSError,UnicodeError,ValueError,duckdb.Error) as error:
                    profile['error']=str(error)
                self.state[location]=profile
                changes.append({'path':location,'change':'new' if previous is None else 'modified'})
        self.index.commit()
        temporary=self.state_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.state,ensure_ascii=False,indent=2,default=str)+'\n')
        temporary.replace(self.state_path)
        self.changes=changes
        self.reindex=False
        return changes

    def _index(self,profile,start,end,heading,body):
        self.index.execute('INSERT INTO units VALUES (?,?,?,?,?,?,?)',
            (profile['path'],profile['revision'],start,end,heading,body,' '.join(search_terms(heading+'\n'+body))))

    def _expression(self,path):
        if path.suffix.lower()=='.csv': return f'read_csv_auto({sql_string(path)}, sample_size=-1)'
        if path.suffix.lower() in {'.json','.jsonl','.ndjson'}: return f'read_json_auto({sql_string(path)}, sample_size=-1)'
        if path.suffix.lower()=='.parquet': return f'read_parquet({sql_string(path)})'
        return None

    def _profile(self,path,profile):
        expression=self._expression(path)
        if expression:
            columns=self.db.sql(f'DESCRIBE SELECT * FROM {expression}').fetchall()
            profile['columns']=[{'name':r[0],'type':r[1]} for r in columns]
            profile['rows']=self.db.sql(f'SELECT count(*) FROM {expression}').fetchone()[0]
            relation=self.db.sql(f'SELECT * FROM {expression} LIMIT 2')
            profile['sample']=[dict(zip(relation.columns,row)) for row in relation.fetchall()]
            profile['schema_origin']='DuckDB inference over the complete source'
            description=json.dumps({'path':profile['path'],'columns':profile['columns']},ensure_ascii=False)
            self._index(profile,0,0,profile['path'],description)
        elif path.suffix.lower() in {'.md','.txt','.rst'}:
            content=path.read_bytes(); text=content.decode('utf-8')
            profile['revision']=sha256(content).hexdigest()
            sections=markdown_sections(text) if path.suffix.lower()=='.md' else [{'line':1,'end_line':len(text.splitlines()),'heading':'','text':text}]
            profile['outline']=[{key:section[key] for key in ['line','end_line','heading']} for section in sections]
            for section in sections:
                self._index(profile,section['line'],section['end_line'],section['heading'],section['text'])
        else:
            profile['error']='No structural profile for this format; native file remains available.'

    def sources(self):
        """Return format, schema/sample or outline, observed version and failures."""
        self.refresh()
        return list(self.state.values())

    def find(self,query,limit=5):
        """Search document sections and table schemas, not all table cell values."""
        if not isinstance(limit,int) or limit<0: raise ValueError('limit must be a nonnegative integer')
        self.refresh()
        terms=search_terms(query)
        if not terms:
            return {'matches':[],'match_count':0,'truncated':False,'searches':'document sections and schemas',
                    'unprofiled':[{'path':p['path'],'error':p['error']} for p in self.state.values() if 'error' in p]}
        expression=' OR '.join('"'+term.replace('"','""')+'"' for term in terms)
        count=self.index.execute('SELECT count(*) FROM units WHERE units MATCH ?',(expression,)).fetchone()[0]
        rows=self.index.execute('SELECT path,revision,start,end,heading,body,bm25(units) FROM units WHERE units MATCH ? ORDER BY bm25(units),path,start LIMIT ?',
                                (expression,limit)).fetchall()
        return {'matches':[{'path':row[0],'revision':row[1],'line':row[2],'end_line':row[3],
                            'heading':row[4],'text':row[5]} for row in rows],
                'searches':'document sections and table schemas; use SQL for table values',
                'match_count':count,'truncated':count>len(rows),
                'unprofiled':[{'path':p['path'],'error':p['error']} for p in self.state.values() if 'error' in p]}

    def read(self,path,start=1,end=None,revision=None):
        target=(self.root/path).resolve()
        if not target.is_relative_to(self.root): raise ValueError('path outside source root')
        content=target.read_bytes()
        observed=sha256(content).hexdigest()
        if revision is not None and revision!=observed: raise ValueError('source revision changed')
        text=content.decode('utf-8').splitlines()
        return {'path':path,'revision':observed,'line':start,'text':'\n'.join(text[start-1:end])}

    def close(self):
        self.db.close(); self.index.close()
