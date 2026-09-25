"""资源 ID 与原始字节 SHA-256 版本锁；读取、构造和核验本身不写盘。"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

try:
    from .workflow_paths import WorkflowError, WorkflowLayout, read_json
except ImportError:
    from workflow_paths import WorkflowError, WorkflowLayout, read_json


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise WorkflowError("RESOURCE_UNREADABLE", f"无法计算文件哈希：{path}: {exc}") from exc
    return digest.hexdigest()


def read_lock(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise WorkflowError("LOCK_MISSING", f"版本锁缺失，需迁移审查：{path}")
    data = read_json(path)
    if data.get("schema") != "JM-workflow-lock-v2":
        raise WorkflowError("LOCK_LEGACY", f"旧版或未知版本锁，需迁移审查：{path}")
    return data


def make_lock(layout: WorkflowLayout) -> dict[str, Any]:
    resources = {}
    for rid, path in sorted(layout.resources.items()):
        base = layout.bundle_root if path == layout.bundle_root or layout.bundle_root in path.parents else layout.root
        resources[rid] = {"sha256": sha256_file(path), "path_hint": path.relative_to(base).as_posix()}
    return {"schema": "JM-workflow-lock-v2", "workflow_id": layout.workflow_id,
            "bundle_id": layout.bundle_id, "rule_version": layout.rule_version,
            "infrastructure_version": layout.infrastructure_version, "hash_algorithm": "sha256",
            "workflow_path_hint": str(layout.root), "bundle_path_hint": str(layout.bundle_root),
            "resources": resources}


def verify_lock(layout: WorkflowLayout, lock_data: dict[str, Any]) -> dict[str, Any]:
    if lock_data.get("schema") != "JM-workflow-lock-v2":
        raise WorkflowError("LOCK_LEGACY", "旧版或未知版本锁需要迁移审查")
    if (lock_data.get("workflow_id") != layout.workflow_id or lock_data.get("bundle_id") != layout.bundle_id
            or lock_data.get("hash_algorithm") != "sha256"):
        raise WorkflowError("LOCK_INVALID", "版本锁身份或哈希算法不符")
    old = lock_data.get("resources")
    if not isinstance(old, dict):
        raise WorkflowError("LOCK_INVALID", "版本锁资源表无效")
    current = make_lock(layout)
    actual = current["resources"]
    changed = []
    diffs = {}
    for rid in sorted(set(old) & set(actual)):
        item = old[rid]
        if not isinstance(item, dict) or not isinstance(item.get("sha256"), str) or len(item["sha256"]) != 64:
            raise WorkflowError("LOCK_INVALID", f"版本锁哈希格式无效：{rid}")
        if item["sha256"].lower() != actual[rid]["sha256"]:
            changed.append(rid)
            diffs[rid] = {"old": item["sha256"], "new": actual[rid]["sha256"]}
    missing = sorted(set(old) - set(actual))
    added = sorted(set(actual) - set(old))
    versions = [k for k in ("rule_version", "infrastructure_version") if lock_data.get(k) != current[k]]
    issues = ([f"内容变化：{', '.join(changed)}"] if changed else [])
    if missing:
        issues.append(f"原锁资源现已缺失：{', '.join(missing)}")
    if added:
        issues.append(f"新增资源尚未接受：{', '.join(added)}")
    if versions:
        issues.append(f"版本字段变化：{', '.join(versions)}")
    return {"ok": not issues, "issues": issues, "location_changed":
            lock_data.get("workflow_path_hint") != str(layout.root) or
            lock_data.get("bundle_path_hint") != str(layout.bundle_root),
            "changed_resources": changed, "missing_resources": missing,
            "added_resources": added, "resource_diffs": diffs, "version_diffs": versions}
