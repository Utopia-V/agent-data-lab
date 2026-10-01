"""Export visible experimental evidence and recompute the report's comparisons."""

import argparse
from collections import defaultdict
from hashlib import sha256
import gzip
import io
import json
from pathlib import Path
import statistics
import tarfile


CAMPAIGNS = ["v1-seed71", "v2-seed313", "v2-seed907", "v2-repa", "v3-seed2027", "v3-luna-seed2027", "v3-seed4099", "v3-luna-seed4099"]


def metrics(row):
    usage = (row.get("usage") or {}).get("total", {})
    return {"input_tokens": usage.get("inputTokens"), "cached_tokens": usage.get("cachedInputTokens"),
        "uncached_input_tokens": usage["inputTokens"] - usage["cachedInputTokens"] if usage else None,
        "output_tokens": usage.get("outputTokens"), "tool_calls": row.get("tool_calls"),
        "model_completions": row.get("model_completions"), "wall_seconds": row["wall_seconds"],
        "observed_bytes": sum(len(json.dumps(exchange["result"], ensure_ascii=False).encode()) for exchange in row.get("trace", [])),
        "program_characters": sum(len(exchange["arguments"].get("command", "")) for exchange in row.get("trace", [])),
        "tool_seconds": sum(exchange["result"].get("wall_seconds", 0) for exchange in row.get("trace", [])),
        "truncated_outputs": sum(bool(exchange["result"].get("truncated")) for exchange in row.get("trace", [])),
        "tool_failures": sum(not exchange.get("success") or bool(exchange["result"].get("exit_code", 0)) for exchange in row.get("trace", []))}


def summarize(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["phase"], row["condition"])].append(row)
    summary = []
    for (phase, condition), cases in grouped.items():
        summary.append({"phase": phase, "condition": condition, "runs": len(cases),
            "correct": sum(row["status"] == "completed" and row.get("protocol_valid", True) and row.get("grade", {}).get("correct", False) for row in cases),
            "model_completions": sum(row["metrics"]["model_completions"] for row in cases),
            "tool_calls": sum(row["metrics"]["tool_calls"] for row in cases),
            "median_wall_seconds": round(statistics.median(row["metrics"]["wall_seconds"] for row in cases), 3),
            "mean_model_completions": round(statistics.mean(row["metrics"]["model_completions"] for row in cases), 3),
            **{key: sum(row["metrics"][key] for row in cases) for key in ["input_tokens", "cached_tokens", "uncached_input_tokens", "output_tokens", "observed_bytes", "program_characters", "tool_seconds", "truncated_outputs", "tool_failures"]}})
    pairs = []
    lookup = {(row["campaign"], row["task"], row["replicate"], row["condition"]):row for row in rows}
    for candidate in rows:
        if candidate["condition"] != "interface":
            continue
        for baseline in ["files", "described", "helpers"]:
            other = lookup.get((candidate["campaign"], candidate["task"], candidate["replicate"], baseline))
            if other:
                pairs.append({"phase":candidate["phase"],"campaign":candidate["campaign"],"task":candidate["task"],"baseline":baseline,
                    "model_call_delta":candidate["metrics"]["model_completions"]-other["metrics"]["model_completions"],
                    "wall_delta":round(candidate["wall_seconds"]-other["wall_seconds"],3)})
    return {"groups": summary, "pairs": pairs}


