"""离线升级：默认预览；--apply --plan 预览计划.json 才写入。无联网或平台操作。"""
from __future__ import annotations
import argparse
from dataclasses import dataclass
from datetime import datetime
import difflib
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

HERE=Path(__file__).resolve().parent
BUNDLE='Codex适配剧梦提示词库（模版）0914'
PARAM_REL=f'{BUNDLE}/dreamina-short-drama-production/assets/项目参数.template.json'

@dataclass(frozen=True)
class Change:
    path: Path
    before: bytes | None
    after: bytes

def sha(data: bytes | None) -> str | None:
    return None if data is None else hashlib.sha256(data).hexdigest()

def normalize(data: bytes) -> str:
    return data.decode('utf-8-sig').replace('\r\n','\n')

def safe_path(base: Path, relative: str) -> Path:
    rel=Path(relative)
    if rel.is_absolute() or '..' in rel.parts: raise ValueError(f'不安全的目标路径：{relative}')
    p=base/rel
    if not p.resolve().is_relative_to(base.resolve()): raise ValueError(f'目标越出项目目录：{p}')
    for parent in (p,*p.parents):
        if parent==base.parent: break
        if parent.is_symlink() or (hasattr(parent,'is_junction') and parent.is_junction()):
            raise ValueError(f'拒绝通过链接写文件：{parent}')
    return p

def transform(text: str, patch: dict[str,str]) -> str:
    if patch['op']=='replace':
        old=patch['old']; new=patch['new']
        count=text.count(old)
        if count!=1: raise ValueError(f"{patch['path']}：旧条款应唯一，实际{count}处：{old[:100]}")
        return text.replace(old,new,1)
    if patch['op']=='section':
        begin=patch['begin']; end=patch['end']
        if text.count(begin)!=1 or text.count(end)!=1:
            raise ValueError(f"{patch['path']}：章节锚点变化，停止自动改写。")
        a=text.index(begin); b=text.index(end,a+len(begin))
        return text[:a]+patch['new']+text[b:]
    raise ValueError('未知补丁类型')

