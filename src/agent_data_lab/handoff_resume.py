"""A new consumer resumes the completed handoff with all ordinary artifacts."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import random
import shutil

from .fixtures import dataset_digest, write_json
from .handoff import execute_task
from .runner import CodexRunner
from .sandbox import Sandbox


TASK = {"id": "new-consumer", "question":
    "从已有交付成果接手，完成一个前端资源使用方案。以当前源码的实际默认行为为准。"
    "上传请求的认证、空间和宿主均有效，资源存在；判断24 MiB和48 MiB各一次上传是否在大小限制内。"
    "再判断：一个默认 hold 建立后从未续期，宿主已失联但未显式关闭，40分钟后 get 是否成功。"
    "还要列出提示配置恢复默认值时 settings.reset 的必填顶层字段。"
    "保存 JSON：{upload_24_mib_allowed:布尔,upload_48_mib_allowed:布尔,"
    "inactive_hold_after_40_minutes:成功填available否则填实际错误码,settings_reset_required:[字段名]}。"
    "/scratch 保留此前工作，部分说明记录的是较早的来源修订；原始材料在 /work。",
    "expected": {"upload_24_mib_allowed": True, "upload_48_mib_allowed": False,
                 "inactive_hold_after_40_minutes": "lease_expired", "settings_reset_required": ["scope", "namespace", "key", "base"]}}


def run(args):
    parent, output = Path(args.parent).resolve(), Path(args.output).resolve()
    manifest = json.loads((parent / "manifest.json").read_text())
    # A running or partial source episode cannot silently become the handoff state.
    jobs = []
    for model in manifest["models"]:
        for replicate in range(manifest["replicates"]):
            for condition in manifest["conditions"]:
                source = parent / f"{model}-{replicate}" / condition
                last = json.loads((source / "handoff-package" / "result.json").read_text())
                if last.get("status") != "completed" or not last.get("protocol_valid"):
                    raise ValueError("parent episode is incomplete")
                jobs.append((model, replicate, condition, source))
    random.Random(1835).shuffle(jobs)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(Path(__file__).parent, output / "implementation", ignore=shutil.ignore_patterns("__pycache__"))
    write_json(output / "manifest.json", {"version": "handoff-reentry-v1", "parent": str(parent), "task": TASK,
               "implementation_sha256": dataset_digest(output / "implementation"),
               "jobs": [{"model": model, "replicate": replicate, "condition": condition,
                         "source_sha256": dataset_digest(source / "source"),
                         "starting_work_sha256": dataset_digest(source / "scratch")}
                        for model, replicate, condition, source in jobs]})

    def execute(job):
        model, replicate, condition, source = job
        home = output / f"{model}-{replicate}" / condition
        root, scratch, host = home / "source", home / "scratch", home / "host"
        shutil.copytree(source / "source", root)
        shutil.copytree(source / "scratch", scratch)
        host.mkdir()
        entry = {"files": "此前成果均在 /scratch。", "documented": "工作说明入口：/scratch/work-notes.md。",
                 "structured": "工作记录入口：/scratch/work-index/README.md。"}[condition]
        with CodexRunner(host, model, "high", 900) as runner:
            return execute_task(runner, Sandbox(root, scratch, interface=False), home / TASK["id"], TASK,
                                suffix="\n" + entry + "\n相对上一项工作，本次原始来源没有新的变化。")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(execute, jobs))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=2)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
