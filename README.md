# Agent 数据访问实验

本项目研究面向 Agent 的数据组织与访问：如何让它从异构材料发现相关信息，形成适合当前任务的工作表示，组合和使用这些表示，并在任务或来源变化后继续工作。

目标是形成有端到端证据支持的组织与访问方案，确定哪些约定值得共享、哪些由来源和业务能力持有。普通文件、脚本、原生数据库和成熟工具是对照与可复用基础。

这是独立实验项目。候选接口不属于 Repa 已接受的产品协议。

第一阶段完成 117 次正式模型运行。Astra 下统一接口减少了部分往返与 token；Luna 下也减少了往返，但正确率没有超过普通文件加说明。较小模型暴露了程序结果正确、最终转录出错的问题。[研究报告](results/2026-10-01/report.md)保留具体错误、token 分项、源码版本与逐次证据。

后续[资料发现与连续工作研究](results/2026-10-01-observations/report.md)采用保留完整工件的协议，完成 192 次任务请求，另保留 116 次诊断记录。它包括定义与数据变化、新会话、原生压缩、文件分片、中文材料，以及从分析程序到 CSV 和交互报告的连续工作。普通文件完成了复合分析的全部任务；自动观察的收益随模型与工作过程变化。

- [当前设计与研究范围](docs/design.md)
- [实验协议](docs/experiment.md)
- [原始来源与工作接续实验](docs/raw-source-experiments.md)
- [已有系统与复用范围](docs/related-systems.md)
- [实验结果](results/README.md)

实验材料包括可重建的合成语料、固定版本的 Repa 文档与公开 DABstep 数据；模型实验的原始记录默认保存在 Git 忽略目录中。

当前方案保留原生来源与程序操作，把含义和范围关联到对应数据，按需要提供原文与变化观察，直接交付程序结果。设计责任与 Repa 接入边界见[设计说明](docs/design.md)；[交互报告示例](results/2026-10-01-observations/example-report/README.md)可独立打开。

## 运行

当前实验宿主为 Linux，使用 Python 3.12、uv、bubblewrap、Codex CLI 的已登录 ChatGPT 账户。
模型程序运行在只含语料、解释器和实验接口的隔离文件系统内；生成器、标准答案和宿主配置不在其中。

来源观察与数据访问模块独立于模型运行时；Codex 是本项目模型实验的运行工具，不是 Repa 的安装依赖。

```bash
uv sync --locked --group environment
uv run --group environment python -m unittest discover -s tests -q
uv run data-lab campaign --output campaigns/example --seed 71 --model gpt-6-astra --effort high
```

`campaign` 会实际调用模型。每个输出目录只创建一次；manifest 保存语料与实现哈希、模型、思考强度、任务、运行顺序和源码快照。原始结果包含可见工具交互、最终回答和使用量，不保留模型隐藏推理。

图表由 `analysis` 依赖组中的 Matplotlib 生成，当前使用已安装的 Noto Sans CJK 中文字体。公开结果包含冻结实现归档，可按报告中的哈希恢复各阶段；本机 campaigns/ 另外保留原始语料、源码快照和模型原始记录。各次运行复制出的工作区在核验后删除，需要时由这些输入重建。

关联研究入口：[Repa #30](https://github.com/Utopia-V/repa/issues/30)。
