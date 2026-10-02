"""建立或补齐短剧项目控制文件；先预检，保留既有内容。Python 3.10+。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

try:
    from .workflow_paths import discover_from_tool, load_layout, reject_links, resource_path, WorkflowError, read_binding, make_binding, parse_json, json_bytes, SKILLS
    from .workflow_lock import make_lock, read_lock, verify_lock
except ImportError:
    from workflow_paths import discover_from_tool, load_layout, reject_links, resource_path, WorkflowError, read_binding, make_binding, parse_json, json_bytes, SKILLS
    from workflow_lock import make_lock, read_lock, verify_lock

DIRS = ('人物', '场景', '道具', '音色', '成片', '视频提示词', '提交快照')
TEMPLATES = {
    '项目启动说明.md': 'template.project_start',
    '项目参数.json': 'template.project_parameters',
    'AGENTS.md': 'template.project_agents',
    '制作台账.json': 'template.ledger',
}


def validate_name(name: str) -> None:
    reserved = name.split('.')[0].upper()
    if (not name or name != name.strip() or name in {'.', '..'} or name.endswith('.')
            or re.search(r'[\\/<>:"|?*\x00-\x1f]', name)
            or reserved in {'CON', 'PRN', 'AUX', 'NUL'}
            or re.fullmatch(r'(COM|LPT)[1-9]', reserved)):
        raise ValueError('ProjectName 必须是合法的单层项目名，不能是路径或保留名称。')


def _json_bytes(data: Any) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def template_content(layout) -> dict[str, bytes]:
    content = {target: resource_path(layout, rid).read_bytes() for target, rid in TEMPLATES.items()}
    params = parse_json(content['项目参数.json'])
    if (params.get('schema') != 'JM-v3.5' or not isinstance(params.get('project'), dict)
            or not isinstance(params.get('authorities'), dict)
            or not isinstance(params['authorities'].get('skills'), dict)):
        raise WorkflowError('TEMPLATE_INVALID', '项目参数模板 schema/project/authorities 无效')
    for rid, name in SKILLS.items():
        authority = params['authorities']['skills'].get(name)
        if not isinstance(authority, dict) or authority.get('resource_id') != rid:
            raise WorkflowError('TEMPLATE_INVALID', f'参数模板 Skill authority 无效：{rid}')
    ledger = parse_json(content['制作台账.json'])
    if (ledger.get('schema') != 'JM-ledger-v1' or not isinstance(ledger.get('segments'), list)
            or not isinstance(ledger.get('segment_fields'), list)
            or not isinstance(ledger.get('legacy_sources'), list)
            or not isinstance(ledger.get('current_mode'), str) or 'next_action' not in ledger):
        raise WorkflowError('TEMPLATE_INVALID', '制作台账模板必要结构无效')
    if any(not isinstance(x, str) for x in ledger['segment_fields']):
        raise WorkflowError('TEMPLATE_INVALID', '台账 segment_fields 必须为字符串数组')
    # 同样预检单段 JSON 和文本编码，不把坏模板留到项目创建后。
    segment = parse_json(resource_path(layout, 'template.segment_check').read_bytes())
    if segment.get('schema') not in {'JM-segment-check-v1','JM-segment-check-v2'}:
        raise WorkflowError('TEMPLATE_INVALID', '单段清单模板 schema 无效')
    for raw in content.values():
        raw.decode('utf-8-sig')
    from_block = content['AGENTS.md']
    start, end = b'<!-- WORKFLOW-BOOTSTRAP START -->', b'<!-- WORKFLOW-BOOTSTRAP END -->'
    if from_block.count(start) != 1 or from_block.count(end) != 1 or from_block.index(start) >= from_block.index(end):
        raise WorkflowError('TEMPLATE_INVALID', '项目 AGENTS 模板管理块无效')
    return content


def initialize(root: Path, name: str, *, common_root: Path | None = None,
               search_roots: list[Path] | None = None) -> dict[str, Any]:
    validate_name(name)
    layout = load_layout(common_root) if common_root is not None else discover_from_tool(Path(__file__))
    reject_links(Path(root))
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f'项目创建父目录不存在：{root}')
    if not os.access(root, os.W_OK):
        raise ValueError(f'项目创建父目录不可写：{root}')
    project = root / name
    reject_links(project)
    if project == layout.root or layout.root in project.parents:
        raise ValueError('项目不能位于公共工作流目录内部。')
    if project.exists() and not project.is_dir():
        raise ValueError(f'项目目标不是目录：{project}')
    existing = project.is_dir()
    if existing and not os.access(project, os.W_OK):
        raise ValueError(f'项目目录不可写：{project}')
    if existing:
        binding_path = project / '工作流绑定.json'
        lock_path = project / '工作流版本锁.json'
        if not binding_path.is_file() or not lock_path.is_file():
            raise WorkflowError('MIGRATION_REQUIRED', '已有项目缺少绑定或版本锁；请先做显式迁移')
        binding = read_binding(project)
        if binding['workflow_id'] != layout.workflow_id or binding['bundle_id'] != layout.bundle_id:
            raise WorkflowError('BINDING_INVALID', '已有项目绑定身份不符')
        if not verify_lock(layout, read_lock(lock_path))['ok']:
            raise WorkflowError('LOCK_CHANGED', '已有项目版本锁与当前内容不同；请先审查迁移')
    # 所有读取、JSON 解析与锁构造均先于写入。
    content = template_content(layout)
    params = parse_json(content['项目参数.json'])
    params['project'].update({'name': name, 'root': str(project), 'common_root': str(layout.root)})
    content['项目参数.json'] = _json_bytes(params)
    content['工作流绑定.json'] = json_bytes(make_binding(project, layout, search_roots=search_roots))
    content['工作流版本锁.json'] = _json_bytes(make_lock(layout))
    for folder in DIRS:
        target = project / folder
        reject_links(target)
        if target.exists() and not target.is_dir():
            raise ValueError(f'预期目录却存在同名文件：{target}')
    for target in content:
        path = project / target
        reject_links(path)
        if path.exists() and not path.is_file():
            raise ValueError(f'预期文件却存在其他类型：{path}')
    created_files: dict[Path, bytes] = {}
    created_dirs: list[Path] = []
    kept = []
    try:
        if not existing:
            project.mkdir(exist_ok=False)
            created_dirs.append(project)
        for folder in DIRS:
            path = project / folder
            if not path.exists():
                path.mkdir()
                created_dirs.append(path)
        for target, data in content.items():
            path = project / target
            try:
                with path.open('xb') as stream:
                    created_files[path] = data
                    stream.write(data)
            except FileExistsError:
                kept.append(target)
    except (OSError, ValueError) as exc:
        residual = []
        for path, planned in reversed(list(created_files.items())):
            try:
                actual = path.read_bytes()
                if actual == planned:
                    path.unlink()
                else:
                    residual.append(str(path))
            except OSError:
                residual.append(str(path))
        for path in reversed(created_dirs):
            try:
                path.rmdir()
            except OSError:
                residual.append(str(path))
        raise WorkflowError('INITIALIZE_IO_FAILED', f'初始化写入失败：{exc}', residual=residual) from exc
    return {'project': str(project), 'created': [p.name for p in created_files],
            'preserved': kept, 'platform_actions': False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, help='新项目的创建父目录；默认公共工作流的父目录')
    parser.add_argument('--project-name', required=True)
    parser.add_argument('--common', type=Path, help='明确指定公共工作流目录')
    parser.add_argument('--search-root', type=Path, action='append', help='显式浅层搜索范围；相对项目目录')
    args = parser.parse_args()
    try:
        layout = load_layout(args.common) if args.common else discover_from_tool(Path(__file__))
        result = initialize(args.root or layout.root.parent, args.project_name, common_root=layout.root, search_roots=args.search_root)
    except (OSError, ValueError) as exc:
        parser.exit(2, f'初始化停止：{exc}\n')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
