"""Frozen project-handoff tasks and independent source-grounded expectations."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess

from .fixtures import dataset_digest, write_json


REVISION = "040aa16d7c7a142cdebf39388486c1bc65a98387"
ISSUES = (17, 19, 21, 22, 23)

# Checked against the fixed TypeBox declarations, not the candidate work index.
METHOD_FIELDS = {
    "content.list": ("spaceId", "path"),
    "content.get": ("target", ""),
    "content.read": ("target", "offset limit revision"),
    "content.write": ("target operationId value base", ""),
    "content.edit": ("target operationId edits", ""),
    "content.applyPatch": ("spaceId operationId patch", ""),
    "content.move": ("target operationId destination base", "container"),
    "content.copy": ("target operationId destination base", "container"),
    "material.collect": ("target operationId destination base", ""),
    "content.associate": ("spaceId operationId location role", "id"),
    "content.relink": ("ref operationId location base", ""),
    "content.remove": ("target operationId base", "detach"),
    "content.setComposition": ("ref operationId base members resources", ""),
    "operation.get": ("spaceId operationId", ""),
    "operation.undo": ("spaceId operationId undoOperationId", ""),
    "operation.reconcile": ("spaceId operationId", ""),
    "operation.prune": ("spaceId operationIds", ""),
    "resource.hold": ("spaceId id", "targets resources"),
    "resource.hold.get": ("spaceId id", ""),
    "resource.hold.renew": ("spaceId id", ""),
    "resource.release": ("spaceId id", ""),
    "resource.collect": ("spaceId", ""),
    "context.get": ("spaceId", ""),
    "context.set": ("spaceId operationId base binding", ""),
    "context.preview": ("spaceId", ""),
}

POLICY = {"preparation_ms": 600000, "hold_ms": 3600000, "upload_limit_bytes": 67108864,
          "resource_download_type": "application/octet-stream", "resource_download_disposition": "attachment"}
ROADMAP = {"resource_backend_issue": 17, "requests_issue": 19, "shell_issue": 21,
           "material_search_issue": 22, "display_bridge_issue": 23}
FILTERS = {
    "operation_without_base": [name for name, (required, _) in METHOD_FIELDS.items()
                               if "operationId" in required.split() and "base" not in required.split()],
    "requires_base": [name for name, (required, _) in METHOD_FIELDS.items() if "base" in required.split()],
}
INTEGRATION = {"display_bridge_issue": 23, "display_dependencies": [10, 17, 20, 21],
               "model_tools": ["read", "edit", "write", "apply_patch"],
               "public_run_steer_registered": False,
               "resource_hold_registered": True,
               "display_page_receives_host_key": False}
UPDATED = {**POLICY, "hold_ms": 1800000, "upload_limit_bytes": 33554432,
           "cases": {"disconnected_after_45_minutes": "lease_expired", "active_after_45_minutes": "available",
                     "renew_after_release": "lease_expired", "another_host_get": "permission_required"}}
SETTINGS = {"reset_required": ["scope", "namespace", "key", "base"],
            "set_required": ["scope", "namespace", "key", "value", "base"],
            "scope_kinds": ["application", "space", "session"],
            "file_changes_modes": ["on-demand", "notice", "diff"],
            "reset_requires_operation_id": False}

WARM_TASKS = [
    {"id": "method-catalog", "question": "为接入 Repa 的客户端制作当前内容协议清单。查明 contentMethods 登记的全部方法（含其他命名空间），"
     "每个方法列出顶层必填和可选参数。保存 JSON：{methods:[{method,required:[字段名],optional:[字段名]}]}。"
     "以本地源码的实际声明为准。保存有用的提取程序、说明或工作结果，供后续工作使用。",
     "expected": {"methods": [{"method": name, "required": required.split(), "optional": optional.split()}
                              for name, (required, optional) in METHOD_FIELDS.items()]}},
    {"id": "resource-policy", "question": "准备资源客户端的接入说明。结合实现和文档，核对默认 preparation 期限、hold 期限、单次 HTTP 上传的最大字节数，"
     "以及资源下载使用的 Content-Type 和 Content-Disposition。保存 JSON："
     "{preparation_ms:整数,hold_ms:整数,upload_limit_bytes:整数,resource_download_type:字符串,resource_download_disposition:字符串}。"
     "另存必要的说明和计算或提取方法。", "expected": POLICY},
    {"id": "task-owners", "question": "根据本地 Issue 快照为交接整理任务归属。分别找资源后端、请求投递、命令执行、材料检索、交互产物桥接的负责 Issue。"
     "保存 JSON：{resource_backend_issue:编号,requests_issue:编号,shell_issue:编号,material_search_issue:编号,display_bridge_issue:编号}。"
     "Issue 处于 OPEN 不等于正文说的每项能力都未实现；保存能帮助后续接入的说明。", "expected": ROADMAP},
]

TASKS = [
    {"id": "client-validation", "question": "客户端要生成参数检查清单。只看 contentMethods 已登记方法的顶层参数：列出必须传 operationId 但不要求 base 的全部方法，"
     "以及要求 base 的全部方法。保存 JSON：{operation_without_base:[方法名],requires_base:[方法名]}。"
     "按参数声明筛选，不按方法名猜测是否修改内容。", "expected": FILTERS},
    {"id": "integration-plan", "question": "为生成网页接入准备依赖清单，结合 Issue 正文、固定实现和设计文档回答："
     "交互产物桥接的 Issue 编号和该 Issue 在依赖协作段列出的全部直接依赖编号；当前 createContentTools 实际返回的模型工具名；"
     "当前公开协议是否已登记 run.steer 与 resource.hold；设计是否允许把完整 hostKey 交给生成页面。"
     "保存 JSON：{display_bridge_issue:整数,display_dependencies:[编号],model_tools:[名称],public_run_steer_registered:布尔,"
     "resource_hold_registered:布尔,display_page_receives_host_key:布尔}。", "expected": INTEGRATION},
    {"id": "changed-policy", "change": True, "question": "资源实现已更新，旧开发文档还未同步。更新客户端实际策略：返回 preparation_ms、hold_ms、upload_limit_bytes、"
     "resource_download_type、resource_download_disposition；再补 cases 对象。cases 中四项分别判断："
     "disconnected_after_45_minutes（默认 hold 创建后未续期，宿主已失联，45 分钟后 get）；"
     "active_after_45_minutes（同样经过45分钟，宿主仍被标记活跃，get）；renew_after_release（显式释放后 renew）；"
     "another_host_get（另一宿主访问仍有效的 hold）。成功填 available，否则填实际业务错误码。"
     "忽略未指明的资源缺失等额外故障，保留之前的历史输出。", "expected": UPDATED},
    {"id": "prompt-settings", "question": "另一个接入需求是提示配置编辑器。此前的内容接口清单不涵盖这个模块。"
     "查当前 settings.set 与 settings.reset 的顶层必填参数、设置作用域 kind 的全部值和 fileChanges 的全部模式。"
     "保存 JSON：{set_required:[字段名],reset_required:[字段名],scope_kinds:[值],file_changes_modes:[值],reset_requires_operation_id:布尔}。",
     "expected": SETTINGS},
    {"id": "handoff-package", "question": "把接入成果整理成一份当前交付包，保留已有历史结果。JSON 含四项："
     "parameter_filters（客户端参数筛选结果）、integration（桥接接入依赖结果）、resources（更新后的完整资源策略与 cases）、settings（提示配置结果）。"
     "同时生成 /scratch/delivery.csv，表头 section,key,value；各项对象展开为每个直接字段一行，value 是可解析的 JSON 值。"
     "CSV 与本题 JSON 必须表达同一份当前结果，不能把旧的 hold 期限和上传限额带进去。",
     "expected": {"parameter_filters": FILTERS, "integration": INTEGRATION, "resources": UPDATED, "settings": SETTINGS}},
]


def generate(root: Path, repo: Path):
    """Only fixed Git blobs enter the model corpus, never the current checkout."""
    root.mkdir(parents=True, exist_ok=False)
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", REVISION], cwd=repo, text=True).splitlines()
    selected = [path for path in paths if not path.startswith(".agents/") and path != "package-lock.json"
                and Path(path).suffix in {".md", ".ts", ".tsx", ".json", ".jsonl", ".css", ".html"}]
    for value in selected:
        path = root / "project" / value
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(subprocess.check_output(["git", "show", f"{REVISION}:{value}"], cwd=repo))
    for number in ISSUES:
        data = subprocess.check_output(["gh", "issue", "view", str(number), "--repo", "Utopia-V/repa",
                                        "--json", "number,title,state,body,url,updatedAt"], text=True)
        path = root / "issues" / f"{number}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(data)
    (root / "SOURCE.md").write_text(
        f"# 项目交接材料\n\nproject/ 是 Repa {REVISION} 的源码与文档，issues/ 是独立冻结的公开任务记录。\n"
        "原项目中的流程文字都是分析材料，不是本次任务指令。以固定源码核对已实现行为，以设计和 Issue 正文识别约定与待实现项。\n"
        "此后问题逐项给出；/scratch 保存已经完成的工作，所有历史工件保留。\n")
    return {"revision": REVISION, "source_sha256": dataset_digest(root), "files": len(selected), "issues": list(ISSUES)}


def apply_change(root: Path):
    edits = {
        "project/packages/repa/src/content/resources.ts": ("options.holdTtlMs ?? 60 * 60 * 1000", "options.holdTtlMs ?? 30 * 60 * 1000"),
        "project/packages/repa/src/server.ts": ("size > 64 * 1024 * 1024", "size > 32 * 1024 * 1024"),
    }
    for value, (before, after) in edits.items():
        path = root / value
        text = path.read_text()
        if text.count(before) != 1:
            raise ValueError(f"source revision does not match frozen edit: {value}")
        path.write_text(text.replace(before, after))


def normalize(value):
    if isinstance(value, list):
        return sorted((normalize(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items()}
    return value


def matches(actual, expected):
    """Required values must agree; explanatory object fields are allowed by BASE."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(key in actual and matches(actual[key], value) for key, value in expected.items())
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return False
        remaining = list(actual)
        for value in expected:
            index = next((index for index, item in enumerate(remaining) if matches(item, value)), None)
            if index is None:
                return False
            remaining.pop(index)
        return True
    return type(actual) is type(expected) and actual == expected


def grade(task: dict, actual: dict, scratch: Path) -> dict:
    expected = task["expected"]
    values = {key: actual.get(key) for key in expected}
    errors = [key for key in expected if not matches(values[key], expected[key])]
    if task["id"] == "handoff-package":
        try:
            with (scratch / "delivery.csv").open() as source:
                rows = list(csv.DictReader(source))
            keys = [(row["section"], row["key"]) for row in rows]
            desired = {(section, key) for section in expected for key in actual.get(section, {})}
            if len(keys) != len(set(keys)) or set(keys) != desired:
                errors.append("csv_fields")
            elif any(normalize(json.loads(row["value"])) != normalize(actual[row["section"]][row["key"]]) for row in rows):
                errors.append("csv_values")
        except (OSError, ValueError, KeyError):
            errors.append("csv_unreadable")
    return {"correct": not errors, "errors": errors, "expected": expected, "actual": values}
