"""Source-grounded Chinese design questions over a fixed public Repa revision."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from .fixtures import write_json
from .repa_corpus import generate_repa,REVISION


TASKS=[
    {'task_id':'context-lifecycle','answer':'A, C, D, F','claims':[
        ('A','官方学习能力拥有学习语境的选择、组成与展开规则。'),
        ('B','同一运行中每次 steer 都会重新组装并注入最新学习语境。'),
        ('C','排队请求实际开始处理时取得当前学习语境，而非受理排队时固定。'),
        ('D','关闭自动注入仍保留文档、绑定查询和独立预览。'),
        ('E','语境读取失败时可静默使用旧视图或空视图继续。'),
        ('F','token 计量、压缩触发和有限溢出恢复复用 Pi 已有机制。'),
    ]},
    {'task_id':'content-identity','answer':'A, E, H','claims':[
        ('A','独立复制内容时建立新身份，旧引用继续指向原内容。'),
        ('B','删除内容后，在原路径创建新文件会自动恢复原身份引用。'),
        ('C','每个稳定内容引用都会自动保存被引用材料的完整历史正文。'),
        ('D','重建材料提取缓存时会覆盖围绕原件持续编辑的校订稿。'),
        ('E','外部移动后不能确认身份和位置关系时，需要重新关联或归属判断。'),
        ('F','空间首次读取任何文件时都必须分配独立内容身份。'),
        ('G','应用关闭期间的全部外部中间编辑都保证可从操作历史恢复。'),
        ('H','代码与交互产物也属于可持续维护的文档，而非只支持 Markdown。'),
    ]},
    {'task_id':'frontend-runtime','answer':'A, E, F, G','claims':[
        ('A','独立前端通过公开应用接口使用后端，Pi SDK 对象留在内部适配层。'),
        ('B','前端组件角色是 MacOS、Windows、Linux、Web 等平台分类。'),
        ('C','公开组件契约要求安装新组件后立即热加载其代码。'),
        ('D','关闭最后一个窗口等价于完整退出，会立即取消全部已启动任务。'),
        ('E','完整退出取消当前工作，保留未执行项，重开后由明确操作继续。'),
        ('F','运行中普通发送作为关联当前运行的 steer，不自动转交其他运行。'),
        ('G','Full Access 放宽执行范围时仍保留内容来源、操作记录和生命周期语义。'),
    ]},
]


def prepare(output,repo):
    output.mkdir(parents=True,exist_ok=False)
    generate_repa(output/'context',repo)
    (output/'context/inventory.json').unlink()
    tasks=[]
    for source in TASKS:
        question=('仅依据 /work 中的固定 Repa 文档，选出下列受到文档支持的设计陈述。'
            '判断约定的设计，不把尚未实现理解为没有该约定。\n'
            +'\n'.join(f'{key}. {statement}' for key,statement in source['claims'])
            +'\n在 answer 中按字母顺序返回被支持的陈述编号。结果文件额外保存 evidence 数组，每项包含 claim、path、quote；'
            '每个选中编号都附来源相对路径和至少十个字符的连续原文摘录。摘录使用原文，不改写。')
        tasks.append({'task_id':source['task_id'],'answer':source['answer'],'question':question,
            'guidelines':'Answer must be a comma separated list of claim IDs, for example A, C.'})
    (output/'dev.jsonl').write_text(''.join(json.dumps(task,ensure_ascii=False)+'\n' for task in tasks))
    files=[{'path':str(path.relative_to(output)),'bytes':path.stat().st_size,
            'sha256':sha256(path.read_bytes()).hexdigest()} for path in sorted(output.rglob('*')) if path.is_file()]
    write_json(output/'manifest.json',{'kind':'repa-understanding','repository':'Utopia-V/repa',
        'revision':REVISION,'files':files,'oracle':'manually checked against CONTEXT.md and ADR 0002/0003/0004'})


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path('datasets/repa-understanding'))
    parser.add_argument('--repo',type=Path,default=Path('/home/uranox/projects/repa'))
    args=parser.parse_args();prepare(args.output,args.repo)


if __name__=='__main__':main()
