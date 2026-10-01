"""Build paired workspaces, execute tasks, and retain versioned run records."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
from pathlib import Path
import random
import shutil
import subprocess
import time

from .fixtures import generate, dataset_digest, write_json, DESCRIPTION, API_HELP, HELPER_HELP
from .runner import CodexRunner
from .sandbox import Sandbox
from .repa_corpus import generate_repa, REVISION as REPA_REVISION, DESCRIPTION as REPA_DESCRIPTION


def grade(final: str, task):
    try:
        value = json.loads(final)
        answers, unresolved = value["answers"], value["unresolved"]
        if not all(isinstance(items, list) and all(isinstance(x, str) for x in items) for items in (answers, unresolved)):
            raise ValueError("invalid output types")
        missing = list((Counter(task.answers) - Counter(answers)).elements())
        extra = list((Counter(answers) - Counter(task.answers)).elements())
        coverage_ok = Counter(unresolved) == Counter(task.unresolved)
        return {"correct": not missing and not extra and coverage_ok,
                "missing": missing, "extra": extra, "coverage_correct": coverage_ok,
                "expected_unresolved": task.unresolved, "actual_unresolved": unresolved}
    except (ValueError, TypeError, KeyError) as error:
        return {"correct": False, "invalid_answer": str(error)}


def campaign(args):
    directory = Path(args.output).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    canonical = directory / "canonical"
    tasks = (generate_repa(canonical, Path(args.repa_repository)) if args.dataset == "repa"
             else generate(canonical, args.seed, args.count, variant=args.variant))
    if args.tasks:
        wanted = set(args.tasks.split(","))
        if not wanted <= {task.id for task in tasks}:
            raise ValueError("unknown task id")
        tasks = [task for task in tasks if task.id in wanted]
    conditions = args.conditions.split(",")
    if not set(conditions) <= {"files", "described", "helpers", "interface"}:
        raise ValueError("unknown condition")
    manifest = {"version": args.version, "dataset": args.dataset, "variant": args.variant,
        "seed": args.seed, "count": args.count, "model": args.model,
        "effort": args.effort, "conditions": conditions, "replicates": args.replicates,
        "tasks": [asdict(task) for task in tasks], "corpus_sha256": dataset_digest(canonical),
        "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "git_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()),
        "codex_version": subprocess.check_output(["codex", "--version"], text=True).strip()}
    if args.dataset == "repa":
        manifest["source"] = {"repository": "https://github.com/Utopia-V/repa", "revision": REPA_REVISION}
    # Freeze hashes before the first model call, even during exploratory runs.
    source_root = Path(__file__).parent
    snapshot = directory / "implementation"
    shutil.copytree(source_root, snapshot, ignore=shutil.ignore_patterns("__pycache__"))
    manifest["implementation_sha256"] = dataset_digest(snapshot)
    write_json(directory / "manifest.json", manifest)
    jobs = [(condition, task, replicate) for replicate in range(args.replicates)
            for task in tasks for condition in conditions]
    random.Random(args.seed + 10000).shuffle(jobs)
    write_json(directory / "order.json", [{"condition": c, "task": t.id, "replicate": r} for c,t,r in jobs])

    def execute(job):
        condition, task, replicate = job
        name = f"{condition}-{task.id}-{replicate}"
        work = directory / "workspaces" / name
        shutil.copytree(canonical, work)
        if condition != "files":
            (work / "DATA.md").write_text(REPA_DESCRIPTION if args.dataset == "repa" else DESCRIPTION)
        if condition == "interface":
            (work / "API.md").write_text(API_HELP)
        elif condition == "helpers":
            (work / "HELPERS.md").write_text(HELPER_HELP)
        host = directory / "hosts" / name
        host.mkdir(parents=True)
        prompt = "工作目录 /work 包含学习空间的数据。README.md 提供格式入口。"
        if condition != "files":
            prompt += "DATA.md 提供来源与字段说明。"
        if condition == "interface":
            prompt += "API.md 提供可组合的 Python 访问接口；原生文件与编程仍可使用。"
        elif condition == "helpers":
            prompt += "HELPERS.md 提供可复用的来源解析函数；原生文件与编程仍可使用。"
        prompt += "\n任务：" + task.prompt + "\n只提交符合 schema 的 JSON 结果。"
        start = time.monotonic()
        try:
            with CodexRunner(host, args.model, args.effort, args.timeout) as runner:
                result = runner.run(prompt, Sandbox(work, directory / "scratch" / name,
                    interface=condition == "interface", helpers=condition == "helpers",
                    provider=snapshot / "access.py"))
            result["grade"] = grade(result["final"], task)
            result["protocol_valid"] = not result.get("unexpected_tools")
        except Exception as error:
            result = {"status": "harness_error", "error": type(error).__name__ + ": " + str(error),
                      "wall_seconds": round(time.monotonic() - start, 3)}
        result.update(condition=condition, task=task.id, replicate=replicate, prompt=prompt)
        write_json(directory / f"{name}.json", result)
        print(json.dumps({"run": name, "status": result["status"], "correct": result.get("grade",{}).get("correct"),
                          "tools": result.get("tool_calls"), "model_completions": result.get("model_completions"),
                          "seconds": result["wall_seconds"]}), flush=True)
        return result

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(execute, jobs))
    write_json(directory / "summary.json", [{k:v for k,v in row.items() if k not in {"trace","messages","prompt","final"}} for row in results])


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("campaign")
    run.add_argument("--output", required=True)
    run.add_argument("--seed", type=int, default=71)
    run.add_argument("--version", default="v2")
    run.add_argument("--dataset", choices=["synthetic", "repa"], default="synthetic")
    run.add_argument("--repa-repository", default="../repa")
    run.add_argument("--variant", choices=["stable", "native"], default="native")
    run.add_argument("--count", type=int, default=120)
    run.add_argument("--model", default="gpt-6-astra")
    run.add_argument("--effort", default="high")
    run.add_argument("--conditions", default="files,described,interface")
    run.add_argument("--tasks")
    run.add_argument("--replicates", type=int, default=1)
    run.add_argument("--workers", type=int, default=3)
    run.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    if args.command == "campaign":
        campaign(args)


if __name__ == "__main__":
    main()
