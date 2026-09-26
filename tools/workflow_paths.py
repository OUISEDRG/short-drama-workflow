"""按固定标识与资源 ID 有界定位公共工作流。所有诊断均只读。Python 3.10+。"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import sys
from typing import Any

WORKFLOW_ID = "jumeng.short-drama.workflow"
BUNDLE_ID = "jumeng.short-drama.core-skills"
EXCLUDED = {".git", "__pycache__", ".pytest_cache", "_backups", "tests", "docs", "maintenance"}
SKILLS = {
    "skill.prebreakdown": "screenplay-prebreakdown-analysis",
    "skill.director": "ai-short-drama-director",
    "skill.acting": "cinematic-acting-execution-library",
    "skill.compiler": "sd25-video-prompt-compiler",
    "skill.adapter": "dreamina-sd25-prompt-adapter",
    "skill.production": "dreamina-short-drama-production",
}
ROOT_RESOURCE_IDS = {
    'meta.workflow', 'doc.readme', 'entry.maintenance', 'entry.rules',
    'template.project_agents', 'template.project_start', 'template.ledger',
    'layout.final_prompt', 'tool.init_project', 'tool.workflow_check',
    'tool.paths', 'tool.lock', 'tool.migrate',
}
BUNDLE_RESOURCE_IDS = {
    'meta.bundle', 'doc.bundle_readme', *SKILLS, 'reference.director',
    'reference.compiler', 'reference.production', 'template.project_parameters',
    'template.segment_check',
}


class WorkflowError(ValueError):
    def __init__(self, code: str, message: str, **details: Any):
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass(frozen=True)
class WorkflowLayout:
    root: Path
    bundle_root: Path
    workflow_id: str
    bundle_id: str
    resources: dict[str, Path]
    rule_version: str = "3.5"
    infrastructure_version: str = "1.0"


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in items:
        if key in result:
            raise WorkflowError("MANIFEST_DUPLICATE_KEY", f"JSON 键重复：{key}")
        result[key] = value
    return result


def json_bytes(data: Any) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def parse_json(raw: bytes, *, label: str = 'JSON') -> dict[str, Any]:
    def reject_constant(value):
        raise WorkflowError('JSON_NONFINITE', f'非法 JSON 数值：{value}')
    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            reject_constant(value)
        return number
    try:
        data = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_pairs,
                          parse_constant=reject_constant, parse_float=finite_float)
    except WorkflowError:
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        raise WorkflowError("MANIFEST_UNREADABLE", f"无法读取 JSON：{label}: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkflowError("MANIFEST_INVALID", f"JSON 顶层必须是对象：{label}")
    return data


def read_json(path: Path) -> dict[str, Any]:
    reject_links(path)
    try:
        return parse_json(path.read_bytes(), label=str(path))
    except OSError as exc:
        raise WorkflowError('MANIFEST_UNREADABLE', f'无法读取 JSON：{path}: {exc}') from exc


def _reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError as exc:
        raise WorkflowError("PATH_UNREADABLE", f"无法检查路径：{path}: {exc}") from exc
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def reject_links(path: Path) -> None:
    """拒绝现有链路中的 symlink、Windows junction 和其他重解析点。"""
    absolute = Path(os.path.abspath(path))
    for part in (absolute, *absolute.parents):
        if part.exists() or part.is_symlink():
            if _reparse(part):
                raise WorkflowError("PATH_LINK_REJECTED", f"拒绝链接或重解析点：{part}")


def _directory(path: Path) -> Path:
    reject_links(path)
    if not path.is_dir():
        raise WorkflowError("PATH_NOT_DIRECTORY", f"目录不存在：{path}")
    return path.resolve()


def _resource(base: Path, value: Any, resource_id: str) -> Path:
    if not isinstance(value, dict) or set(value) != {"path", "required"} or value.get("required") is not True:
        raise WorkflowError("MANIFEST_INVALID", f"资源定义无效：{resource_id}")
    rel = value["path"]
    if (not isinstance(rel, str) or not rel or "\\" in rel or PurePosixPath(rel).is_absolute()
            or PureWindowsPath(rel).drive or any(part in {"", ".", ".."} for part in rel.split("/"))):
        raise WorkflowError("RESOURCE_PATH_INVALID", f"资源路径越界或无效：{resource_id}: {rel}")
    path = base.joinpath(*rel.split("/"))
    reject_links(path)
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise WorkflowError("RESOURCE_PATH_INVALID", f"资源路径越界：{resource_id}") from exc
    if not path.is_file():
        raise WorkflowError("RESOURCE_MISSING", f"必需文件缺失或不是文件：{resource_id}: {path}")
    try:
        with path.open("rb") as stream:
            stream.read(1)
    except OSError as exc:
        raise WorkflowError("RESOURCE_UNREADABLE", f"资源无法读取：{resource_id}: {exc}") from exc
    return path


def _manifest(data: dict[str, Any], schema: str, path: Path) -> None:
    if data.get("schema") != schema:
        raise WorkflowError("MANIFEST_SCHEMA", f"清单 schema 错误：{path}")
    for key in ("workflow_id", "resources"):
        if key not in data:
            raise WorkflowError("MANIFEST_INVALID", f"清单缺少 {key}：{path}")
    if not isinstance(data["resources"], dict) or not data["resources"]:
        raise WorkflowError("MANIFEST_INVALID", f"资源表为空或类型错误：{path}")
    if any(not isinstance(k, str) or not k for k in data["resources"]):
        raise WorkflowError("MANIFEST_INVALID", f"资源 ID 为空：{path}")
    if data["workflow_id"] != WORKFLOW_ID:
        raise WorkflowError("WORKFLOW_ID_MISMATCH", f"工作流身份不符：{path}")


def _skill_name(path: Path) -> str:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if not lines or lines[0].strip() != "---":
        raise WorkflowError("SKILL_NAME_MISMATCH", f"Skill 前置 name 缺失：{path}")
    names = [line[5:].strip().strip('"\'') for line in lines[1:20] if line.startswith("name:")]
    if "---" not in lines[1:20] or len(names) != 1:
        raise WorkflowError("SKILL_NAME_MISMATCH", f"Skill 前置 name 无效：{path}")
    return names[0]


def load_layout(root: Path) -> WorkflowLayout:
    root = _directory(Path(root))
    root_file = root / "workflow.manifest.json"
    if not root_file.is_file():
        raise WorkflowError("WORKFLOW_NOT_FOUND", f"缺少工作流标识：{root_file}")
    root_data = read_json(root_file)
    _manifest(root_data, "JM-workflow-manifest-v1", root_file)
    if not ROOT_RESOURCE_IDS <= root_data['resources'].keys():
        raise WorkflowError('RESOURCE_MISSING', f"根清单缺少固定资源 ID：{sorted(ROOT_RESOURCE_IDS - root_data['resources'].keys())}")
    bundle_spec = root_data.get("bundle")
    if (not isinstance(bundle_spec, dict) or bundle_spec.get("bundle_id") != BUNDLE_ID
            or bundle_spec.get("discovery") != "direct_children"):
        raise WorkflowError("MANIFEST_INVALID", "包发现声明无效")
    for key in ("rule_version", "infrastructure_version"):
        if not isinstance(root_data.get(key), str) or not root_data[key]:
            raise WorkflowError("MANIFEST_INVALID", f"{key} 无效")
    bundles = []
    try:
        children = list(root.iterdir())
    except OSError as exc:
        raise WorkflowError('PATH_UNREADABLE', f'无法列出公共目录：{root}: {exc}') from exc
    for child in children:
        if child.name in EXCLUDED or not child.is_dir():
            continue
        reject_links(child)
        marker = child / "bundle.manifest.json"
        if not marker.exists():
            continue
        bundle_data = read_json(marker)
        if bundle_data.get("bundle_id") == BUNDLE_ID:
            _manifest(bundle_data, "JM-bundle-manifest-v1", marker)
            bundles.append((child, bundle_data))
    if len(bundles) != 1:
        code = "BUNDLE_MISSING" if not bundles else "BUNDLE_AMBIGUOUS"
        raise WorkflowError(code, f"Skill 包数量应为 1，实际 {len(bundles)}", candidates=[str(x[0]) for x in bundles])
    bundle_root, bundle_data = bundles[0]
    if not BUNDLE_RESOURCE_IDS <= bundle_data['resources'].keys():
        raise WorkflowError('RESOURCE_MISSING', f"包清单缺少固定资源 ID：{sorted(BUNDLE_RESOURCE_IDS - bundle_data['resources'].keys())}")
    if bundle_data.get("bundle_id") != BUNDLE_ID:
        raise WorkflowError("BUNDLE_ID_MISMATCH", "Skill 包身份不符")
    resources = {}
    for base, data in ((root, root_data), (bundle_root, bundle_data)):
        for rid, spec in data["resources"].items():
            if isinstance(spec, dict) and isinstance(spec.get('path'), str) and spec['path'].split('/')[0] in EXCLUDED:
                raise WorkflowError('RESOURCE_PATH_INVALID', f'维护或缓存目录不可登记为运行资源：{rid}')
            if rid in resources:
                raise WorkflowError("RESOURCE_ID_DUPLICATE", f"根/包资源 ID 重复：{rid}")
            resources[rid] = _resource(base, spec, rid)
    expected = set(SKILLS) | {"meta.workflow", "meta.bundle"}
    if not expected <= resources.keys():
        raise WorkflowError("RESOURCE_MISSING", f"清单缺少固定资源 ID：{sorted(expected - resources.keys())}")
    for rid, name in SKILLS.items():
        if _skill_name(resources[rid]) != name:
            raise WorkflowError("SKILL_NAME_MISMATCH", f"Skill name 不符：{rid}")
    return WorkflowLayout(root, bundle_root, WORKFLOW_ID, BUNDLE_ID, resources,
                          root_data["rule_version"], root_data["infrastructure_version"])


def discover_from_tool(tool_path: Path) -> WorkflowLayout:
    path = Path(tool_path).absolute()
    reject_links(path)
    for parent in (path.parent, *path.parents):
        marker = parent / "workflow.manifest.json"
        if marker.exists():
            return load_layout(parent)
    raise WorkflowError("WORKFLOW_NOT_FOUND", f"工具祖先目录无标识：{path}")


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def read_binding(project_dir: Path) -> dict[str, Any]:
    project = _directory(Path(project_dir))
    path = project / "工作流绑定.json"
    if not path.is_file():
        raise WorkflowError("BINDING_MISSING", f"项目未迁移，缺少绑定：{path}")
    data = read_json(path)
    if (data.get("schema") != "JM-workflow-binding-v1" or data.get("workflow_id") != WORKFLOW_ID
            or data.get("bundle_id") != BUNDLE_ID or type(data.get("max_depth")) is not int
            or data["max_depth"] not in (0, 1) or not isinstance(data.get("search_roots"), list)
            or not data["search_roots"] or any(not isinstance(x, str) or not x for x in data["search_roots"])
            or data.get("path_hint") is not None and not isinstance(data["path_hint"], str)):
        raise WorkflowError("BINDING_INVALID", f"绑定内容无效：{path}")
    return data


def make_binding(project_dir: Path, layout: WorkflowLayout,
                 *, search_roots: list[Path] | None = None) -> dict[str, Any]:
    project = Path(os.path.abspath(project_dir))
    reject_links(project)
    scopes = search_roots if search_roots is not None else [project.parent, layout.root.parent]
    roots = []
    seen = set()
    for value in scopes:
        scope = Path(value)
        if not scope.is_absolute():
            scope = project / scope
        scope = _directory(Path(os.path.abspath(scope)))
        if search_roots is None and (scope == Path(scope.anchor) or scope == Path.home().resolve()
                                     or str(scope).startswith('\\\\')):
            raise WorkflowError('SEARCH_SCOPE_REQUIRED', f'特殊父范围需显式 --search-root 授权：{scope}')
        key = _path_key(scope)
        if key in seen:
            continue
        seen.add(key)
        try:
            root = os.path.relpath(scope, project).replace('\\', '/')
        except ValueError:
            root = str(scope)
        roots.append(root)
    if not roots:
        raise WorkflowError('BINDING_INVALID', '搜索范围不能为空')
    if not any(_path_key(layout.root) == k or _path_key(layout.root.parent) == k for k in seen):
        raise WorkflowError('BINDING_INVALID', '选定公共库不在声明的浅层范围内')
    return {'schema': 'JM-workflow-binding-v1', 'workflow_id': layout.workflow_id,
            'bundle_id': layout.bundle_id, 'search_roots': roots, 'max_depth': 1,
            'path_hint': str(layout.root)}


def discover_from_project(project_dir: Path, *, explicit_common: Path | None = None) -> WorkflowLayout:
    project = _directory(Path(project_dir))
    binding = read_binding(project)
    if explicit_common is not None:
        return load_layout(explicit_common)
    roots = []
    declared = []
    for value in binding["search_roots"]:
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = project / candidate
        reject_links(candidate)
        declared.append(str(candidate))
        if candidate.is_dir():
            roots.append(candidate.resolve())
    hint = binding.get("path_hint")
    if hint:
        hinted = Path(hint)
        if not hinted.is_absolute():
            hinted = project / hinted
        # 先比较词法边界，不对范围外的提示调用 exists/resolve/read。
        hinted = Path(os.path.abspath(hinted))
        for scope in roots:
            valid = os.path.normcase(str(hinted)) == os.path.normcase(str(scope)) or (
                binding['max_depth'] == 1 and os.path.normcase(str(hinted.parent)) == os.path.normcase(str(scope)))
            if valid:
                reject_links(hinted)
                if hinted.exists():
                    marker = hinted / "workflow.manifest.json"
                    if marker.is_file():
                        data = read_json(marker)
                        if data.get("workflow_id") != WORKFLOW_ID:
                            raise WorkflowError("WORKFLOW_ID_MISMATCH", f"位置提示指向另一工作流：{hinted}")
    candidates: dict[str, Path] = {}
    checked = []
    for scope in roots:
        locations = [scope]
        if binding["max_depth"] == 1:
            try:
                locations.extend(p for p in scope.iterdir() if p.is_dir() and p.name not in EXCLUDED)
            except OSError as exc:
                raise WorkflowError('PATH_UNREADABLE', f'无法列出搜索范围：{scope}: {exc}') from exc
        for candidate in locations:
            reject_links(candidate)
            checked.append(str(candidate))
            marker = candidate / "workflow.manifest.json"
            if not marker.exists():
                continue
            data = read_json(marker)
            if data.get("workflow_id") == WORKFLOW_ID:
                _manifest(data, "JM-workflow-manifest-v1", marker)
                candidates[_path_key(candidate)] = candidate.resolve()
    if not candidates:
        raise WorkflowError("WORKFLOW_NOT_FOUND", "声明范围内未找到公共工作流", checked=checked, declared=declared)
    if len(candidates) > 1:
        raise WorkflowError("WORKFLOW_AMBIGUOUS", "发现多份相同身份的工作流", candidates=[str(p) for p in candidates.values()])
    return load_layout(next(iter(candidates.values())))


def resource_path(layout: WorkflowLayout, resource_id: str) -> Path:
    try:
        return layout.resources[resource_id]
    except KeyError as exc:
        raise WorkflowError("RESOURCE_ID_UNKNOWN", f"未知资源 ID：{resource_id}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("doctor", "list-resources", "resolve"))
    parser.add_argument("resource_id", nargs="?")
    parser.add_argument("--project", type=Path)
    parser.add_argument("--common", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        layout = (discover_from_project(args.project, explicit_common=args.common) if args.project
                  else load_layout(args.common) if args.common else discover_from_tool(Path(__file__)))
        result: dict[str, Any] = {"ok": True, "workflow_root": str(layout.root),
                                  "bundle_root": str(layout.bundle_root), "issues": [],
                                  "lock_status": "not_requested", "ready_for_project_execution": False}
        exit_code = 0
        if args.project:
            try:
                from workflow_lock import read_lock, verify_lock
                check = verify_lock(layout, read_lock(Path(args.project) / "工作流版本锁.json"))
                result.update(lock_status="passed" if check["ok"] else "changed",
                              ready_for_project_execution=check["ok"], issues=check["issues"])
                if not check["ok"]:
                    result["ok"] = False
                    exit_code = 3
            except WorkflowError as exc:
                result.update(ok=False, lock_status=exc.code, issues=[str(exc)])
                exit_code = 3
        if args.command == "list-resources":
            result["resources"] = {rid: str(path) for rid, path in sorted(layout.resources.items())}
        if args.command == "resolve":
            if not args.resource_id:
                raise WorkflowError("ARGUMENT_REQUIRED", "resolve 需要资源 ID")
            result.update(resource_id=args.resource_id, path=str(resource_path(layout, args.resource_id)))
    except WorkflowError as exc:
        result = {"ok": False, "code": exc.code, "issues": [str(exc)], "details": exc.details,
                  "workflow_root": None, "bundle_root": None, "lock_status": "not_checked",
                  "ready_for_project_execution": False}
        exit_code = 2
    if args.json and hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else result)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