def collect_changes(root: Path, project_name: str) -> list[Change]:
    from init_project import validate_name
    validate_name(project_name)
    root=root.resolve(); common=root/'_通用短剧工作流'; project=root/project_name
    if not common.is_dir() or not project.is_dir(): raise FileNotFoundError('两个现有目录均须存在；不猜测另一份工作流。')
    marker=common/'WORKFLOW_RELEASE.json'
    if marker.exists():
        data=json.loads(marker.read_text(encoding='utf-8-sig'))
        if data.get('version')=='3.5':
            bad=[p for p,h in data.get('installed_hashes',{}).items() if not Path(p).is_file() or sha(Path(p).read_bytes())!=h]
            if bad: raise ValueError('已经升级，但这些文件后来发生变化；请先复核，不覆盖：'+str(bad))
            if data.get('project')!=str(project): raise ValueError('通用工作流已升级；其他项目请用初始化器及独立配置迁移，不重复套本剧补丁。')
            return []
        raise ValueError('发现未知版本记录，停止覆盖。')
    originals: dict[Path,bytes | None]={}; stage: dict[Path,str]={}
    def load(p: Path) -> str:
        if p not in originals:
            originals[p]=p.read_bytes() if p.exists() else None
            stage[p]=normalize(originals[p]) if originals[p] is not None else ''
        return stage[p]
    patches=json.loads((HERE/'patches.json').read_text(encoding='utf-8'))
    for patch in patches:
        relative=patch['path']; base=project if relative.startswith('@project/') else common
        relative=relative.removeprefix('@project/')
        p=safe_path(base,relative)
        if not p.is_file(): raise FileNotFoundError(f'缺少已读取版本的文件：{p}')
        stage[p]=transform(load(p),patch)
    replace_files={
        '新聊天启动指令.md':'新聊天启动指令.md',
        '项目启动说明.template.md':'项目启动说明.template.md',
        '视频提示词输出规范_资产全名版.md':'视频提示词输出规范_资产全名版.md',
        '创建新短剧项目.ps1':'创建新短剧项目.ps1',
        PARAM_REL:'项目参数.template.json',
    }
    required_titles={
        '新聊天启动指令.md':'# 新短剧项目',
        '项目启动说明.template.md':'# 新短剧项目启动说明',
        '视频提示词输出规范_资产全名版.md':'# 视频提示词输出规范',
        '创建新短剧项目.ps1':'param(',
    }
    for relative,source in replace_files.items():
        p=safe_path(common,relative)
        if not p.is_file(): raise FileNotFoundError(p)
        old=load(p)
        if relative in required_titles and not old.lstrip().startswith(required_titles[relative]):
            raise ValueError(f'文件身份/版本不同，停止整体替换：{p}')
        if relative==PARAM_REL:
            if json.loads(old).get('schema')!='JM0914-v3.4-skill-layout': raise ValueError('项目参数模板版本不同，须人工复核。')
        stage[p]=(HERE/'payload'/source).read_text(encoding='utf-8-sig')
    def create_only(p: Path,text: str) -> None:
        if p.exists(): raise FileExistsError(f'新文件位置已有内容，不覆盖：{p}')
        load(p); stage[p]=text
    for name in ['AGENTS.project.template.md','工作流规则索引.md','制作台账.template.json']:
        create_only(safe_path(common,name),(HERE/'payload'/name).read_text(encoding='utf-8-sig'))
    for name in ['workflow_check.py','init_project.py']:
        create_only(safe_path(common,'tools/'+name),(HERE/name).read_text(encoding='utf-8'))
    agents=(HERE/'payload/AGENTS.project.template.md').read_text(encoding='utf-8').replace('{{COMMON_ROOT}}',str(common))
    create_only(safe_path(project,'AGENTS.md'),agents)
    create_only(safe_path(common,'AGENTS.md'),'# 通用短剧工作流维护入口\n\n先读《工作流规则索引.md》。本目录集中维护六个Skill；各项目事实不可写入公共模板。更改先备份并做离线检查；不改线上项目，不花积分。历史备份不是当前执行规则。\n')
    params=json.loads((HERE/'payload/项目参数.template.json').read_text(encoding='utf-8'))
    params['project'].update(name=project_name,root=str(project),common_root=str(common))
    params['script'].update(fact_source='【西语本地化】864229 I Died Before He Believed Me【被炼化后男友悔疯了（雨）】全.md',main_language='es')
    if project_name!='被炼化后的男友悔疯了': raise ValueError('本次项目配置迁移只用于已审阅的《被炼化后的男友悔疯了》。')
    params['decisions']=[{'id':'USER-20260924-v35','source':'用户于本次聊天明确裁决','scope':'后续新生成/重编任务，不追溯重写历史证据','status':'active','replaces':['独立声音引用模块','屏幕文字后期默认','固定单集时长默认','可超过5秒的连续镜头默认','旁白默认朗读'],'requirements':['内容由编译器7.3/适配负责，排版由资产全名版24负责','人物附带音频保留，正常对白完整保留','旁白只转对应画面','所有成片语言仅西语，必要屏幕文字直接生成','时长按用户或已确认SRT，连续镜头≤5秒']}]
    create_only(safe_path(project,'项目参数.json'),json.dumps(params,ensure_ascii=False,indent=2)+'\n')
    ledger=json.loads((HERE/'payload/制作台账.template.json').read_text(encoding='utf-8'))
    ledger.update(project=project_name,user_reported_status='用户表示本剧制作已完成；本轮为Skill优化',legacy_sources=['EP12-EP19_抽卡执行日志.md','EP12-EP19_Sequence_Canon.md','项目完整复盘_被炼化后的男友悔疯了.md'],next_action='新的制作任务开始前读取当前规则，明确任务范围与时间来源；本轮无生成授权。')
    create_only(safe_path(project,'制作台账.json'),json.dumps(ledger,ensure_ascii=False,indent=2)+'\n')
    result=[]
    for p,text in stage.items():
        before=originals[p]
        if before is not None and b'\r\n' in before: text=text.replace('\n','\r\n')
        encoding='utf-8-sig' if p.suffix=='.ps1' or (before and before.startswith(b'\xef\xbb\xbf')) else 'utf-8'
        after=text.encode(encoding)
        if before!=after: result.append(Change(p,before,after))
    new_bytes={c.path:c.after for c in result}
    active_root_names={'新聊天启动指令.md','项目启动说明.template.md','视频提示词输出规范_资产全名版.md','创建新短剧项目.ps1','AGENTS.project.template.md','AGENTS.md','工作流规则索引.md','制作台账.template.json'}
    active_files={common/name for name in active_root_names if (common/name).is_file()}
    active_files.update(p for p in (common/BUNDLE).rglob('*') if p.is_file() and p.suffix in {'.md','.json'} and not any(x.startswith(('_升级','_备份','.')) for x in p.relative_to(common/BUNDLE).parts))
    active_files.update(common/'tools'/name for name in ('workflow_check.py','init_project.py') if (common/'tools'/name).is_file())
    active_files.update(p for p in new_bytes if p.is_relative_to(common))
    lock={'workflow_version':'3.5','common_root':str(common),'files':{str(p.relative_to(common)):sha(new_bytes[p] if p in new_bytes else p.read_bytes()) for p in sorted(active_files)}}
    lock_path=safe_path(project,'工作流版本锁.json')
    if lock_path.exists(): raise FileExistsError('已有项目版本锁，须比较后迁移，不能覆盖。')
    result.append(Change(lock_path,None,(json.dumps(lock,ensure_ascii=False,indent=2)+'\n').encode('utf-8')))
    marker_data={'version':'3.5','project':str(project),'source':'2026-09-24用户明确裁决','installed_hashes':{str(c.path):sha(c.after) for c in result}}
    result.append(Change(marker,None,(json.dumps(marker_data,ensure_ascii=False,indent=2)+'\n').encode('utf-8')))
    return result

