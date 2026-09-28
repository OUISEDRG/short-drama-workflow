"""Portable Codex entry installation and read-only project relocation audit. Python 3.10+."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.workflow_paths import load_layout, discover_from_project, reject_links, read_json
from tools.workflow_lock import read_lock, verify_lock

START = '<!-- JUMENG-PORTABLE START -->'
END = '<!-- JUMENG-PORTABLE END -->'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def default_home():
    value = os.environ.get('CODEX_HOME')
    return Path(value).expanduser().absolute() if value else Path.home() / '.codex'


def block(root):
    layout = load_layout(root)
    template = root / 'maintenance/AGENTS.global.template.md'
    reject_links(template)
    body = template.read_text(encoding='utf-8-sig').replace('{{WORKFLOW_ROOT}}', str(layout.root))
    body = body.replace('{{LOCATOR_SHA256}}', sha(layout.resources['tool.paths'].read_bytes()))
    raw = body.rstrip().encode('utf-8') + b'\n'
    return (START + '\n<!-- payload-sha256: ' + sha(raw) + ' -->\n').encode() + raw + END.encode()


def replace_block(old, new):
    start, end = START.encode(), END.encode()
    if start not in old and end not in old:
        return old + (b'\n\n' if old else b'') + new + b'\n'
    if old.count(start) != 1 or old.count(end) != 1:
        raise ValueError('Managed block markers are duplicated or incomplete')
    a, b = old.index(start), old.index(end)
    if b < a:
        raise ValueError('Managed block order is invalid')
    existing = old[a:b + len(end)]
    match = re.fullmatch(rb'<!-- JUMENG-PORTABLE START -->\n<!-- payload-sha256: ([a-f0-9]{64}) -->\n(.*)<!-- JUMENG-PORTABLE END -->', existing, re.S)
    if not match or sha(match[2]).encode() != match[1]:
        raise ValueError('Managed block was edited; preserve it and review before reinstalling')
    return old[:a] + new + old[b + len(end):]


def atomic_write(path, data, expected):
    reject_links(path)
    current = path.read_bytes() if path.exists() else None
    if current != expected:
        raise ValueError('Destination changed concurrently')
    fd, temporary = tempfile.mkstemp(prefix='.jumeng-', dir=path.parent)
    tmp = Path(temporary)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if (path.read_bytes() if path.exists() else None) != expected:
            raise ValueError('Destination changed before replacement')
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def install(root, home):
    root, home = Path(root).absolute(), Path(home).absolute()
    reject_links(home)
    override = home / 'AGENTS.override.md'
    reject_links(override)
    if override.exists() and override.read_text(encoding='utf-8-sig').strip():
        raise ValueError('Non-empty AGENTS.override.md shadows AGENTS.md; review override first')
    target = home / 'AGENTS.md'
    reject_links(target)
    before = target.read_bytes() if target.exists() else None
    after = replace_block(before or b'', block(root))
    if after == before:
        return {'ok': True, 'changed': False, 'entry': str(target)}
    home.mkdir(parents=True, exist_ok=True)
    backups = home / 'jumeng-entry-backups'
    reject_links(backups)
    backups.mkdir(exist_ok=True)
    backup = backups / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8] + '.json')
    record = {'schema': 'JM-portable-backup-v1', 'home': str(home), 'entry': str(target),
              'before_exists': before is not None, 'before_base64': base64.b64encode(before or b'').decode(),
              'before_sha256': sha(before or b''), 'after_sha256': sha(after),
              'created_at': datetime.now(timezone.utc).isoformat()}
    with backup.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
    atomic_write(target, after, before)
    return {'ok': True, 'changed': True, 'entry': str(target), 'backup': str(backup),
            'workflow_root': str(root), 'new_session_verification_required': True}


def restore(home, backup):
    home, backup = Path(home).absolute(), Path(backup).absolute()
    reject_links(home)
    reject_links(backup)
    if backup.parent != home / 'jumeng-entry-backups':
        raise ValueError('Backup must belong to this Codex home')
    data = read_json(backup)
    target = home / 'AGENTS.md'
    reject_links(target)
    if data.get('schema') != 'JM-portable-backup-v1' or data.get('home') != str(home) or data.get('entry') != str(target):
        raise ValueError('Backup identity mismatch')
    old = base64.b64decode(data['before_base64'], validate=True)
    if sha(old) != data['before_sha256'] or (data['before_exists'] is False and old):
        raise ValueError('Backup bytes fail checksum')
    current = target.read_bytes()
    if sha(current) != data['after_sha256']:
        raise ValueError('Entry has later edits; refusing to overwrite')
    if data['before_exists'] is True:
        atomic_write(target, old, current)
    elif data['before_exists'] is False:
        target.unlink()
    else:
        raise ValueError('Invalid before_exists')
    return {'ok': True, 'restored': str(target)}


def audit_project(project):
    project = Path(project).absolute()
    reject_links(project)
    result = {'root': str(project), 'lock_ok': False, 'paths': [], 'issues': [],
              'coverage': '项目参数.json中的绝对路径；未扫描剧本正文或任意软件工程内路径',
              'production_ready': False}
    try:
        layout = discover_from_project(project)
        checked = verify_lock(layout, read_lock(project / '工作流版本锁.json'))
        result.update(lock_ok=checked['ok'], workflow_root=str(layout.root))
        result['issues'].extend(checked['issues'])
    except (OSError, ValueError) as exc:
        result['issues'].append(str(exc))
    params_file = project / '项目参数.json'
    if not params_file.is_file():
        result['issues'].append('项目参数.json missing; existing project needs explicit migration')
        return result
    params = read_json(params_file)
    old_root = params.get('project', {}).get('root')

    def walk(value, field=''):
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, (field + '.' if field else '') + key)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, field + '[' + str(index) + ']')
        elif isinstance(value, str) and (PureWindowsPath(value).is_absolute() or Path(value).is_absolute()):
            hint = field in ('project.root', 'project.common_root')
            exists = Path(value).exists()
            record = {'field': field, 'path': value, 'exists': exists, 'historical_hint': hint}
            if old_root and not hint:
                try:
                    relative = PureWindowsPath(value).relative_to(PureWindowsPath(old_root))
                    if '..' not in relative.parts:
                        candidate = project.joinpath(*relative.parts)
                        reject_links(candidate)
                        record.update(candidate=str(candidate), candidate_exists=candidate.exists())
                except ValueError:
                    pass
            record['needs_review'] = not hint and (not exists or (record.get('candidate_exists', False) and str(Path(value)) != record['candidate']))
            result['paths'].append(record)
    walk(params)
    result['path_review_required'] = any(x['needs_review'] for x in result['paths'])
    return result


def check(root, home, project=None):
    root, home = Path(root).absolute(), Path(home).absolute()
    issues = []
    result = {'ok': False, 'workflow_root': str(root), 'codex_home': str(home),
              'python': sys.version.split()[0], 'codex_cli_found': bool(shutil.which('codex')),
              'desktop_discovery_verified': False, 'browser_login_verified': False,
              'platform_actions': False, 'issues': issues}
    try:
        expected = block(root)
        target = home / 'AGENTS.md'
        reject_links(target)
        raw = target.read_bytes() if target.exists() else b''
        if replace_block(raw, expected) != raw:
            issues.append('Codex entry absent or points to another installation; run install')
        override = home / 'AGENTS.override.md'
        reject_links(override)
        if override.exists() and override.read_text(encoding='utf-8-sig').strip():
            issues.append('AGENTS.override.md shadows this entry')
        if sys.version_info < (3, 10):
            issues.append('Python 3.10+ required')
        if project:
            result['project'] = audit_project(project)
            if not result['project']['lock_ok'] or result['project'].get('path_review_required') or result['project']['issues']:
                issues.append('Project binding, content lock or paths require review; no files changed')
    except (OSError, ValueError) as exc:
        issues.append(str(exc))
    result['ok'] = not issues
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('install', 'check', 'restore'))
    parser.add_argument('--codex-home', type=Path)
    parser.add_argument('--project', type=Path)
    parser.add_argument('--backup', type=Path)
    args = parser.parse_args()
    home = args.codex_home or default_home()
    try:
        if args.command == 'install':
            result = install(ROOT, home)
        elif args.command == 'check':
            result = check(ROOT, home, args.project)
        else:
            if not args.backup:
                raise ValueError('restore requires --backup')
            result = restore(home, args.backup)
    except (OSError, ValueError, KeyError) as exc:
        result = {'ok': False, 'issues': [str(exc)], 'platform_actions': False}
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
