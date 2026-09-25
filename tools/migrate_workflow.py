"""单项目旧锁迁移：plan 只读，apply 须批准计划原始字节 SHA-256。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import sys
from typing import Any

try:
    from .workflow_paths import WorkflowError, load_layout, read_json, reject_links, resource_path
    from .workflow_lock import make_lock, sha256_file
    from .init_project import _binding, _json_bytes
except ImportError:
    from workflow_paths import WorkflowError, load_layout, read_json, reject_links, resource_path
    from workflow_lock import make_lock, sha256_file
    from init_project import _binding, _json_bytes

CONTROL = ('AGENTS.md', '项目参数.json', '工作流绑定.json', '工作流版本锁.json')
BLOCK_START = '<!-- WORKFLOW-BOOTSTRAP START -->'
BLOCK_END = '<!-- WORKFLOW-BOOTSTRAP END -->'


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _snapshot(project: Path) -> dict[str, str | None]:
    result = {}
    for name in CONTROL:
        path = project / name
        reject_links(path)
        if path.exists() and not path.is_file():
            raise WorkflowError('MIGRATION_CONTROL_INVALID', f'控制文件不是普通文件：{path}')
        result[name] = sha256_file(path) if path.is_file() else None
    return result


def _map_legacy(old_files: dict[str, Any], layout) -> tuple[dict[str, str], list[str]]:
    mapping = {}
    unknown = []
    for old_path, old_sha in old_files.items():
        if not isinstance(old_path, str) or not isinstance(old_sha, str) or len(old_sha) != 64:
            unknown.append(str(old_path))
            continue
        normalized = old_path.replace('\\', '/')
        matches = []
        for rid, target in layout.resources.items():
            base = layout.bundle_root if layout.bundle_root in target.parents else layout.root
            rel = target.relative_to(base).as_posix()
            if (base == layout.root and normalized == rel) or (base == layout.bundle_root and normalized.endswith('/' + rel)):
                matches.append(rid)
        if len(matches) != 1 or matches[0] in mapping.values():
            unknown.append(old_path)
        else:
            mapping[old_path] = matches[0]
    return mapping, unknown


def _agents_update(original: bytes | None) -> bytes:
    try:
        text = original.decode('utf-8-sig') if original is not None else '# 短剧项目工作入口\n'
    except UnicodeError as exc:
        raise WorkflowError('AGENTS_MERGE_REVIEW_REQUIRED', f'AGENTS 编码无法安全读取：{exc}') from exc
    if text.count(BLOCK_START) != text.count(BLOCK_END) or text.count(BLOCK_START) > 1:
        raise WorkflowError('AGENTS_MERGE_REVIEW_REQUIRED', 'AGENTS 管理块边界重复或损坏')
    block = (f'{BLOCK_START}\n'
             '先读项目的工作流绑定.json 与工作流版本锁.json；按绑定的浅层范围只读寻找 workflow.manifest.json，'
             '核对唯一身份与资源后运行 workflow_paths.py doctor --project <本项目路径> --json。'
             '差异须审查，不能自动更新锁。定位与迁移命令见公共工作流根目录 README.md。\n'
             f'{BLOCK_END}')
    if BLOCK_START in text:
        start = text.index(BLOCK_START)
        end = text.index(BLOCK_END) + len(BLOCK_END)
        text = text[:start] + block + text[end:]
    else:
        lines = text.splitlines(keepends=True)
        recognized = [i for i, line in enumerate(lines) if line.startswith('通用工作流目录：') or line.startswith('通用工作流目录:')]
        if len(recognized) > 1:
            raise WorkflowError('AGENTS_MERGE_REVIEW_REQUIRED', 'AGENTS 存在多处旧公共目录入口')
        if recognized:
            lines[recognized[0]] = block + '\n'
            text = ''.join(lines)
        else:
            if '通用工作流目录' in text or 'common_root' in text:
                raise WorkflowError('AGENTS_MERGE_REVIEW_REQUIRED', 'AGENTS 中旧路径指令无法安全识别')
            text = text.rstrip('\n') + '\n\n' + block + '\n'
    return text.encode('utf-8')


def _parameters_update(original: bytes | None, layout) -> bytes | None:
    if original is None:
        return None
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise WorkflowError('PARAMETERS_MERGE_REVIEW_REQUIRED', f'项目参数有重复 JSON 键：{key}')
            result[key] = value
        return result
    try:
        data = json.loads(original.decode('utf-8-sig'), object_pairs_hook=pairs)
    except WorkflowError:
        raise
    except (ValueError, UnicodeError) as exc:
        raise WorkflowError('PARAMETERS_MERGE_REVIEW_REQUIRED', f'项目参数无法解析：{exc}') from exc
    if not isinstance(data, dict) or not isinstance(data.get('project'), dict):
        raise WorkflowError('PARAMETERS_MERGE_REVIEW_REQUIRED', '项目参数结构无效')
    template = read_json(resource_path(layout, 'template.project_parameters'))
    data['project']['common_root'] = str(layout.root)  # 历史字段，只作提示
    data['authorities'] = template['authorities']
    return _json_bytes(data)


def _proposed(project: Path, layout) -> dict[str, bytes | None]:
    return {
        'AGENTS.md': _agents_update((project / 'AGENTS.md').read_bytes() if (project / 'AGENTS.md').is_file() else None),
        '项目参数.json': _parameters_update((project / '项目参数.json').read_bytes() if (project / '项目参数.json').is_file() else None, layout),
        '工作流绑定.json': _json_bytes(_binding(project, layout.root)),
        '工作流版本锁.json': _json_bytes(make_lock(layout)),
    }


def plan(project: Path, common: Path) -> dict[str, Any]:
    reject_links(Path(project))
    project = Path(project).resolve()
    if not project.is_dir():
        raise WorkflowError('PROJECT_NOT_FOUND', f'项目不存在：{project}')
    layout = load_layout(common)
    controls = _snapshot(project)
    old_path = project / '工作流版本锁.json'
    if not old_path.is_file():
        raise WorkflowError('LOCK_MISSING', '缺少旧版本锁，无法自动映射；需人工审查')
    old = read_json(old_path)
    if old.get('schema') == 'JM-workflow-lock-v2':
        raise WorkflowError('MIGRATION_ALREADY_APPLIED', '项目已有 v2 锁；请使用 doctor 核验')
    files = old.get('files')
    if not isinstance(files, dict):
        raise WorkflowError('LOCK_LEGACY_INVALID', '旧锁缺少 files 资源表')
    new_lock = make_lock(layout)
    mapping, unknown = _map_legacy(files, layout)
    unchanged = []
    changed = []
    for old_name, rid in mapping.items():
        (unchanged if files[old_name].lower() == new_lock['resources'][rid]['sha256'] else changed).append(rid)
    added = sorted(set(new_lock['resources']) - set(mapping.values()))
    blockers = [f'旧锁条目无法唯一映射：{item}' for item in unknown]
    try:
        proposed = _proposed(project, layout)
    except WorkflowError as exc:
        blockers.append(f'{exc.code}: {exc}')
        proposed = {}
    proposed_diffs = {}
    if proposed.get('AGENTS.md') is not None:
        before = (project / 'AGENTS.md').read_text(encoding='utf-8-sig') if (project / 'AGENTS.md').is_file() else None
        after = proposed['AGENTS.md'].decode('utf-8')
        if before != after:
            proposed_diffs['AGENTS.md'] = {'before': before, 'after': after}
    if proposed.get('项目参数.json') is not None:
        before = read_json(project / '项目参数.json')
        after = json.loads(proposed['项目参数.json'].decode('utf-8'))
        proposed_diffs['项目参数.json'] = {
            'project.common_root': {'before': before.get('project', {}).get('common_root'),
                                    'after': after['project']['common_root']},
            'authorities': {'before': before.get('authorities'), 'after': after['authorities']},
        }
    changes = {name: {'old_sha256': controls[name], 'new_sha256': _digest(data) if data is not None else None}
               for name, data in proposed.items() if data is not None and controls[name] != _digest(data)}
    return {'schema': 'JM-workflow-migration-plan-v1', 'project': str(project),
            'common': str(layout.root), 'workflow_id': layout.workflow_id, 'bundle_id': layout.bundle_id,
            'old_lock_sha256': controls['工作流版本锁.json'], 'control_preconditions': controls,
            'resource_sha256': {rid: item['sha256'] for rid, item in new_lock['resources'].items()},
            'legacy_mapping': mapping, 'unchanged_resources': sorted(unchanged),
            'changed_resources': sorted(changed), 'added_resources': added,
            'unmapped_legacy': unknown, 'control_changes': changes,
            'proposed_diffs': proposed_diffs,
            'backup_rule': '项目/_workflow_migration_backups/<计划SHA256前16位>/原始控制文件',
            'blockers': blockers, 'requires_content_upgrade_review': bool(changed or added)}


def _write_exclusive(path: Path, data: bytes) -> None:
    with path.open('xb') as stream:
        stream.write(data)


def apply(project: Path, plan_path: Path, approved_sha256: str) -> dict[str, Any]:
    reject_links(Path(plan_path))
    plan_bytes = Path(plan_path).read_bytes()
    digest = _digest(plan_bytes)
    if approved_sha256.lower() != digest:
        raise WorkflowError('MIGRATION_APPROVAL_MISMATCH', '批准摘要与计划文件原始字节不符')
    spec = read_json(Path(plan_path))
    if spec.get('schema') != 'JM-workflow-migration-plan-v1':
        raise WorkflowError('MIGRATION_PLAN_INVALID', '迁移计划 schema 无效')
    if (not isinstance(spec.get('common'), str) or not isinstance(spec.get('project'), str)
            or not isinstance(spec.get('blockers'), list)
            or not isinstance(spec.get('control_changes'), dict)
            or not set(spec['control_changes']) <= set(CONTROL)):
        raise WorkflowError('MIGRATION_PLAN_INVALID', '迁移计划字段或控制文件白名单无效')
    reject_links(Path(project))
    project = Path(project).resolve()
    if str(project) != spec.get('project') or not project.is_dir():
        raise WorkflowError('MIGRATION_PLAN_STALE', '计划项目路径与显式项目不一致')
    if spec.get('blockers'):
        raise WorkflowError('MIGRATION_BLOCKED', f"迁移计划有阻塞项：{spec['blockers']}")
    # 不执行计划中的路径或指令；只根据固定白名单重新计算提案。
    common = Path(spec['common'])
    current = plan(project, common)
    for field in ('workflow_id', 'bundle_id', 'old_lock_sha256', 'control_preconditions',
                  'resource_sha256', 'legacy_mapping', 'control_changes', 'proposed_diffs'):
        if current.get(field) != spec.get(field):
            raise WorkflowError('MIGRATION_PLAN_STALE', f'计划前置条件变化：{field}')
    layout = load_layout(common)
    proposed = _proposed(project, layout)
    changes = {name: data for name, data in proposed.items() if data is not None and
               current['control_preconditions'][name] != _digest(data)}
    backup = project / '_workflow_migration_backups' / digest[:16]
    reject_links(backup)
    if backup.exists():
        raise WorkflowError('MIGRATION_ALREADY_APPLIED', f'迁移备份目录已存在：{backup}')
    created_parent = not backup.parent.exists()
    backup.mkdir(parents=True, exist_ok=False)
    originals = {}
    written = {}
    staged = []
    residual = []
    try:
        for name in changes:
            path = project / name
            original = path.read_bytes() if path.is_file() else None
            originals[name] = original
            if original is not None:
                _write_exclusive(backup / name, original)
        _write_exclusive(backup / 'backup_hashes.json', _json_bytes({name: _digest(data) if data is not None else None for name, data in originals.items()}))
        for name, data in changes.items():
            path = project / name
            reject_links(path)
            fd, tmp = tempfile.mkstemp(prefix='.workflow-stage-', dir=project)
            temp_path = Path(tmp)
            staged.append(temp_path)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if _snapshot(project)[name] != current['control_preconditions'][name]:
                raise WorkflowError('MIGRATION_PLAN_STALE', f'写入前文件变化：{name}')
            os.replace(temp_path, path)
            staged.remove(temp_path)
            written[name] = _digest(data)
    except Exception as exc:
        for temp_path in staged:
            try:
                temp_path.unlink()
            except OSError:
                residual.append(str(temp_path))
        for name, new_hash in reversed(list(written.items())):
            path = project / name
            try:
                if sha256_file(path) != new_hash:
                    residual.append(str(path))
                    continue
                old_data = originals[name]
                if old_data is None:
                    path.unlink()
                else:
                    path.write_bytes(old_data)
            except OSError:
                residual.append(str(path))
        _write_exclusive(backup / 'recovery.json', _json_bytes({'error': str(exc), 'residual': residual}))
        raise WorkflowError('MIGRATION_IO_FAILED', f'迁移写入失败并已尝试有限恢复：{exc}', backup=str(backup), residual=residual) from exc
    return {'ok': True, 'project': str(project), 'backup': str(backup), 'written': sorted(changes),
            'requires_content_upgrade_review': current['requires_content_upgrade_review']}


def main() -> int:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('plan')
    p.add_argument('--project', type=Path, required=True)
    p.add_argument('--common', type=Path, required=True)
    p.add_argument('--output', type=Path)
    a = sub.add_parser('apply')
    a.add_argument('--project', type=Path, required=True)
    a.add_argument('--plan', type=Path, required=True)
    a.add_argument('--approve-plan-sha256', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'plan':
            result = plan(args.project, args.common)
            data = _json_bytes(result)
            if args.output:
                _write_exclusive(args.output, data)
        else:
            result = apply(args.project, args.plan, args.approve_plan_sha256)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not result.get('blockers') else 3
    except (OSError, ValueError) as exc:
        code = exc.code if isinstance(exc, WorkflowError) else 'MIGRATION_ERROR'
        print(json.dumps({'ok': False, 'code': code, 'issues': [str(exc)]}, ensure_ascii=False))
        return 3 if code in {'MIGRATION_PLAN_STALE', 'LOCK_LEGACY', 'MIGRATION_BLOCKED'} else 2


if __name__ == '__main__':
    raise SystemExit(main())