def export(root: Path, destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    rows, provenance = [], []
    for name in CAMPAIGNS:
        campaign = root / name
        manifest = json.loads((campaign / "manifest.json").read_text())
        phase = "v2" if name.startswith("v2-seed") else manifest["version"]
        archive_dir=destination/"implementations"
        archive_dir.mkdir(exist_ok=True)
        archive_name=manifest["implementation_sha256"]+".tar.gz"
        buffer=io.BytesIO()
        with tarfile.open(fileobj=buffer,mode="w",format=tarfile.GNU_FORMAT) as archive:
            for path in sorted((campaign/"implementation").glob("*.py")):
                contents=path.read_bytes()
                info=tarfile.TarInfo("agent_data_lab/"+path.name)
                info.size=len(contents); info.mode=0o644; info.mtime=0
                archive.addfile(info,io.BytesIO(contents))
        archive_bytes=gzip.compress(buffer.getvalue(),mtime=0)
        archive_path=archive_dir/archive_name
        if archive_path.exists():
            archive_bytes=archive_path.read_bytes()
            if gzip.decompress(archive_bytes)!=buffer.getvalue():
                raise ValueError("implementation archive content differs")
        else:
            archive_path.write_bytes(archive_bytes)
        provenance.append({"campaign":name,"manifest":manifest,
            "implementation_archive":"implementations/"+archive_name,
            "archive_sha256":sha256(archive_bytes).hexdigest(),
            "order":json.loads((campaign/"order.json").read_text()),
            "module_hashes":{path.name:sha256(path.read_bytes()).hexdigest() for path in sorted((campaign/"implementation").glob("*.py"))}})
        order=json.loads((campaign/"order.json").read_text())
        for item in order:
            path=campaign/f"{item['condition']}-{item['task']}-{item['replicate']}.json"
            row=json.loads(path.read_text())
            if row.get("unexpected_tools") or row.get("errors"):
                raise ValueError(f"review exceptional run before publication: {path}")
            row.update(campaign=name,phase=phase,metrics=metrics(row))
            if row["status"] != "completed" or any(row["metrics"][key] is None
                    for key in ("model_completions", "tool_calls", "input_tokens", "cached_tokens", "output_tokens")):
                raise ValueError(f"cost evidence incomplete; inspect original run instead of aggregating: {path}")
            rows.append(row)
    (destination / "runs.jsonl").write_text("".join(json.dumps(row,ensure_ascii=False)+"\n" for row in rows))
    (destination / "provenance.json").write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+"\n")
    result=summarize(rows)
    (destination / "summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(result["groups"],ensure_ascii=False,indent=2))


def plot(source: Path):
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    font_path=Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
    font=FontProperties(fname=str(font_path)) if font_path.exists() else FontProperties()
    plt.rcParams.update({"font.family":font.get_name(),"axes.unicode_minus":False,"svg.fonttype":"none","svg.hashsalt":"agent-data-lab"})
    data=json.loads((source/"summary.json").read_text())["groups"]
    labels={"files":"普通文件", "described":"文件＋说明", "helpers":"源端辅助函数", "interface":"统一接口"}
    colors={"files":"#8492a6","described":"#5b83ae","helpers":"#af8544","interface":"#137e76"}
    phases=[("v1","初轮 · 每组 8 次"),("v2","原生链接 · 每组 12 次"),("v2-repa","Repa 原文 · 每组 3 次"),("v3","对齐助手与输入 · 每组 8 次")]
    fig, axes=plt.subplots(2,4,figsize=(14.6,7.5),layout="constrained")
    for column,(phase,title) in enumerate(phases):
        rows=[row for row in data if row["phase"]==phase]
        rows.sort(key=lambda row:list(labels).index(row["condition"]))
        for row_index,metric,ylabel in [(0,"mean_model_completions","每任务平均模型调用次数"),(1,"median_wall_seconds","每任务耗时中位数（秒）")]:
            axis=axes[row_index,column]
            for i,row in enumerate(rows):
                value=row[metric]
                axis.bar(i,value,color=colors[row["condition"]],width=.62)
                axis.text(i,value+.05 if row_index==0 else value+.45,f"{value:.2f}" if row_index==0 else f"{value:.1f}",ha="center",fontsize=10)
            axis.set_xticks(range(len(rows)),[labels[row["condition"]] for row in rows],rotation=24,ha="right",fontsize=9)
            axis.set_ylim(0,6 if row_index==0 else 48)
            axis.spines[["top","right"]].set_visible(False)
            axis.grid(axis="y",alpha=.18)
            axis.set_axisbelow(True)
            if column==0: axis.set_ylabel(ylabel)
            if row_index==0: axis.set_title(title,fontsize=12,pad=14)
    fig.suptitle("数据访问方式对模型往返与耗时的影响",fontsize=19)
    fig.supxlabel("各阶段任务不同，分别比较；所有组的最终答案均正确。GPT-6 Astra · high",fontsize=11)
    fig.savefig(source/"comparison.png",dpi=180)
    fig.savefig(source/"comparison.svg",metadata={"Date":None})
    plt.close(fig)

    fig,axes=plt.subplots(2,4,figsize=(16,7.5),layout="constrained")
    for row_index,(phase,model) in enumerate([("v3","GPT-6 Astra"),("v3-luna","GPT-6 Luna")]):
        rows=[row for row in data if row["phase"]==phase]
        rows.sort(key=lambda row:list(labels).index(row["condition"]))
        for col,(metric,title,scale) in enumerate([
            ("correct","答案正确数",1),
            ("model_completions","模型调用总数",1),
            ("uncached_input_tokens","未命中缓存的输入 token（千）",1000),
            ("output_tokens","输出 token（千）",1000)]):
            axis=axes[row_index,col]
            for i,row in enumerate(rows):
                value=row[metric]/scale
                axis.bar(i,value,color=colors[row["condition"]],width=.6)
                label=(str(int(value))+"/"+str(row["runs"])) if metric=="correct" else (f"{value:.1f}" if scale>1 else str(int(value)))
                axis.text(i,value*1.015,label,ha="center",fontsize=11)
            axis.set_xticks(range(len(rows)),[labels[row["condition"]] for row in rows],fontsize=10)
            axis.set_title(f"{model} · {title}",fontsize=12)
            axis.set_ylim(0,max(row[metric]/scale for row in data if row["phase"] in {"v3","v3-luna"})*1.22)
            axis.spines[["top","right"]].set_visible(False)
            axis.grid(axis="y",alpha=.18); axis.set_axisbelow(True)
    fig.suptitle("相同任务与接口版本下的模型及 token 对照",fontsize=18)
    fig.supxlabel("每组 8 次：相同四类任务、两个语料 seed · high · 缓存输入另列",fontsize=11)
    fig.savefig(source/"model-tokens.png",dpi=180)
    fig.savefig(source/"model-tokens.svg",metadata={"Date":None})
    plt.close(fig)
    for path in source.glob("*.svg"):
        path.write_text("\n".join(line.rstrip() for line in path.read_text().splitlines())+"\n")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--campaign-root",type=Path,default=Path("campaigns"))
    parser.add_argument("--output",type=Path,default=Path("results/2026-10-01"))
    parser.add_argument("--plot",action="store_true")
    args=parser.parse_args()
    export(args.campaign_root,args.output)
    if args.plot: plot(args.output)


if __name__=="__main__":
    main()
