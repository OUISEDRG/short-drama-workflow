"""单项目旧锁迁移及 v2 内容升级：plan 只读，apply 须批准计划原始字节 SHA-256。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path, PureWindowsPath
import tempfile
import sys
from typing import Any

try:
    from .workflow_paths import WorkflowError, load_layout, read_json, reject_links, resource_path, parse_json, json_bytes, make_binding, SKILLS
    from .workflow_lock import make_lock, sha256_file, verify_lock
except ImportError:
    from workflow_paths import WorkflowError, load_layout, read_json, reject_links, resource_path, parse_json, json_bytes, make_binding, SKILLS
    from workflow_lock import make_lock, sha256_file, verify_lock

CONTROL = ('AGENTS.md', '项目参数.json', '工作流绑定.json', '工作流版本锁.json')
_json_bytes = json_bytes
BLOCK_START = '<!-- WORKFLOW-BOOTSTRAP START -->'
BLOCK_END = '<!-- WORKFLOW-BOOTSTRAP END -->'

# 已发布 4f30aee 的 writer/参数母版；不靠文件名后缀猜测公共来源。
LEGACY_BUNDLE = 'Codex适配剧梦提示词库（模版）0914'
LEGACY_AUTHORITY_PATHS = {
    **{name: (name + '/SKILL.md', None) for name in SKILLS.values()},
    'content': ('sd25-video-prompt-compiler/references/视频模型工作流配置_SD2.5_v3.4.md', '7.3'),
    'platform_content': ('dreamina-sd25-prompt-adapter/SKILL.md', None),
    'layout': ('视频提示词输出规范_资产全名版.md', '24'),
}
LEGACY_V35_RESOURCES = {
    'entry.maintenance', 'entry.rules', 'template.project_agents', 'template.project_start',
    'template.ledger', 'layout.final_prompt', 'tool.init_project', 'tool.workflow_check',
    'doc.bundle_readme', 'template.project_parameters', 'template.segment_check',
    'reference.director', 'reference.compiler', 'reference.production', *SKILLS,
}
# 6d2ca1b 基础设施 1.0 默认入口的定位区间；业务说明与用户尾部不在此区间。
LEGACY_BOOTSTRAP_V1_0 = (
    '公共工作流位置由本项目 `工作流绑定.json` 的浅层范围定位；`项目参数.json` 中的 `common_root` 仅为历史位置提示。\n\n'
    '开始工作或恢复任务时，先读取项目自己的 `项目启动说明.md`、`项目参数.json`、`制作台账.json`、`工作流绑定.json` 和 `工作流版本锁.json`。用当前文件读取能力在绑定声明的浅层范围查找固定 `workflow.manifest.json`，先只读 JSON 核对唯一身份、包清单和工具文件；不要先执行未知候选仓库的代码。已有锁时，可用终端 SHA-256 核对定位器及依赖，再运行已定位的 `tools/workflow_paths.py doctor --project <本项目路径> --json`。只有内容锁通过后，才按资源 ID 读取规则索引和当前任务所需 Skill；旧项目缺绑定须明确迁移。没有文件就标记缺口，不能凭旧聊天编造事实。'
).encode('utf-8')
LOCATOR_WORDS = ('通用工作流目录', 'common_root', 'workflow_paths.py',
                 'workflow.manifest.json', '工作流绑定.json')


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


def _legacy_v35_format(data: dict[str, Any]) -> bool:
    """有限识别真实无 schema writer；旧位置无需仍存在，不执行旧代码。"""
    if (set(data) != {'workflow_version', 'common_root', 'files'}
            or data.get('workflow_version') != '3.5'
            or not isinstance(data.get('common_root'), str)
            or not data['common_root'] or '\x00' in data['common_root']
            or not (Path(data['common_root']).is_absolute()
                    or PureWindowsPath(data['common_root']).is_absolute())
            or not isinstance(data.get('files'), dict) or not data['files']):
        return False
    return all(isinstance(path, str) and isinstance(sha, str)
               and re.fullmatch(r'[0-9a-fA-F]{64}', sha) is not None
               for path, sha in data['files'].items())


def _map_legacy(old_files: dict[str, Any], layout, *, historical_v35=False) -> tuple[dict[str, str], list[str]]:
    mapping = {}
    unknown = []
    for old_path, old_sha in old_files.items():
        if not isinstance(old_path, str) or not isinstance(old_sha, str) or re.fullmatch(r'[0-9a-fA-F]{64}', old_sha) is None:
            unknown.append(str(old_path))
            continue
        normalized = old_path.replace('\\', '/')
        if (PureWindowsPath(old_path).drive or normalized.startswith('/')
                or '\x00' in normalized or any(part in ('', '.', '..') for part in normalized.split('/'))):
            unknown.append(old_path)
            continue
        matches = []
        for rid, target in layout.resources.items():
            if historical_v35 and rid not in LEGACY_V35_RESOURCES:
                continue
            base = layout.bundle_root if layout.bundle_root in target.parents else layout.root
            rel = target.relative_to(base).as_posix()
            bundle_paths = {prefix + '/' + rel for prefix in (LEGACY_BUNDLE, layout.bundle_root.name)}
            if (base == layout.root and normalized == rel) or (base == layout.bundle_root and normalized in bundle_paths):
                matches.append(rid)
        if len(matches) != 1 or matches[0] in mapping.values():
            unknown.append(old_path)
        else:
            mapping[old_path] = matches[0]
    return mapping, unknown


def _block(raw: bytes) -> tuple[int, int]:
    try:
        raw.decode('utf-8-sig')
    except UnicodeError as exc:
        raise WorkflowError('AGENTS_MERGE_REVIEW_REQUIRED', 'AGENTS 编码无效') from exc
    start, end = BLOCK_START.encode(), BLOCK_END.encode()
    if raw.count(start) != 1 or raw.count(end) != 1 or raw.index(start) >= raw.index(end):
        raise WorkflowError('AGENTS_MERGE_REVIEW_REQUIRED', '管理块逆序、重复、嵌套或缺半边')
    return raw.index(start), raw.index(end) + len(end)


def merge_agents(original: bytes | None, template: bytes) -> bytes:
    a, b = _block(template)
    block = template[a:b]
    if original is None:
        return template
    try:
        text = original.decode('utf-8-sig')
    except UnicodeError as exc:
        raise WorkflowError('AGENTS_MERGE_REVIEW_REQUIRED', 'AGENTS 编码无效') from exc
    if BLOCK_START in text or BLOCK_END in text:
        a, b = _block(original)
        outside = (original[:a] + original[b:]).decode('utf-8-sig')
        if any(word in outside for word in LOCATOR_WORDS):
            raise WorkflowError('AGENTS_MERGE_REVIEW_REQUIRED', '管理块外存在冲突定位指令')
        return original[:a] + block + original[b:]
    legacy_matches = []
    for known in (LEGACY_BOOTSTRAP_V1_0, LEGACY_BOOTSTRAP_V1_0.replace(b'\n', b'\r\n')):
        offset = 0
        while (a := original.find(known, offset)) >= 0:
            b = a + len(known)
            # 只认可完整独立行；不从修改过的段落内部截取默认字符串。
            if ((a == 0 or original[a-1:a] == b'\n' or a == 3 and original[:3] == b'\xef\xbb\xbf')
                    and (b == len(original) or original[b:b+1] in (b'\r', b'\n'))):
                legacy_matches.append((a, b))
            offset = b
    if legacy_matches:
        if len(legacy_matches) != 1:
            raise WorkflowError('AGENTS_MERGE_REVIEW_REQUIRED', '多个 1.0 默认入口需人工审查')
        a, b = legacy_matches[0]
        outside = (original[:a] + original[b:]).decode('utf-8-sig')
        if any(word in outside for word in LOCATOR_WORDS):
            raise WorkflowError('AGENTS_MERGE_REVIEW_REQUIRED', '1.0 默认入口外存在冲突定位指令')
        return original[:a] + block + original[b:]
    lines = original.splitlines(keepends=True)
    recognized = [i for i, line in enumerate(lines) if line.startswith(
        ('通用工作流目录：'.encode(), '通用工作流目录:'.encode()))]
    if len(recognized) > 1:
        raise WorkflowError('AGENTS_MERGE_REVIEW_REQUIRED', '多个旧入口行需人工审查')
    if recognized:
        i = recognized[0]
        rest = b''.join(lines[:i] + lines[i+1:]).decode('utf-8-sig')
        if any(word in rest for word in LOCATOR_WORDS):
            raise WorkflowError('AGENTS_MERGE_REVIEW_REQUIRED', '块外存在冲突定位指令')
        newline = b'\r\n' if lines[i].endswith(b'\r\n') else b'\n' if lines[i].endswith(b'\n') else b''
        return b''.join(lines[:i]) + block + newline + b''.join(lines[i+1:])
    if any(word in text for word in LOCATOR_WORDS):
        raise WorkflowError('AGENTS_MERGE_REVIEW_REQUIRED', '无法唯一识别旧定位指令')
    return original + b'\n\n' + block + b'\n'


def merge_parameters(original: bytes, template: bytes, *, common_root: Path) -> bytes:
    data, authority_template = parse_json(original), parse_json(template)
    if not isinstance(data.get('project'), dict) or not isinstance(data.get('authorities', {}), dict):
        raise WorkflowError('PARAMETERS_MERGE_REVIEW_REQUIRED', '参数 project/authorities 类型冲突')
    authorities = data.setdefault('authorities', {})
    skills = authorities.setdefault('skills', {})
    if not isinstance(skills, dict):
        raise WorkflowError('PARAMETERS_MERGE_REVIEW_REQUIRED', 'skills 类型冲突')
    template_auth = authority_template.get('authorities', {})
    if not isinstance(template_auth, dict) or not isinstance(template_auth.get('skills', {}), dict):
        raise WorkflowError('PARAMETERS_MERGE_REVIEW_REQUIRED', 'authority 模板类型冲突')
    known = {**{name: rid for rid, name in SKILLS.items()},
             'content': 'reference.compiler', 'platform_content': 'skill.adapter', 'layout': 'layout.final_prompt'}
    def default_path(value, name, separate_section=None):
        if not isinstance(value, str):
            return False
        path, fragment, section = value.replace('\\', '/').partition('#')
        expected_path, expected_section = LEGACY_AUTHORITY_PATHS[name]
        if path != expected_path:
            return False
        if fragment:
            return expected_section is not None and section == expected_section
        return expected_section is None or separate_section == expected_section
    for name, rid in known.items():
        target = skills if name in SKILLS.values() else authorities
        desired = template_auth.get('skills', {}).get(name) if target is skills else template_auth.get(name)
        if desired is None:
            continue
        if not isinstance(desired, dict) or desired.get('resource_id') != rid:
            raise WorkflowError('PARAMETERS_MERGE_REVIEW_REQUIRED', f'已知 authority 模板无效：{name}')
        old = target.get(name, {})
        if isinstance(old, str) and default_path(old, name):
            old = {}
        if not isinstance(old, dict):
            raise WorkflowError('PARAMETERS_MERGE_REVIEW_REQUIRED', f'自定义 authority 来源需审查：{name}')
        if ('resource_id' in old and old['resource_id'] != rid
                or 'path' in old and not default_path(old['path'], name, old.get('section'))
                or 'section' in old and old['section'] != desired.get('section')):
            raise WorkflowError('PARAMETERS_MERGE_REVIEW_REQUIRED', f'自定义 authority 指向需审查：{name}')
        old.pop('path', None)
        for key in ('resource_id', 'section'):
            if key in desired:
                old[key] = desired[key]
        target[name] = old
    data['project']['common_root'] = str(common_root)
    return original if data == parse_json(original) else json_bytes(data)


def _proposed(project: Path, layout, *, search_roots=None, replace_lock=True) -> dict[str, bytes | None]:
    binding_path = project / '工作流绑定.json'
    old_binding = read_json(binding_path) if binding_path.is_file() else {}
    if search_roots is None and old_binding.get('schema') == 'JM-workflow-binding-v1':
        values = old_binding.get('search_roots')
        if not isinstance(values, list) or any(not isinstance(x, str) for x in values):
            raise WorkflowError('BINDING_INVALID', '旧绑定范围类型错误')
        scopes = [Path(x) if Path(x).is_absolute() else project / x for x in values]
        if any(Path(os.path.abspath(x)) in (layout.root, layout.root.parent) for x in scopes):
            search_roots = scopes
    binding = {**old_binding, **make_binding(project, layout, search_roots=search_roots)}
    binding_bytes = binding_path.read_bytes() if old_binding == binding else json_bytes(binding)
    parameters = project / '项目参数.json'
    if not parameters.is_file():
        raise WorkflowError('PARAMETERS_MERGE_REVIEW_REQUIRED', '项目参数缺失，不能补造业务证据')
    return {
        'AGENTS.md': merge_agents((project / 'AGENTS.md').read_bytes() if (project / 'AGENTS.md').is_file() else None,
                                 resource_path(layout, 'template.project_agents').read_bytes()),
        '项目参数.json': merge_parameters(parameters.read_bytes(), resource_path(layout, 'template.project_parameters').read_bytes(), common_root=layout.root),
        '工作流绑定.json': binding_bytes,
        '工作流版本锁.json': json_bytes(make_lock(layout)) if replace_lock else (project / '工作流版本锁.json').read_bytes(),
    }


def _field_diffs(before, after, prefix=''):
    if isinstance(before, dict) and isinstance(after, dict):
        result = {}
        for key in sorted(before.keys() | after.keys()):
            result.update(_field_diffs(before.get(key), after.get(key), (prefix + '.' + key).lstrip('.')))
        return result
    return {} if before == after else {prefix: {'before': before, 'after': after}}


def plan(project: Path, common: Path, *, search_roots: list[Path] | None = None) -> dict[str, Any]:
    reject_links(Path(project))
    project = Path(project).resolve()
    if not project.is_dir():
        raise WorkflowError('PROJECT_NOT_FOUND', f'项目不存在：{project}')
    layout = load_layout(common)
    if project == layout.root or layout.root in project.parents:
        raise WorkflowError('MIGRATION_TARGET_INVALID', '项目不能位于公共工作流内部')
    controls = _snapshot(project)
    old_path = project / '工作流版本锁.json'
    old = read_json(old_path) if old_path.is_file() else {}
    new_lock = make_lock(layout)
    mapping, unknown, changed, added, missing, unchanged = {}, [], [], [], [], []
    blockers = []
    source_schema = old.get('schema')
    historical_v35 = 'schema' not in old and _legacy_v35_format(old)
    replace_lock = True
    relocated, versions = [], []
    if source_schema == 'JM-workflow-lock-v2':
        comparison = verify_lock(layout, old)
        changed, added, missing = (comparison[k] for k in ('changed_resources','added_resources','missing_resources'))
        relocated, versions = comparison['relocated_resources'], comparison['version_diffs']
        unchanged = sorted(set(old['resources']) & set(new_lock['resources']) - set(changed))
        blockers.extend(f'原锁资源无兼容映射：{rid}' for rid in missing)
        replace_lock = not comparison['ok'] or bool(relocated)
    elif (historical_v35 or source_schema in ('JM-workflow-lock-v1', 'JM-v3.5-workflow-lock')) and isinstance(old.get('files'), dict):
        mapping, unknown = _map_legacy(old['files'], layout, historical_v35=historical_v35)
        if historical_v35:
            blockers.extend(f'历史 3.5 锁缺必要资源：{rid}' for rid in sorted(LEGACY_V35_RESOURCES - set(mapping.values())))
        for old_name, rid in mapping.items():
            (unchanged if old['files'][old_name].lower() == new_lock['resources'][rid]['sha256'] else changed).append(rid)
        added = sorted(set(new_lock['resources']) - set(mapping.values()))
        blockers.extend(f'旧锁条目无法唯一映射：{item}' for item in unknown)
    else:
        blockers.append('LOCK_MISSING' if not old else 'LOCK_SCHEMA_UNKNOWN')
    try:
        proposed = _proposed(project, layout, search_roots=search_roots, replace_lock=replace_lock)
    except WorkflowError as exc:
        blockers.append(f'{exc.code}: {exc}')
        proposed = {}
    diffs = {}
    for name, raw in proposed.items():
        if name.endswith('.json'):
            before = read_json(project / name) if (project / name).is_file() else {}
            diffs[name] = _field_diffs(before, parse_json(raw))
        elif controls[name] != _digest(raw):
            diffs[name] = {'before': (project / name).read_bytes().decode('utf-8-sig') if (project / name).is_file() else None,
                           'after': raw.decode('utf-8-sig')}
    changes = {name: {'old_sha256': controls[name], 'new_sha256': _digest(data)}
               for name, data in proposed.items() if controls[name] != _digest(data)}
    content_upgrade = bool(changed or added or missing or versions or relocated)
    operation = ('legacy_migration' if source_schema != 'JM-workflow-lock-v2' else
                 'content_upgrade' if content_upgrade else 'rebind' if changes else 'no_op')
    return {'schema': 'JM-workflow-migration-plan-v1', 'contract_version': 2,
            'project': str(project), 'common': str(layout.root), 'workflow_id': layout.workflow_id,
            'bundle_id': layout.bundle_id, 'source_lock_schema': source_schema,
            'source_lock_format': 'legacy-3.5-noschema' if historical_v35 else source_schema,
            'operation': operation, 'no_op': not changes and not blockers,
            'search_roots': [str(x) for x in search_roots] if search_roots is not None else None,
            'old_lock_sha256': controls['工作流版本锁.json'], 'control_preconditions': controls,
            'resource_sha256': {rid: item['sha256'] for rid, item in new_lock['resources'].items()},
            'legacy_mapping': mapping, 'unchanged_resources': sorted(unchanged),
            'changed_resources': sorted(changed), 'added_resources': added, 'missing_resources': missing,
            'relocated_resources': relocated, 'version_diffs': versions,
            'unmapped_legacy': unknown, 'control_changes': changes, 'proposed_diffs': diffs,
            'backup_rule': '项目/_workflow_migration_backups/<计划SHA256前16位>/原始控制文件',
            'blockers': blockers, 'requires_content_upgrade_review': content_upgrade}


def _write_exclusive(path: Path, data: bytes) -> None:
    with path.open('xb') as stream:
        stream.write(data)


def _restore_owned(path: Path, original: bytes | None, expected_hash: str) -> bool:
    reject_links(path)
    if sha256_file(path) != expected_hash:
        return False
    if original is None:
        path.unlink()
        return True
    fd, name = tempfile.mkstemp(prefix='.workflow-recover-', dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
        if sha256_file(path) != expected_hash:
            return False
        os.replace(temp, path)
        return True
    finally:
        if temp.exists():
            temp.unlink()


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
            or spec.get('contract_version') != 2
            or not isinstance(spec.get('control_changes'), dict)
            or spec.get('search_roots') is not None and (not isinstance(spec['search_roots'], list) or any(not isinstance(x, str) for x in spec['search_roots']))
            or not set(spec['control_changes']) <= set(CONTROL)):
        raise WorkflowError('MIGRATION_PLAN_INVALID', '迁移计划字段或控制文件白名单无效')
    reject_links(Path(project))
    project = Path(project).resolve()
    if str(project) != spec.get('project') or not project.is_dir():
        raise WorkflowError('MIGRATION_PLAN_STALE', '计划项目路径与显式项目不一致')
    common = Path(spec['common'])
    scopes = [Path(x) for x in spec['search_roots']] if spec.get('search_roots') is not None else None
    current = plan(project, common, search_roots=scopes)
    if current['blockers']:
        raise WorkflowError('MIGRATION_BLOCKED', f"重新计算有阻塞项：{current['blockers']}")
    if current != spec:
        raise WorkflowError('MIGRATION_PLAN_STALE', '计划字段或前置条件变化；请重新生成计划')
    if current['no_op']:
        return {'ok': True, 'no_op': True, 'written': [], 'backup': None}
    layout = load_layout(common)
    proposed = _proposed(project, layout, search_roots=scopes,
                         replace_lock=current['operation'] in ('legacy_migration', 'content_upgrade'))
    changes = {name: data for name, data in proposed.items() if data is not None and
               current['control_preconditions'][name] != _digest(data)}
    if (_snapshot(project) != current['control_preconditions'] or
            {rid: item['sha256'] for rid, item in make_lock(load_layout(common))['resources'].items()} != current['resource_sha256']):
        raise WorkflowError('MIGRATION_PLAN_STALE', '备份之前前置内容发生变化')
    backup = project / '_workflow_migration_backups' / digest[:16]
    reject_links(backup)
    if backup.exists():
        raise WorkflowError('MIGRATION_ALREADY_APPLIED', f'迁移备份目录已存在：{backup}')
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
            expected_controls = {**current['control_preconditions'], **written}
            if (_snapshot(project) != expected_controls or
                    {rid: item['sha256'] for rid, item in make_lock(load_layout(common))['resources'].items()} != current['resource_sha256']):
                raise WorkflowError('MIGRATION_PLAN_STALE', f'写入前控制文件或公共资源变化：{name}')
            os.replace(temp_path, path)
            staged.remove(temp_path)
            written[name] = _digest(data)
        if _snapshot(project) != {**current['control_preconditions'], **written}:
            raise WorkflowError('MIGRATION_PLAN_STALE', '写入之后控制文件变化')
        if not verify_lock(load_layout(common), read_json(project / '工作流版本锁.json'))['ok']:
            raise WorkflowError('MIGRATION_PLAN_STALE', '写入之后公共锁变化')
    except Exception as exc:
        for temp_path in staged:
            try:
                temp_path.unlink()
            except OSError:
                residual.append(str(temp_path))
        for name, new_hash in reversed(list(written.items())):
            path = project / name
            try:
                if not _restore_owned(path, originals[name], new_hash):
                    residual.append(str(path))
            except (OSError, WorkflowError):
                residual.append(str(path))
        try:
            _write_exclusive(backup / 'recovery.json', _json_bytes({'error': str(exc), 'residual': residual}))
        except OSError:
            residual.append(str(backup / 'recovery.json'))
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
    p.add_argument('--search-root', type=Path, action='append')
    a = sub.add_parser('apply')
    a.add_argument('--project', type=Path, required=True)
    a.add_argument('--plan', type=Path, required=True)
    a.add_argument('--approve-plan-sha256', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'plan':
            result = plan(args.project, args.common, search_roots=args.search_root)
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
