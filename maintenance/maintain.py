"""标准库维护入口：check 默认只读；release 冻结并验证可复测版本。"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).absolute().parents[1]
sys.path.insert(0, str(ROOT))
from tools.workflow_paths import (WorkflowError, discover_from_tool, load_layout,
                                  read_json, json_bytes, reject_links)
from tools.workflow_lock import make_lock
from tools.init_project import template_content

TEST_FILES = ('support.py', 'test_paths.py', 'test_lock.py', 'test_init.py',
              'test_migration.py', 'test_maintenance.py', 'test_production_contracts.py')
MAINTENANCE_FILES = ('README.md', 'CHANGELOG.md', 'maintain.py')
FIXTURE_FILES = (
    'README.md', 'provenance.json',
    'legacy-3.5-noschema/AGENTS.project.template.md',
    'legacy-3.5-noschema/项目参数.template.json',
    'legacy-3.5-noschema/工作流版本锁.json',
    'infrastructure-1.0/AGENTS.project.template.md',
    'infrastructure-1.0/项目参数.template.json',
    'infrastructure-1.0/工作流版本锁.json',
    'infrastructure-1.0/工作流绑定.json',
    'infrastructure-1.0/workflow.manifest.json',
    'infrastructure-1.0/bundle.manifest.json',
)
PROTECTED = {'layout.final_prompt', 'tool.workflow_check', 'skill.prebreakdown',
             'skill.director', 'skill.acting', 'skill.compiler', 'skill.adapter',
             'skill.production', 'reference.director', 'reference.compiler', 'reference.production'}


def hash_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def aggregate(hashes):
    return hash_bytes(json_bytes(dict(sorted(hashes.items()))))


def source_files(root):
    layout = load_layout(root)
    files = {p.relative_to(root).as_posix(): p for p in layout.resources.values()}
    for name in MAINTENANCE_FILES:
        files['maintenance/' + name] = root / 'maintenance' / name
    for name in TEST_FILES:
        files['maintenance/tests/' + name] = root / 'maintenance/tests' / name
    fixture_root = root / 'maintenance' / 'tests' / 'fixtures'
    for name in FIXTURE_FILES:
        files['maintenance/tests/fixtures/' + name] = fixture_root / name
    files['.gitignore'] = root / '.gitignore'
    for rel, path in files.items():
        reject_links(path)
        if not path.is_file():
            raise WorkflowError('SOURCE_MISSING', f'缺少维护或运行源码：{rel}')
        parts = Path(rel).parts
        if any(x in {'.git', '__pycache__', 'backups', 'releases', 'reports'} for x in parts):
            raise WorkflowError('RELEASE_CONTENT_INVALID', f'禁止归档的资源：{rel}')
    # 未登记的测试源不能悄悄遗漏；新增测试时须扩展发布白名单。
    actual = {p.name for p in (root / 'maintenance' / 'tests').glob('*.py')}
    if actual != set(TEST_FILES):
        raise WorkflowError('TEST_SOURCE_SET_INVALID', f'测试源码白名单不匹配：{sorted(actual)}')
    actual_fixtures = {p.relative_to(fixture_root).as_posix()
                       for p in fixture_root.rglob('*') if p.is_file()}
    if actual_fixtures != set(FIXTURE_FILES):
        raise WorkflowError('TEST_FIXTURE_SET_INVALID', f'历史样本白名单不匹配：{sorted(actual_fixtures)}')
    return files


def hashes(files):
    return {rel: hash_bytes(p.read_bytes()) for rel, p in files.items()}


def run_tests(root):
    # 每次独立解释器装载目标快照的模块，避免 sys.modules 缓存其他副本。
    runner = r'''
import io,json,sys,unittest
from pathlib import Path
root=Path(sys.argv[1]); sys.path.insert(0,str(root/'maintenance'/'tests'))
class Result(unittest.TextTestResult):
    def __init__(self,*a,**k): super().__init__(*a,**k); self.items=[]
    def addSuccess(self,t): super().addSuccess(t); self.items.append({'test':t.id(),'status':'passed'})
    def addFailure(self,t,e): super().addFailure(t,e); self.items.append({'test':t.id(),'status':'failed'})
    def addError(self,t,e): super().addError(t,e); self.items.append({'test':t.id(),'status':'error'})
    def addSkip(self,t,r): super().addSkip(t,r); self.items.append({'test':t.id(),'status':'skipped','reason':r})
suite=unittest.defaultTestLoader.discover(str(root/'maintenance'/'tests'),pattern='test_*.py')
out=io.StringIO(); result=unittest.TextTestRunner(stream=out,verbosity=2,resultclass=Result).run(suite)
print(json.dumps({'tests_run':result.testsRun,'tests_passed':sum(x['status']=='passed' for x in result.items),'failures':len(result.failures),'errors':len(result.errors),'skipped':[{'test':t.id(),'reason':r} for t,r in result.skipped],'test_results':result.items,'test_output':out.getvalue()}))
'''
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
    proc = subprocess.run([sys.executable, '-B', '-c', runner, str(root)], env=env,
                          capture_output=True, encoding='utf-8')
    if proc.returncode:
        raise WorkflowError('TEST_LOAD_FAILED', proc.stderr or proc.stdout)
    return json.loads(proc.stdout)


def local_navigation(files):
    for rel, path in files.items():
        if path.suffix != '.md':
            continue
        text = path.read_text(encoding='utf-8-sig')
        for target in re.findall(r'(?<!!)\[[^\]\n]+\]\(([^)]+)\)', text):
            target = target.split('#')[0].split(' "')[0].strip('<>')
            if not target or '://' in target or target.startswith(('mailto:', 'app:')):
                continue
            dest = path.parent / target
            reject_links(dest)
            if not dest.exists():
                raise WorkflowError('NAVIGATION_BROKEN', f'{rel} 的本地链接不存在：{target}')


def protection_check(root, layout, baseline_path):
    data = read_json(baseline_path)
    if (data.get('schema') != 'JM-maintenance-baseline-v1'
            or not isinstance(data.get('collected_at'), str)
            or not isinstance(data.get('protected_resources'), dict)
            or set(data['protected_resources']) != PROTECTED
            or data.get('excluded_parameter_fields') != []
            or not isinstance(data.get('parameters_business'), dict)):
        raise WorkflowError('BASELINE_INVALID', '基线结构或保护覆盖不符')
    for rid, old_hash in data['protected_resources'].items():
        if not isinstance(old_hash, str) or not re.fullmatch('[0-9a-f]{64}', old_hash):
            raise WorkflowError('BASELINE_INVALID', f'基线哈希无效：{rid}')
        if hash_bytes(layout.resources[rid].read_bytes()) != old_hash:
            raise WorkflowError('PROTECTED_CHANGED', f'受保护原始字节变化：{rid}')
    params = read_json(layout.resources['template.project_parameters'])
    if params != data['parameters_business']:
        raise WorkflowError('PROTECTED_CHANGED', '参数业务字段变化（本次排除字段为空）')


def check(root=ROOT, *, baseline=None):
    root = Path(root).resolve()
    result = {'ok': False, 'scope': 'maintenance', 'runtime_structure_ok': False,
              'lock_status': 'not_requested', 'ready_for_project_execution': False,
              'tests_run': 0, 'tests_passed': 0, 'failures': 0, 'errors': 0, 'skipped': [],
              'not_verified': ['Python 3.10 未实机运行', '跨物理磁盘移动未实测',
                               '无平台、生成或成片验收'],
              'issues': [], 'runtime_digest': None, 'source_digest': None,
              'protection_comparison': 'not_requested' if baseline is None else 'not_completed',
              'python': sys.version, 'os': platform.platform(),
              'checked_at': datetime.now(timezone.utc).isoformat(), 'exit_code': 2}
    try:
        layout = load_layout(root)
        result['runtime_structure_ok'] = True
        files = source_files(root)
        for rel, path in files.items():
            if path.suffix == '.json':
                read_json(path)
            if path.suffix == '.py':
                ast.parse(path.read_text(encoding='utf-8-sig'), filename=rel, feature_version=(3, 10))
        template_content(layout)
        local_navigation(files)
        if baseline is not None:
            protection_check(root, layout, Path(baseline))
            result['protection_comparison'] = 'passed'
        result['runtime_digest'] = aggregate({rid: item['sha256'] for rid, item in make_lock(layout)['resources'].items()})
        result['source_digest'] = aggregate(hashes(files))
        result.update(run_tests(root))
        if result['tests_run'] == 0:
            result['issues'].append('ZERO_TESTS：发现 0 项测试')
        if result['skipped']:
            result['issues'].append('REQUIRED_TEST_SKIPPED：必需测试被跳过')
        result['ok'] = bool(result['tests_run']) and not (result['failures'] or result['errors'] or result['skipped'] or result['issues'])
        result['exit_code'] = 0 if result['ok'] else 3
    except (OSError, ValueError, SyntaxError) as exc:
        result['issues'].append({'code': getattr(exc, 'code', 'CHECK_INPUT_ERROR'), 'message': str(exc)})
    return result


def output_path(root, value, area):
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    reject_links(path)
    path = Path(os.path.abspath(path))
    try:
        path.relative_to(root / 'maintenance' / area)
    except ValueError as exc:
        raise WorkflowError('OUTPUT_OUT_OF_SCOPE', f'输出必须在 maintenance/{area} 内') from exc
    return path


def write_exclusive(path, raw):
    with path.open('xb') as stream:
        stream.write(raw)


def write_report(root, value, result):
    path = output_path(root, value, 'reports')
    if path.exists():
        raise WorkflowError('OUTPUT_EXISTS', f'报告已存在：{path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    owned = False
    try:
        with path.open('xb') as stream:
            owned = True
            stream.write(json_bytes(result))
    except Exception:
        if owned:
            incomplete = path.with_suffix(path.suffix + '.incomplete')
            if not incomplete.exists():
                path.rename(incomplete)
        raise
    return path


def smoke(root):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
    code = r'''
import sys,tempfile,json
from pathlib import Path
sys.path.insert(0,sys.argv[1]); from tools.workflow_paths import load_layout,discover_from_project
from tools.workflow_lock import read_lock,verify_lock
from tools.init_project import initialize
from maintenance.tests.support import valid_segment
from tools.workflow_check import validate_manifest
root=Path(sys.argv[1]); layout=load_layout(root)
renamed_bundle=layout.bundle_root.with_name('已改名技能包'); layout.bundle_root.rename(renamed_bundle)
renamed_root=root.with_name('已改名公共发布'); root.rename(renamed_root)
with tempfile.TemporaryDirectory(prefix='jm-release-project-') as t:
    project=Path(initialize(Path(t),'合成发布冒烟',common_root=renamed_root)['project'])
    layout=discover_from_project(project)
    assert verify_lock(layout,read_lock(project/'工作流版本锁.json'))['ok']
    assert not validate_manifest(valid_segment())
print(json.dumps({'ok':True,'both_outer_renames':True,'new_project':True,'binding':True,'lock':True,'segment_check':True}))
'''
    proc = subprocess.run([sys.executable, '-B', '-c', code, str(root)], env=env,
                          capture_output=True, encoding='utf-8')
    if proc.returncode:
        raise WorkflowError('RELEASE_SMOKE_FAILED', proc.stderr)
    return json.loads(proc.stdout)


def release(root=ROOT, *, output_dir='maintenance/releases', checker=check, smoker=smoke):
    root = Path(root).resolve()
    output = output_path(root, output_dir, 'releases')
    files = source_files(root)
    original = hashes(files)
    layout = load_layout(root)
    name = f'workflow-r{layout.rule_version}-i{layout.infrastructure_version}-{aggregate(original)[:12]}'
    package, record = output / (name + '.zip'), output / (name + '.json')
    if package.exists() or record.exists():
        raise WorkflowError('OUTPUT_EXISTS', f'发布目标已存在：{name}')
    owned = []
    try:
        with tempfile.TemporaryDirectory(prefix='jm-release-') as temp:
            space = Path(temp)
            frozen = space / 'snapshot'
            for rel, path in files.items():
                raw = path.read_bytes()
                if hash_bytes(raw) != original[rel]:
                    raise WorkflowError('RELEASE_SOURCE_CHANGED', f'捕获期间源变化：{rel}')
                dest = frozen / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(raw)
            tested = checker(frozen)
            if not tested.get('ok') or tested.get('tests_run', 0) == 0 or tested.get('skipped'):
                raise WorkflowError('RELEASE_CHECK_FAILED', '冻结快照测试失败或必需测试跳过', result=tested)
            if hashes(source_files(root)) != original or hashes(source_files(frozen)) != original:
                raise WorkflowError('RELEASE_SOURCE_CHANGED', '检查期间来源或冻结快照发生变化')
            temp_zip = space / 'release.zip'
            with zipfile.ZipFile(temp_zip, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
                for rel in sorted(original):
                    archive.writestr(rel, (frozen / rel).read_bytes())
            with zipfile.ZipFile(temp_zip) as archive:
                if archive.testzip() or set(archive.namelist()) != set(original) or len(archive.namelist()) != len(original):
                    raise WorkflowError('RELEASE_ZIP_INVALID', 'ZIP 完整性或内容清单不符')
                for rel in original:
                    if hash_bytes(archive.read(rel)) != original[rel]:
                        raise WorkflowError('RELEASE_ZIP_INVALID', f'包内字节不符：{rel}')
                unpack = space / 'export' / 'unpacked'
                archive.extractall(unpack)
            if hashes(source_files(unpack)) != original:
                raise WorkflowError('RELEASE_ZIP_INVALID', '解包后字节不符')
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
            doctor = subprocess.run([sys.executable, '-B', str(unpack / 'tools' / 'workflow_paths.py'), 'doctor', '--json'],
                                    capture_output=True, encoding='utf-8', env=env)
            if doctor.returncode:
                raise WorkflowError('RELEASE_SMOKE_FAILED', doctor.stderr or doctor.stdout)
            smoke_result = smoker(unpack)
            if not smoke_result.get('ok'):
                raise WorkflowError('RELEASE_SMOKE_FAILED', '解包冒烟未通过')
            if hashes(source_files(root)) != original:
                raise WorkflowError('RELEASE_SOURCE_CHANGED', '发布前来源发生变化')
            zip_raw = temp_zip.read_bytes()
            result = {'ok': True, 'complete': True, 'scope': 'maintenance_release',
                      'rule_version': layout.rule_version, 'infrastructure_version': layout.infrastructure_version,
                      'package': str(package), 'record': str(record), 'zip_sha256': hash_bytes(zip_raw),
                      'files': original, 'runtime_digest': tested['runtime_digest'],
                      'source_digest': aggregate(original), 'check': tested, 'smoke': smoke_result,
                      'doctor': json.loads(doctor.stdout), 'created_at': datetime.now(timezone.utc).isoformat()}
            output.mkdir(parents=True, exist_ok=True)
            # 先在临时区完成所有验证，排他输出；IO 故障仅清理本次拥有的文件。
            for path, raw in ((package, zip_raw), (record, json_bytes(result))):
                with path.open('xb') as stream:
                    owned.append((path, raw))
                    stream.write(raw)
            return result
    except Exception as exc:
        residual = []
        for path, raw in reversed(owned):
            try:
                # 写入失败的文件也标记为 .incomplete，不能冒充完成产物。
                if path.read_bytes() == raw:
                    path.unlink()
                else:
                    incomplete = path.with_suffix(path.suffix + '.incomplete')
                    if incomplete.exists():
                        residual.append(str(path))
                    else:
                        path.rename(incomplete)
                        residual.append(str(incomplete))
            except OSError:
                residual.append(str(path))
        if isinstance(exc, WorkflowError):
            exc.details['residual'] = residual
            raise
        raise WorkflowError('RELEASE_IO_FAILED', f'发布失败：{exc}', residual=residual) from exc


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    c = sub.add_parser('check')
    c.add_argument('--baseline', type=Path)
    c.add_argument('--report', type=Path)
    c.add_argument('--json', action='store_true')
    r = sub.add_parser('release')
    r.add_argument('--output-dir', default='maintenance/releases')
    r.add_argument('--json', action='store_true')
    args = parser.parse_args()
    try:
        root = discover_from_tool(Path(__file__)).root
        if args.command == 'check':
            baseline = (root / args.baseline if args.baseline and not args.baseline.is_absolute() else args.baseline)
            result = check(root, baseline=baseline)
            if args.report:
                write_report(root, args.report, result)
            code = result['exit_code']
        else:
            result = release(root, output_dir=args.output_dir)
            code = 0
    except (OSError, ValueError) as exc:
        result = {'ok': False, 'code': getattr(exc, 'code', 'MAINTENANCE_ERROR'),
                  'issues': [str(exc)], 'details': getattr(exc, 'details', {})}
        code = 3 if result['code'] in ('RELEASE_CHECK_FAILED', 'RELEASE_SMOKE_FAILED', 'RELEASE_SOURCE_CHANGED') else 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
