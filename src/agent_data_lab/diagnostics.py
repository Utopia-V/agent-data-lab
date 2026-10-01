"""Replay observed result-transfer failures without another model call."""

import ast
import json
from pathlib import Path

from .cli import grade
from .fixtures import Task, write_json


def replay(root: Path, destination: Path):
    cases=[]
    specifications=[("v3-luna-seed2027","helpers-references-0",4,"references"),
                    ("v3-luna-seed2027","interface-join-0",4,"join"),
                    ("v3-luna-seed4099","helpers-references-0",3,"tuple_references")]
    for campaign,name,step_index,kind in specifications:
        directory=root/campaign
        manifest=json.loads((directory/"manifest.json").read_text())
        tasks={row["id"]:Task(**row) for row in manifest["tasks"]}
        run=json.loads((directory/(name+".json")).read_text())
        output=run["trace"][step_index]["result"]
        if output.get("truncated") or output.get("exit_code"):
            raise ValueError("selected observation is incomplete")
        answers=[]
        # Transform only the program's observed output. The task oracle is used
        # afterwards by grade(), never to select or repair individual entries.
        for line in output["output"].splitlines():
            if kind=="tuple_references":
                if line.startswith("MATCH "):
                    ref,start,ordinal,*_=ast.literal_eval(line.removeprefix("MATCH "))
                    answers.append(f"{ref}@{start}:{ordinal}")
                continue
            ref,value=line.split(" ",1)
            if kind=="references":
                location=ast.literal_eval(value)
                answers.append(f"{ref}@{location['line']}:{location['ordinal']}")
            else:
                answers.append(ref+"="+value)
        direct={"answers":answers,"unresolved":[]}
        cases.append({"campaign":campaign,"run":name,"observation_step":step_index+1,
            "observed_model_grade":run["grade"],"direct_program_result":direct,
            "direct_program_grade":grade(json.dumps(direct),tasks[run["task"]]),
            "meaning":"已观察程序输出的确定性转交重放；不是新的模型运行，也不修复原模型最终答案"})
    write_json(destination,cases)


if __name__=="__main__":
    replay(Path("campaigns"),Path("results/2026-10-01/result-transfer-replay.json"))
