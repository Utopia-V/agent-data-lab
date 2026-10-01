# 可复用的已有系统

记录日期：2026-10-01。以下项目分别解决访问、转换或执行的某一部分；本课题按实际任务选择接入，不把它们拼成强制依赖栈。

| 系统 | 已有能力 | 本课题的使用判断 |
| --- | --- | --- |
| DuckDB | 直接读取 CSV、JSON、Parquet，SQL 连接和视图 | 已用于来源结构提取与原生查询。业务含义来自数据说明，不能从列类型推断 |
| LOTUS | Pandas 与语义操作组合；LazyFrame 保存执行结构、延迟执行、原生过滤前推 | 批量语义处理需要这类能力时优先复用，不另造通用算子语言 |
| DocETL | 文档到结构化记录的处理流程；MOAR 在评分函数指导下搜索流程改写 | 适合需要反复语义抽取的集合。当前费率任务的手册规则能先转为普通程序，无需逐行调用模型 |
| Palimpzest | 声明式语义转换与查询计划优化 | 同属可复用的语义处理执行层；是否引入由具体任务决定 |

[DuckDB 多文件访问](https://duckdb.org/docs/current/data/multiple_files/overview)和 [JSON 读取](https://duckdb.org/docs/current/data/json/loading_json)保留原生来源。[LOTUS LazyFrame](https://lotus-ai.readthedocs.io/en/latest/lazyframe_api.html)支持保存流程，但含自定义 Python callable 的序列化受 Python 环境影响。[DocETL 优化说明](https://ucbepic.github.io/docetl/optimization/overview/)区分离线流程搜索与执行时模型级联。[Palimpzest 说明](https://palimpzest.org/docs/intro)展示自然语言过滤、字段抽取和原生关系操作的组合。

这些执行能力不能替代对当前任务范围与来源含义的解释。本实验继续检查解释生成的程序、直接读取的数据和交付结果之间的关系：新数据能直接重算，改变计算含义的说明可能要求改程序。两种变化不能都按“重跑旧程序”处理。

数据描述也有成熟格式可借鉴。[Frictionless Data Package](https://specs.frictionlessdata.io/data-package/)通过独立 descriptor 描述资源、位置、schema 与来源，保留数据的原有形式。[W3C CSVW](https://www.w3.org/TR/tabular-metadata/)提供表、列、关系、自然语言说明和数据类型等元数据。[RO-Crate](https://www.researchobject.org/ro-crate/)组织研究数据与相关资源的描述。它们说明“给原生内容附可解释的描述”已有基础，不需要先统一正文存储。本项目尚未声明实现这些标准的完整兼容性。
