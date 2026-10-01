# Agent 数据访问实验

本项目研究 Agent 在文件、结构化记录与派生索引之间取得数据的方式。实验比较普通文件工具、附带数据说明的文件工具，以及增加统一寻址、范围查询和引用查询的访问方式。

问题是：在允许模型自行编程、筛选和组合结果的前提下，哪些额外约定仍能改善任务结果、减少模型往返或降低错误恢复成本？

这是独立实验项目。候选接口不属于 Repa 已接受的产品协议。

已完成 117 次正式模型运行。Astra 下统一接口减少了部分往返与 token；Luna 下也减少了往返，但正确率没有超过普通文件加说明。较小模型暴露了程序结果正确、最终转录出错的问题。[研究报告](results/2026-10-01/report.md)保留具体错误、token 分项、源码版本与逐次证据。

- [实验后收敛的设计](docs/design.md)
- [实验协议](docs/experiment.md)
- [实验结果](results/README.md)

实验材料使用可重建的合成语料；模型实验的原始记录默认保存在 Git 忽略目录中。

## 运行

当前实验宿主为 Linux，使用 Python 3.12、uv、bubblewrap、Codex CLI 的已登录 ChatGPT 账户。
模型程序运行在只含语料、解释器和实验接口的隔离文件系统内；生成器、标准答案和宿主配置不在其中。

```bash
uv sync --locked
uv run python -m unittest discover -s tests -v
uv run data-lab campaign --output campaigns/example --seed 71 --model gpt-6-astra --effort high
```

`campaign` 会实际调用模型。每个输出目录只创建一次；manifest 保存语料与实现哈希、模型、思考强度、任务、运行顺序和源码快照。原始结果包含可见工具交互、最终回答和使用量，不保留模型隐藏推理。

图表由 `analysis` 依赖组中的 Matplotlib 生成，当前使用已安装的 Noto Sans CJK 中文字体。公开结果包含冻结实现归档，可按报告中的哈希恢复各阶段；本机 campaigns/ 另外保留原始语料、源码快照和模型原始记录。各次运行复制出的工作区在核验后删除，需要时由这些输入重建。

关联研究入口：[Repa #30](https://github.com/Utopia-V/repa/issues/30)。
