"""Generate task facts and independent expected answers before provider execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import random
import sqlite3


@dataclass
class Task:
    id: str
    prompt: str
    answers: list[str]
    unresolved: list[str]


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


DESCRIPTION = """# 数据说明

inventory.json 是对象目录。ref 为稳定身份，path 是当前位置；文件名不表示主题或先后顺序。
kind 为 markdown/html/record/opaque，record 使用 annotations.jsonl 的 id 作为 key。

learning.sqlite 中 attempts 每行是一次练习提交，question_ref 关联对象 ref。
seq 只表示同一题目的提交顺序；判断当前状态时取该题最大 seq。correct 为 0/1。
experiments 每行是一项实验结果，dataset 指数据集，valid 表示校验是否通过，
latency_us 为微秒；只在相同 dataset 下比较 latency_us，越低越好。note_ref 关联文档。

annotations.jsonl 每行是一条标注，subject_ref 是真实关系，quoted_ref 只是文本样例。
普通文档使用 CommonMark 链接；代码块、行内代码和仅出现地址文字不构成链接。
HTML 的 a[href] 是链接。repa:document/<ref>#<fragment> 指向对象及其内部位置。
相对路径按引用者所在目录解析，再对应 inventory.json 中的对象身份。
损坏或缺失的文件并不表示内容中不存在关联；对未能判断的对象保留其 ref。
"""


API_HELP = """# Python 接口

在 python3 中使用 `from agent_data_lab.access import Space; s = Space('/work')`。
所有原生文件、sqlite3、markdown_it 和 shell 仍可使用。接口按需使用。

- `s.objects()` -> inventory.json 的对象列表。
- `s.sql(query, params=())` -> SQLite 行字典列表。SQL 使用原生表名/字段名。
- `s.records('annotations')` -> 标注行字典列表。
- `s.read(ref, lines=None, revision=None)` -> {ref, revision, text}。lines 为从 1 开始的闭区间；过期 revision 报错。
- `s.search(query, within=None, limit=None)` -> {items, covered, unresolved, complete, matched_count, truncated}。
  字面子串查询，结果按 ref、line 排序后截断；每个命中行一项 {ref,line,text,revision}。
- `s.references_to(target, within=None)` -> {items, covered, unresolved, complete}。
  target 是对象 ref；within 限制引用者。每次实际引用分别返回 {ref,target,revision,relation,ordinal,...}。
  文档定位 line 为所在 Markdown 块起始行（1-based），ordinal 为块中第几个链接（1-based）；
  HTML ordinal 为文件中第几个 a[href]；记录返回 field。不会将文本样例识别为关系。

within 为 ref 列表，None 查询目录全部对象；[] 查询空集。重复 ref 不重复计数。
unresolved 是未能完成的 {ref,reason}，可通过原生方法继续处理。complete 仅表示覆盖完成；
truncated 表示返回结果被 limit 截断，不能解释为全部匹配。无自动链接扩张或推测语义关系。
一次脚本中可自由组合接口和原生操作，只输出需要模型观察的结果。
"""


HELPER_HELP = """# 来源辅助函数

Python 中 `from agent_data_lab.native import markdown_links, html_links, annotation_links, query_learning_db, load_annotations`。
这些函数与接口组的底层解析实现相同，均为可自由组合的普通函数：

- `markdown_links(text)` 枚举实际链接，包括 reference-style 与内嵌 HTML，排除代码样例。
  每项为 {uri, line, end_line, ordinal, context, relation}；line 为块起始行（1-based），
  ordinal 为块内所有链接的序号（1-based）；uri 是原生地址，可能是相对路径。
- `html_links(text)` 枚举 a[href]，返回 {uri,line,column,ordinal,context,relation}；ordinal 为文件内链接顺序。
- `annotation_links(row)` 返回标注对象的声明关系，字段为 {uri,field,ordinal,relation}。
- `query_learning_db(query, params=(), root='/work')` 执行原生只读 SQL，返回行字典列表，与 Space.sql 共用实现。
- `load_annotations(root='/work')` 读取 JSONL 标注，返回行字典列表，与 Space.records 共用实现。