def serial_plan(changes: list[Change]) -> list[dict[str,Any]]:
    return [{'path':str(c.path),'before_sha256':sha(c.before),'after_sha256':sha(c.after),'new_file':c.before is None} for c in changes]

def atomic_write(path: Path,data: bytes) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.'+path.name+'.v35-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out: out.write(data); out.flush(); os.fsync(out.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name): os.unlink(name)

def apply_changes(changes: list[Change],backup: Path) -> None:
    for c in changes:
        actual=c.path.read_bytes() if c.path.exists() else None
        if actual!=c.before: raise RuntimeError(f'预检后文件发生变化，停止：{c.path}')
    backup.mkdir(parents=True,exist_ok=False)
    manifest=[]
    for index,c in enumerate(changes):
        entry={'path':str(c.path),'before_sha256':sha(c.before),'after_sha256':sha(c.after),'backup':None}
        if c.before is not None:
            name=f'{index:03d}_{c.path.name}'; (backup/name).write_bytes(c.before); entry['backup']=name
        manifest.append(entry)
    (backup/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    written=[]
    try:
        for c in changes:
            actual=c.path.read_bytes() if c.path.exists() else None
            if actual!=c.before: raise RuntimeError(f'写入前发现并发修改，停止：{c.path}')
            atomic_write(c.path,c.after); written.append(c)
        for c in changes:
            if c.path.read_bytes()!=c.after: raise RuntimeError(f'回读不一致：{c.path}')
    except Exception:
        failed=[]
        for c in reversed(written):
            actual=c.path.read_bytes() if c.path.exists() else None
            if actual!=c.after: failed.append(str(c.path)); continue
            if c.before is None: c.path.unlink()
            else: atomic_write(c.path,c.before)
        (backup/'rollback.json').write_text(json.dumps({'not_rolled_back_due_to_concurrent_change':failed},ensure_ascii=False,indent=2),encoding='utf-8')
        raise

def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('D:/短剧制作'))
    parser.add_argument('--project',default='被炼化后的男友悔疯了')
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--plan',type=Path,help='必须使用上一轮预检产生的plan.json')
    parser.add_argument('--report-dir',type=Path,default=HERE/'预检报告')
    args=parser.parse_args()
    try:
        changes=collect_changes(args.root,args.project)
        plan=serial_plan(changes)
        if not changes:
            print('当前安装已匹配v3.5全部记录，无需再次修改。'); return 0
        if args.apply:
            if args.plan is None: raise ValueError('--apply 必须同时提供 --plan 上一轮预检的plan.json')
            approved=json.loads(args.plan.read_text(encoding='utf-8-sig'))
            if approved!=plan: raise ValueError('当前文件或升级包与预检计划不同，重新预检后再应用。')
            stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            backup=args.root.resolve()/'_通用短剧工作流/_升级记录'/('v3.5_apply_'+stamp)
            apply_changes(changes,backup)
            print(json.dumps({'applied_files':len(changes),'backup':str(backup),'readback_verified':True,'video_or_platform_validation':False},ensure_ascii=False,indent=2))
        else:
            args.report_dir.mkdir(parents=True,exist_ok=True)
            (args.report_dir/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
            diffs=[]
            for c in changes:
                before=normalize(c.before).splitlines(keepends=True) if c.before else []
                after=normalize(c.after).splitlines(keepends=True)
                diffs.extend(difflib.unified_diff(before,after,fromfile=str(c.path)+' (before)',tofile=str(c.path)+' (after)'))
            (args.report_dir/'changes.diff').write_text(''.join(diffs),encoding='utf-8')
            print(json.dumps({'mode':'preview_only','project_files_modified':False,'planned_files':len(changes),'plan':str((args.report_dir/'plan.json').resolve()),'diff':str((args.report_dir/'changes.diff').resolve())},ensure_ascii=False,indent=2))
    except (OSError,ValueError,RuntimeError) as exc:
        print('升级停止：'+str(exc)); return 1
    return 0

if __name__=='__main__': raise SystemExit(main())
