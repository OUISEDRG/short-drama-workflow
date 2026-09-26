from support import *
from unittest.mock import patch
from tools.workflow_paths import read_json


class InitTests(Sandbox):
    def test_A14_F5_bad_ledger_zero_write(self):
        self.layout.resources['template.ledger'].write_bytes(b'{broken')
        with self.assertRaises(ValueError):
            initialize(self.space, '坏台账项目', common_root=self.common)
        self.assertFalse((self.space / '坏台账项目').exists())

    def test_A13_missing_resources_zero_write(self):
        for rid in ('skill.director', 'reference.compiler', 'template.project_parameters'):
            path = self.layout.resources[rid]; raw = path.read_bytes(); path.unlink()
            try:
                with self.subTest(rid=rid), self.assertRaises(WorkflowError) as caught:
                    initialize(self.space, '缺资源剧', common_root=self.common)
                self.assertIn(rid, str(caught.exception))
                self.assertFalse((self.space / '缺资源剧').exists())
            finally:
                path.write_bytes(raw)

    def test_A14_bad_json_structures_and_existing_gap(self):
        ledger = self.layout.resources['template.ledger']
        original = ledger.read_bytes()
        project = self.project()
        (project / '制作台账.json').unlink()
        for raw in (b'{"schema":"JM-ledger-v1","segments":{}}', b'{"schema":"wrong","segments":[]}', b'{"segments":NaN}'):
            ledger.write_bytes(raw)
            before = snapshot(project)
            with self.subTest(raw=raw), self.assertRaises(WorkflowError):
                initialize(self.space, project.name, common_root=self.common)
            self.assertEqual(before, snapshot(project))
        ledger.write_bytes(original)
        params = self.layout.resources['template.project_parameters']
        params.write_bytes(b'{"schema":"JM-v3.5","project":{},"project":{}}')
        with self.assertRaises(WorkflowError):
            initialize(self.space, '重复参数键', common_root=self.common)
        self.assertFalse((self.space / '重复参数键').exists())

    def test_A15_reinitialize_preserves_business_bytes(self):
        project = self.project()
        params = json.loads((project / '项目参数.json').read_bytes())
        params['script']['main_language'] = 'es'; params['decisions'] = [{'custom': '合成裁决'}]
        (project / '项目参数.json').write_bytes(encoded(params))
        (project / '人物' / '合成标记.txt').write_bytes(b'synthetic')
        before = snapshot(project)
        result = initialize(self.space, project.name, common_root=self.common)
        self.assertEqual(len(result['preserved']), 6)
        self.assertEqual(before, snapshot(project))
        self.assertEqual(len(list(project.iterdir())), 13)

    def test_A16_existing_missing_binding_or_lock(self):
        project = self.project()
        for name in ('工作流绑定.json', '工作流版本锁.json'):
            path = project / name; raw = path.read_bytes(); path.unlink()
            before = snapshot(project)
            self.assertCode('MIGRATION_REQUIRED', initialize, self.space, project.name, common_root=self.common)
            self.assertEqual(before, snapshot(project)); path.write_bytes(raw)
        path = project / '工作流版本锁.json'; path.write_bytes(encoded({'schema': 'JM-workflow-lock-v1', 'files': {}}))
        self.assertCode('LOCK_LEGACY', initialize, self.space, project.name, common_root=self.common)

    def test_A17_reserved_internal_and_junction(self):
        for name in ('CON', 'LPT1.txt', '../x', 'trail.', 'a/b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                initialize(self.space, name, common_root=self.common)
        with self.assertRaises(ValueError):
            initialize(self.common, '内部项目', common_root=self.common)
        target = self.space / 'actual'; target.mkdir()
        link = self.space / 'link'
        proc = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(link), str(target)], capture_output=True)
        self.assertEqual(proc.returncode, 0)
        try:
            self.assertCode('PATH_LINK_REJECTED', initialize, link, '链接项目', common_root=self.common)
        finally:
            os.rmdir(link)
        self.assertFalse((target / '链接项目').exists())

    def test_A18_write_failure_limited_recovery(self):
        real_open = Path.open
        def faulty(path, mode='r', *args, **kwargs):
            if mode == 'xb' and path.name == 'AGENTS.md':
                raise OSError('synthetic write failure')
            return real_open(path, mode, *args, **kwargs)
        with patch.object(Path, 'open', faulty):
            self.assertCode('INITIALIZE_IO_FAILED', initialize, self.space, '失败项目', common_root=self.common)
        self.assertFalse((self.space / '失败项目').exists())

    def test_A18_external_change_survives_recovery(self):
        real_open = Path.open
        project = self.space / '外部修改项目'
        def faulty(path, mode='r', *args, **kwargs):
            if mode == 'xb' and path.name == 'AGENTS.md':
                (project / '项目启动说明.md').write_bytes(b'user concurrent edit')
                raise OSError('synthetic failure after external edit')
            return real_open(path, mode, *args, **kwargs)
        with patch.object(Path, 'open', faulty):
            self.assertCode('INITIALIZE_IO_FAILED', initialize, self.space, project.name, common_root=self.common)
        self.assertEqual((project / '项目启动说明.md').read_bytes(), b'user concurrent edit')
