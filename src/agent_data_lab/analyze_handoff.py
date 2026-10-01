"""Account for shared creation and description costs in paired handoff episodes."""

import argparse
import json
from pathlib import Path

from .fixtures import write_json
from .handoff_tasks import grade


def measurements(paths):
    result = {"turns": 0, "completed": 0, "graded_turns": 0, "correct": 0, "model_calls": 0,
              "input_tokens": 0, "cached_input_tokens": 0, "uncached_input_tokens": 0,
              "output_tokens": 0, "seconds": 0.0, "missing_usage": 0}
    for path in paths:
        rescored = path.with_name("regraded.json")
        value = json.loads((rescored if rescored.exists() else path).read_text())
        model_path = path.with_name("model.json")
        measured = json.loads(model_path.read_text()) if model_path.exists() else value
        result["turns"] += 1
        result["completed"] += value.get("status") == "completed"
        result["graded_turns"] += "grade" in value
        result["correct"] += bool(value.get("grade", {}).get("correct") and value.get("protocol_valid"))
        result["model_calls"] += measured.get("model_completions") or 0
        result["seconds"] += measured.get("wall_seconds", 0)
        usage = (measured.get("usage") or {}).get("total")
        if usage is None:
            result["missing_usage"] += 1
            continue
        result["input_tokens"] += usage.get("inputTokens", 0)
        result["cached_input_tokens"] += usage.get("cachedInputTokens", 0)
        result["uncached_input_tokens"] += usage.get("inputTokens", 0) - usage.get("cachedInputTokens", 0)
        result["output_tokens"] += usage.get("outputTokens", 0)
    result["seconds"] = round(result["seconds"], 3)
    return result


def analyze(root):
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text())
    tasks_by_id = {task["id"]: task for task in manifest["warm_tasks"] + manifest["tasks"]}
    for path in root.glob("gpt-*/*/*/result.json"):
        task = tasks_by_id.get(path.parent.name)
        if task is None:
            continue
        raw = json.loads(path.read_text())
        if raw.get("status") == "completed" and isinstance(raw.get("artifact"), dict) and (path.parent / "artifacts").is_dir():
            revised = dict(raw, original_grade=raw.get("grade"), grading_version="handoff-v1.1",
                           grade=grade(task, raw["artifact"], path.parent / "artifacts"))
            write_json(path.with_name("regraded.json"), revised)
    summaries, rows = [], []
    for model in manifest["models"]:
        for replicate in range(manifest["replicates"]):
            home = root / f"{model}-{replicate}"
            initial = [home / "initial" / task["id"] / "result.json" for task in manifest["warm_tasks"]]
            description = home / "initial" / "description" / "result.json"
            for condition in manifest["conditions"]:
                stage = home / condition
                following = [stage / task["id"] / "result.json" for task in manifest["tasks"]]
                existing = [path for path in following if path.exists()]
                chargeable = [path for path in initial if path.exists()] + existing
                if condition != "files" and description.exists():
                    chargeable.append(description)
                summary = {"model": model, "replicate": replicate, "condition": condition,
                           "continuation": measurements(existing), "with_creation": measurements(chargeable),
                           "expected_followup_turns": len(following)}
                setup_path = stage / "setup.json"
                render_seconds = json.loads(setup_path.read_text())["render_seconds"] if setup_path.exists() else None
                observation_seconds = sum(json.loads(path.read_text())["seconds"]
                                          for path in stage.glob("*/observation.json"))
                summary["render_seconds"] = render_seconds
                summary["observation_seconds"] = round(observation_seconds, 4)
                summary["whole_continuation_correct"] = summary["continuation"]["correct"] == len(following)
                summaries.append(summary)
                for task, path in zip(manifest["tasks"], following):
                    if not path.exists():
                        continue
                    rescored = path.with_name("regraded.json")
                    value = json.loads((rescored if rescored.exists() else path).read_text())
                    rows.append({"model": model, "replicate": replicate, "condition": condition,
                                 "task": task["id"], "grade": value.get("grade"), "status": value["status"],
                                 "protocol_valid": value.get("protocol_valid"), **measurements([path])})
    result = {"version": manifest["version"], "groups": summaries, "tasks": rows,
              "accounting": "with_creation includes the same initial work for each alternative; documentation creation is charged to documented and structured"}
    write_json(root / "summary.json", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign")
    args = parser.parse_args()
    result = analyze(args.campaign)
    for group in result["groups"]:
        print(json.dumps(group, ensure_ascii=False))


if __name__ == "__main__":
    main()
