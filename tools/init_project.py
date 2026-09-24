"""只补缺失项目文件；不覆盖、不生成、不联网。Python 3.10+。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any


def validate_name(name: str) -> None:
    reserved = name.split('.')[0].upper()
    if (not name or name!=name.strip() or name in {'.','..','_通用短剧工作流'}
        or name.endswith('.') or re.search(r'[\\/<>:"|?*\x00-\x1f]',name)
        or reserved in {'CON','PRN','AUX','NUL'} or re.fullmatch(r'(COM|LPT)[1-9]',reserved)):
        raise ValueError('ProjectName 必须是合法的单层项目名，不能是路径或保留名称。')


def initialize(root: Path, name: str) -> dict[str,Any]:
    validate_name(name)
    root=root.resolve(); common=root/'_通用短剧工作流'; project=root/name
    if common.is_symlink() or project.is_symlink(): raise ValueError('拒绝通过符号链接初始化项目。')
    templates={
        '项目启动说明.md':common/'项目启动说明.template.md',
        '项目参数.json':common/'Codex适配剧梦提示词库（模版）0914/dreamina-short-drama-production/assets/项目参数.template.json',
        'AGENTS.md':common/'AGENTS.project.template.md',
        '制作台账.json':common/'制作台账.template.json',
    }
    # 先确认全部模板，再建立目录；模板缺失时不留下半个项目。
    content={target:src.read_text(encoding='utf-8-sig') for target,src in templates.items()}
    params=json.loads(content['项目参数.json'])
    params.setdefault('project',{}).update({'name':name,'root':str(project),'common_root':str(common)})
    content['项目参数.json']=json.dumps(params,ensure_ascii=False,indent=2)+'\n'
    content['AGENTS.md']=content['AGENTS.md'].replace('{{COMMON_ROOT}}',str(common))
    directories=['人物','场景','道具','音色','成片','视频提示词','提交快照']
    for folder in directories:
        p=project/folder
        if p.exists() and not p.is_dir(): raise ValueError(f'预期目录却存在同名文件：{p}')
    project.mkdir(parents=True,exist_ok=True)
    for folder in directories: (project/folder).mkdir(exist_ok=True)
    created=[]; kept=[]
    for target,text in content.items():
        path=project/target
        if path.is_symlink(): raise ValueError(f'拒绝写入符号链接：{path}')
        try:
            with path.open('x',encoding='utf-8',newline='\n') as out: out.write(text)
            created.append(target)
        except FileExistsError: kept.append(target)
    lock=project/'工作流版本锁.json'
    if not lock.exists():
        entries={}
        root_names={'新聊天启动指令.md','项目启动说明.template.md','视频提示词输出规范_资产全名版.md','创建新短剧项目.ps1','AGENTS.project.template.md','AGENTS.md','工作流规则索引.md','制作台账.template.json'}
        active={common/name for name in root_names if (common/name).is_file()}
        bundle=common/'Codex适配剧梦提示词库（模版）0914'
        active.update(p for p in bundle.rglob('*') if p.is_file() and p.suffix in {'.md','.json'} and not any(x.startswith(('_升级','_备份','.')) for x in p.relative_to(bundle).parts))
        active.update(common/'tools'/name for name in ('workflow_check.py','init_project.py') if (common/'tools'/name).is_file())
        for p in sorted(active):
            entries[str(p.relative_to(common))]=hashlib.sha256(p.read_bytes()).hexdigest()
        try:
            with lock.open('x',encoding='utf-8') as out:
                json.dump({'workflow_version':'3.5','common_root':str(common),'files':entries},out,ensure_ascii=False,indent=2)
            created.append(lock.name)
        except FileExistsError: kept.append(lock.name)
    else: kept.append(lock.name)
    return {'project':str(project),'created':created,'preserved':kept,'platform_actions':False}


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--project-name',required=True)
    args=parser.parse_args()
    try: result=initialize(args.root,args.project_name)
    except (OSError,ValueError) as exc:
        parser.exit(1,f'初始化停止：{exc}\n')
    print(json.dumps(result,ensure_ascii=False,indent=2)); return 0

if __name__=='__main__': raise SystemExit(main())
