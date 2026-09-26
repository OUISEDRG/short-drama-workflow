"""只在 TemporaryDirectory 中构造公共副本和合成项目。"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'maintenance' / 'tests' / 'fixtures'
sys.path.insert(0, str(ROOT))
from tools.workflow_paths import load_layout, WorkflowError
from tools.init_project import initialize
from tools.workflow_lock import make_lock


def encoded(data):
    return (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def copy_workflow(target, source=ROOT):
    layout = load_layout(source)
    for path in layout.resources.values():
        dest = target / path.relative_to(source)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())
    for name in ('README.md', 'CHANGELOG.md', 'maintain.py'):
        path = source / 'maintenance' / name
        if path.is_file():
            dest = target / 'maintenance' / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(path.read_bytes())
    for path in (source / 'maintenance' / 'tests').glob('*.py'):
        dest = target / 'maintenance' / 'tests' / path.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())
    for path in (source / 'maintenance' / 'tests' / 'fixtures').rglob('*'):
        if path.is_file():
            dest = target / path.relative_to(source)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(path.read_bytes())
    if (source / '.gitignore').is_file():
        (target / '.gitignore').write_bytes((source / '.gitignore').read_bytes())
    return target


def snapshot(root):
    return {p.relative_to(root).as_posix(): digest(p.read_bytes())
            for p in root.rglob('*') if p.is_file()}


def cli(script, *args, cwd=None):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
    return subprocess.run([sys.executable, '-B', str(script), *map(str, args)],
                          cwd=cwd, env=env, capture_output=True, text=True, encoding='utf-8')


def valid_segment():
    return {'schema': 'JM-segment-check-v1', 'segment_id': 'synthetic-1', 'segment_number': 1,
            'main_language': 'es', 'duration_seconds': 4, 'time_source': {'kind': 'user', 'seconds': 4},
            'source_review': dict.fromkeys(('dialogue', 'narration', 'visible_text'), 'confirmed'),
            'has_independent_voice_reference': False, 'character_attached_audio_preserved': True,
            'screen_text_mode': 'direct_generation', 'shots': [{'id': 's1', 'number': 1, 'start': 0,
            'end': 4, 'transition_in': 'start'}], 'source_dialogue': {}, 'source_dialogue_meta': {},
            'dialogue_events': [], 'source_narration': {}, 'narration_coverage': [],
            'visible_text': [], 'asset_bindings': []}


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='jm-maintenance-')
        self.addCleanup(self.temp.cleanup)
        self.space = Path(self.temp.name)
        self.common = copy_workflow(self.space / '公共 中文 空格')
        self.layout = load_layout(self.common)

    def project(self, name='合成剧', parent=None):
        parent = parent or self.space
        parent.mkdir(parents=True, exist_ok=True)
        return Path(initialize(parent, name, common_root=self.common)['project'])

    def legacy(self):
        project = self.project()
        data = {'schema': 'JM-workflow-lock-v1', 'files': {
            p.relative_to(self.common).as_posix(): digest(p.read_bytes())
            for p in self.layout.resources.values()}}
        (project / '工作流版本锁.json').write_bytes(encoded(data))
        (project / 'AGENTS.md').write_bytes('通用工作流目录：历史默认位置\n用户要求保留\n'.encode('utf-8'))
        return project

    def historical_project(self, case, name='历史合成项目'):
        """使用持久历史控制样本；不调用当前或历史 initialize。"""
        source = FIXTURES / case
        project = self.space / name
        project.mkdir()
        params = json.loads((source / '项目参数.template.json').read_bytes())
        params['project'].update(name=name, root=str(project), common_root=str(self.common))
        (project / '项目参数.json').write_bytes(encoded(params))
        agents = (source / 'AGENTS.project.template.md').read_bytes()
        (project / 'AGENTS.md').write_bytes(agents.replace(b'{{COMMON_ROOT}}', str(self.common).encode()))
        for target in ('工作流版本锁.json', '工作流绑定.json'):
            if (source / target).is_file():
                (project / target).write_bytes((source / target).read_bytes())
        return project

    def assertCode(self, code, func, *args, **kwargs):
        with self.assertRaises(WorkflowError) as caught:
            func(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def approve(self, project, spec):
        from tools.migrate_workflow import apply
        path = self.space / 'plan.json'
        path.write_bytes(encoded(spec))
        return apply(project, path, digest(path.read_bytes()))
