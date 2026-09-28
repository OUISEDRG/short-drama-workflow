import base64
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from support import ROOT, copy_workflow, initialize, snapshot


class PortableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.common = copy_workflow(self.base / '母版 with spaces')
        spec = importlib.util.spec_from_file_location('portable_test_module', ROOT / 'maintenance/portable.py')
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.home = self.base / 'other user' / '.codex'

    def test_install_preserves_existing_and_repeat_is_noop(self):
        self.home.mkdir(parents=True)
        old = b'\xef\xbb\xbf# Personal\r\nKeep this exactly.\r\n'
        (self.home / 'AGENTS.md').write_bytes(old)
        result = self.mod.install(self.common, self.home)
        content = (self.home / 'AGENTS.md').read_bytes()
        self.assertTrue(content.startswith(old))
        before = snapshot(self.home)
        self.assertFalse(self.mod.install(self.common, self.home)['changed'])
        self.assertEqual(before, snapshot(self.home))
        self.assertTrue(self.mod.check(self.common, self.home)['ok'])
        self.mod.restore(self.home, Path(result['backup']))
        self.assertEqual((self.home / 'AGENTS.md').read_bytes(), old)

    def test_move_install_and_synthetic_project(self):
        self.mod.install(self.common, self.home)
        target = self.base / 'new machine' / 'renamed common'
        target.parent.mkdir()
        shutil.move(str(self.common), target)
        self.mod.install(target, self.home)
        text = (self.home / 'AGENTS.md').read_text(encoding='utf-8')
        self.assertIn(str(target), text)
        self.assertNotIn(str(self.common), text)
        project = Path(initialize(target.parent, 'Synthetic', common_root=target)['project'])
        report = self.mod.check(target, self.home, project)
        self.assertTrue(report['ok'], report)
        self.assertTrue(report['project']['lock_ok'])

    def test_override_blocks_without_writes(self):
        self.home.mkdir(parents=True)
        (self.home / 'AGENTS.override.md').write_text('active override', encoding='utf-8')
        before = snapshot(self.home)
        with self.assertRaises(ValueError):
            self.mod.install(self.common, self.home)
        self.assertEqual(before, snapshot(self.home))

    def test_malformed_and_modified_managed_block_fail_closed(self):
        self.home.mkdir(parents=True)
        path = self.home / 'AGENTS.md'
        path.write_text(self.mod.START, encoding='utf-8')
        with self.assertRaises(ValueError):
            self.mod.install(self.common, self.home)
        path.write_bytes(b'')
        self.mod.install(self.common, self.home)
        path.write_bytes(path.read_bytes().replace(b'skill.adapter', b'CUSTOM.rule'))
        before = snapshot(self.home)
        with self.assertRaises(ValueError):
            self.mod.install(self.common, self.home)
        self.assertEqual(before, snapshot(self.home))

    def test_restore_refuses_later_user_edits(self):
        result = self.mod.install(self.common, self.home)
        path = self.home / 'AGENTS.md'
        path.write_bytes(path.read_bytes() + b'\nLater user rule\n')
        before = snapshot(self.home)
        with self.assertRaises(ValueError):
            self.mod.restore(self.home, Path(result['backup']))
        self.assertEqual(before, snapshot(self.home))

    def test_restore_new_file_and_tampered_backup(self):
        result = self.mod.install(self.common, self.home)
        backup = Path(result['backup'])
        data = json.loads(backup.read_text(encoding='utf-8'))
        bad = dict(data, before_base64=base64.b64encode(b'tampered').decode())
        backup.write_text(json.dumps(bad), encoding='utf-8')
        with self.assertRaises(ValueError):
            self.mod.restore(self.home, backup)
        backup.write_text(json.dumps(data), encoding='utf-8')
        self.mod.restore(self.home, backup)
        self.assertFalse((self.home / 'AGENTS.md').exists())

    def test_project_paths_are_readonly_and_old_root_proposes_candidate(self):
        project = self.base / 'moved project'
        project.mkdir()
        (project / '剧本').mkdir()
        (project / '剧本/script.md').write_text('facts', encoding='utf-8')
        (project / '项目参数.json').write_text(json.dumps({
            'project': {'root': r'Z:\Old\Drama'},
            'script': {'fact_source': r'Z:\Old\Drama\剧本\script.md'},
            'assets': {'authorized_local_files': [r'Z:\external\missing.png']}
        }, ensure_ascii=False), encoding='utf-8')
        before = snapshot(project)
        report = self.mod.audit_project(project)
        self.assertFalse(report['lock_ok'])
        record = next(x for x in report['paths'] if x['field'] == 'script.fact_source')
        self.assertEqual(record['candidate'], str(project / '剧本/script.md'))
        self.assertTrue(record['candidate_exists'])
        self.assertEqual(before, snapshot(project))

    def test_lock_drift_is_not_automatically_accepted(self):
        self.mod.install(self.common, self.home)
        project = Path(initialize(self.base, 'Drama', common_root=self.common)['project'])
        lock = (project / '工作流版本锁.json').read_bytes()
        (self.common / 'README.md').write_bytes((self.common / 'README.md').read_bytes() + b'\nchanged')
        report = self.mod.check(self.common, self.home, project)
        self.assertFalse(report['ok'])
        self.assertFalse(report['project']['lock_ok'])
        self.assertEqual(lock, (project / '工作流版本锁.json').read_bytes())

    def test_missing_home_check_does_not_create(self):
        self.assertFalse(self.mod.check(self.common, self.home)['ok'])
        self.assertFalse(self.home.exists())

    def test_missing_project_parameters_blocks_even_when_lock_matches(self):
        self.mod.install(self.common, self.home)
        project = Path(initialize(self.base, 'Incomplete', common_root=self.common)['project'])
        (project / '项目参数.json').unlink()
        before = snapshot(project)
        result = self.mod.check(self.common, self.home, project)
        self.assertFalse(result['ok'])
        self.assertTrue(result['project']['lock_ok'])
        self.assertTrue(result['project']['issues'])
        self.assertEqual(before, snapshot(project))

    def test_codex_home_precedence(self):
        with patch.dict(os.environ, {'CODEX_HOME': str(self.home)}):
            self.assertEqual(self.mod.default_home(), self.home)

    def test_atomic_failure_preserves_existing(self):
        self.home.mkdir(parents=True)
        path = self.home / 'AGENTS.md'
        path.write_bytes(b'old user rules')
        with patch.object(self.mod.os, 'replace', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                self.mod.install(self.common, self.home)
        self.assertEqual(path.read_bytes(), b'old user rules')


if __name__ == '__main__':
    unittest.main()
