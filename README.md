# Agent 数据访问实验

本项目研究 Agent 在文件、结构化记录与派生索引之间取得数据的方式。实验比较普通文件工具、附带数据说明的文件工具，以及增加统一寻址、范围查询和引用查询的访问方式。

问题是：在允许模型自行编程、筛选和组合结果的前提下，哪些额外约定仍能改善任务结果、减少模型往返或降低错误恢复成本？

这是独立实验项目。候选接口不属于 Repa 已接受的产品协议。

- [当前设计与待裁决选择](docs/design.md)
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

关联研究入口：[Repa #30](https://github.com/Utopia-V/repa/issues/30)。