三个函数都是迭代器。继续使用 json、sqlite3、pathlib、urllib.parse 等原生库读取数据、处理地址和组合结果。
"""


def generate(root: Path, seed: int, count: int = 120, *, variant: str = "stable", scope_file: bool = False) -> list[Task]:
    if count < 24:
        raise ValueError("count must be >= 24")
    root.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    (root / "notes").mkdir(exist_ok=True)
    refs = ["d" + rng.randbytes(5).hex() for _ in range(count)]
    target = refs[0]
    inventory, facts, occurrences, attempts, annotations, experiments = [], {}, [], [], [], []
    target_path = None
    for index, ref in enumerate(refs):
        token = "K" + rng.randbytes(4).hex()
        path = f"notes/{rng.randrange(10000,99999)}-{index}.md"
        if index == 0:
            target_path = path
        lines = [f"# 学习记录 {index}", "", f"对象：{ref}", f"校验词：{token}", ""]
        latest_wrong = index % 4 == 1
        has_phrase = index % 3 == 1 or index % 7 == 0
        lines += ["## 观察", "", ("写回路径需要单独分析脏块写出。" if has_phrase else "读取路径需要分析命中后的数据返回。"), ""]
        lines += ["## 参考", ""]
        if index % 9 == 1:
            occurrences.append(f"{ref}@{len(lines) + 1}:1")
            lines += [f"比较 [材料](repa:document/{target}#example)。", ""]
        if index % 13 == 2:
            occurrences.extend([f"{ref}@{len(lines) + 1}:1", f"{ref}@{len(lines) + 1}:2"])
            lines += [f"先读 [定义][basis]，再复查 [前提][basis]。", "", f"[basis]: repa:document/{target}#assumptions", ""]
        if variant == "native" and index % 11 == 4:
            occurrences.append(f"{ref}@{len(lines) + 1}:1")
            lines += [f'<a href="repa:document/{target}#embedded">嵌入链接</a>', ""]
        if variant == "native" and index % 2 == 0:
            lines = [line.replace(f"repa:document/{target}", Path(target_path).name) for line in lines]
        # Search text alone cannot distinguish these from actual links.
        lines += [f"地址样例 `repa:document/{target}`。", "", "```md", f"[不是引用](repa:document/{target})", "```", ""]
        if index % 5 == 0:
            lines += [f"代码样例之外的文字 repa:document/{target} 也不是链接。", ""]
        lines += ["## 背景", "", "记录保留了计算的边界条件和已有观察。" * rng.randrange(15, 45), ""]
        (root / path).write_text("\n".join(lines))
        inventory.append({"ref": ref, "kind": "markdown", "path": path})
        facts[ref] = {"token": token, "wrong": latest_wrong, "phrase": has_phrase}
        # Earlier state intentionally contradicts latest state.
        for seq, correct in [(1, int(latest_wrong)), (2, int(not latest_wrong))]:
            attempts.append((f"a{index}-{seq}", ref, seq, correct))
        latency = rng.randrange(50, 1200)
        experiments.append((f"e{index:03}", "cpu" if index % 3 else "vector", int(index % 5 != 0), latency, ref))
        if index < 16:
            annotations.append({"id": f"n{index}", "subject_ref": target if index % 3 == 0 else ref,
                                "quoted_ref": target, "text": f"保留本条说明 {index}"})

    rng.shuffle(attempts)
    with sqlite3.connect(root / "learning.sqlite") as db:
        db.executescript("CREATE TABLE attempts (id TEXT PRIMARY KEY, question_ref TEXT, seq INTEGER, correct INTEGER);"
                         "CREATE TABLE experiments (id TEXT PRIMARY KEY, dataset TEXT, valid INTEGER, latency_us INTEGER, note_ref TEXT);")
        db.executemany("INSERT INTO attempts VALUES (?,?,?,?)", attempts)
        db.executemany("INSERT INTO experiments VALUES (?,?,?,?,?)", experiments)
    (root / "annotations.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in annotations))
    for row in annotations:
        inventory.append({"ref": "annotation:" + row["id"], "kind": "record", "key": row["id"]})
    html_ref = "page:" + str(seed)
    html_uri = target_path if variant == "native" else f"repa:document/{target}"
    html_text = f'<h1>交互材料</h1>\n<a href="{html_uri}#demo">演示来源</a>\n<code>repa:document/{target}</code>\n'
    (root / "demo.html").write_text(html_text)
    inventory.append({"ref": html_ref, "kind": "html", "path": "demo.html"})
    missing, broken, opaque = "missing:" + str(seed), "broken:" + str(seed), "opaque:" + str(seed)
    (root / "broken.md").write_bytes(b"\xff\xfe\x00invalid")
    (root / "unclassified.txt").write_text(f"独立文字资料。唯一显式链接采用 CommonMark：[材料](repa:document/{target})。\n")
    inventory.extend([
        {"ref": missing, "kind": "markdown", "path": "lost.md"},
        {"ref": broken, "kind": "markdown", "path": "broken.md"},
        {"ref": opaque, "kind": "opaque", "path": "unclassified.txt"},
    ])
    rng.shuffle(inventory)
    write_json(root / "inventory.json", inventory)
    (root / "README.md").write_text("# 学习空间\n\ninventory.json 列出对象 ref、kind 与当前位置 path 或记录 key。\n"
        "notes/ 保存 Markdown；demo.html 是网页；annotations.jsonl 是标注；learning.sqlite 是 SQLite 数据库。\n"
        "文档内使用 repa:document/<ref> 表示对象地址。\n")
    wrong = sorted(ref for ref, fact in facts.items() if fact["wrong"])
    both = sorted(ref for ref, fact in facts.items() if fact["wrong"] and fact["phrase"])
    refs_json = json.dumps(refs, ensure_ascii=False)
    reference_scope = refs
    if scope_file:
        reference_scope = refs[::2] + refs[1:2]
        write_json(root / "reference-scope.json", reference_scope)
        refs_json = "reference-scope.json 中列出的对象引用集合"
    valid_experiments = [row for row in experiments if row[1] == "cpu" and row[2] and facts[row[4]]["wrong"]]
    best = min(valid_experiments, key=lambda row: (row[3], row[0]))
    mixed_scope = [refs[1], refs[2], html_ref, "annotation:n0", "annotation:n1", opaque, missing, broken]
    mixed_answers = [item for item in occurrences if item.split("@")[0] in mixed_scope]
    mixed_answers += [f"{html_ref}@2:1", "annotation:n0@subject_ref", f"{opaque}@1:1"]
    return [
        Task("lookup", f"读取对象 {target}，返回它的校验词。answers 只含这个词。", [facts[target]["token"]], []),
        Task("latest", "列出最近一次提交仍然答错的全部题目 ref。不要把历史错误当作当前错误。answers 为 ref 列表。", wrong, []),
        Task("join", "在最近一次提交仍答错的题目中，找到正文包含字面短语‘写回路径’的全部文档。answers 每项使用 ref=校验词 格式。", [ref + "=" + facts[ref]["token"] for ref in both], []),
        Task("references", f"找出对象 {target} 在下列范围内的全部实际链接出现位置：{refs_json}。使用 CommonMark 规则，包括其中的 HTML a[href]；排除代码和仅出现地址的文字，reference-style 链接的每次使用都计入。answers 每项为 ref@块起始行:块内链接序号，均从1开始；重复引用逐项保留。", sorted(item for item in occurrences if item.split('@')[0] in reference_scope), []),
        Task("scoped", "在最近一次提交仍答错的题目范围内，搜索包含字面短语‘写回路径’的文档。按 ref 字典序返回前三个不同文档的 ref。", both[:3], []),
        Task("mixed", f"目标是 {target}。在范围 {json.dumps(mixed_scope)} 中找出全部实际引用。Markdown/CommonMark 的真实链接、HTML a[href]、标注的 subject_ref 都计入；unclassified.txt 中的文字明确声明了其链接语法，应继续读取处理。answers 文档用 ref@块起始行:块内链接序号，HTML用 ref@行:文件内链接序号，标注用 ref@subject_ref。unresolved 只列最终仍无法判断的对象 ref。", sorted(mixed_answers), [broken, missing]),
        Task("decision", "从 cpu 数据集、校验通过、关联题目最近一次提交仍答错的实验中，选择 latency_us 最低的一项；同值按实验 id 字典序。answers 返回两个字符串：实验 id、关联文档的校验词。", [best[0], facts[best[4]]["token"]], []),
        Task("empty", "在显式空范围 [] 内，搜索字面短语‘写回路径’，返回匹配对象 ref。", [], []),
    ]


def dataset_digest(root: Path) -> str:
    digest = sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def dump_tasks(path: Path, tasks: list[Task]):
    write_json(path, [asdict(task) for task in tasks])
