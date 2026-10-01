"""Program-readable descriptions of model-authored work, without owning its data."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path


def digest(path: Path) -> str | None:
    try:
        return sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def contained(root: Path, value: str) -> Path:
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"path outside declared root: {value}")
    return path


def prepare_records(records: list[dict], source: Path, scratch: Path) -> list[dict]:
    """Attach byte revisions only to the dependencies the model actually named."""
    result, seen = [], set()
    for record in records:
        key = record["id"]
        if not isinstance(key, str) or not key or key in seen:
            raise ValueError("work ids must be nonempty and unique")
        seen.add(key)
        for name in ("title", "purpose", "limits", "entrypoint"):
            if not isinstance(record.get(name), str):
                raise ValueError(f"missing textual field: {name}")
        for name in ("artifacts", "sources", "depends_on"):
            if not isinstance(record.get(name), list) or not all(isinstance(x, str) for x in record[name]):
                raise ValueError(f"invalid list field: {name}")
        for artifact in record["artifacts"]:
            if not contained(scratch, artifact).is_file():
                raise ValueError(f"unknown work artifact: {artifact}")
        fields = {name: record[name] for name in ("id", "title", "purpose", "limits", "entrypoint", "artifacts", "depends_on")}
        result.append({**fields, "sources": [
            {"path": value, "revision": digest(contained(source, value))}
            for value in record["sources"]]})
    for record in result:
        if any(value not in seen for value in record["depends_on"]):
            raise ValueError("work dependency references an unknown record")
    return result


def render_document(records: list[dict]) -> str:
    """Render all description fields; the JSON form receives no additional facts."""
    lines = ["# 已完成工作的说明", "", "来源版本只表示实际文件字节；未登记的依赖需要自行核对。", ""]
    for record in records:
        lines.extend([f"## {record['id']} · {record['title']}", "",
                      f"用途：{record['purpose']}", "", f"适用条件：{record['limits']}", "",
                      f"入口：{record['entrypoint']}", "", "工件："])
        lines.extend(f"- {path}" for path in record["artifacts"])
        lines.extend(["", "依据及字节版本："])
        lines.extend(f"- {item['path']}：{item['revision']}" for item in record["sources"])
        lines.extend(["", "依赖的工作：", *[f"- {value}" for value in record["depends_on"]], ""])
    return "\n".join(lines) + "\n"


class WorkIndex:
    def __init__(self, file="/scratch/work-index/records.json", source="/work", scratch="/scratch"):
        self.file, self.source, self.scratch = Path(file), Path(source), Path(scratch)

    def records(self) -> list[dict]:
        return json.loads(self.file.read_text())

    def select(self, ids=None, *, text=None) -> list[dict]:
        """Return complete records from an explicit scope; text is a literal filter."""
        records = self.records()
        if ids is not None:
            requested = set(ids)
            unknown = requested - {record["id"] for record in records}
            if unknown:
                raise KeyError(sorted(unknown))
            records = [record for record in records if record["id"] in requested]
        if text is not None:
            records = [record for record in records if text.casefold() in json.dumps(record, ensure_ascii=False).casefold()]
        return records

    def changes(self, ids=None) -> list[dict]:
        changes = []
        for record in self.select(ids):
            for item in record["sources"]:
                current = digest(contained(self.source, item["path"]))
                if current != item["revision"]:
                    changes.append({"work": record["id"], "path": item["path"],
                                    "before": item["revision"], "after": current})
        return changes

    def artifacts(self, ids=None) -> list[dict]:
        return [{"work": record["id"], "path": str(contained(self.scratch, path))}
                for record in self.select(ids) for path in record["artifacts"]]


INSTRUCTIONS = """# 工作记录入口

records.json 记录已经完成的工作及其依据，原始文件和程序仍直接可用。
该记录是此前模型形成的解释，来源改变或任务超出适用范围时需要核对。

```python
import sys
sys.path.insert(0, '/scratch/work-index')
from work_records import WorkIndex
index = WorkIndex()
records = index.select()  # 或 select(ids=[...], text='字面词')；空 ids 返回空集合
changed = index.changes()  # 只核对已登记的来源；不判断业务上是否需要重建
paths = index.artifacts(ids=[...])  # 普通文件路径，可直接读取、连接和筛选
```

必要时编辑 records.json 维护说明，或继续使用普通脚本、文件与查询。
结构不负责执行业务程序、不推断未登记的依赖，也不替代来源。
"""
