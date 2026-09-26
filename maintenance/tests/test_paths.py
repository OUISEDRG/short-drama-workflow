from support import *
from tools.workflow_paths import discover_from_project, make_binding, read_json, reject_links
from tools.workflow_lock import verify_lock, read_lock
from unittest.mock import patch


class PathsTests(Sandbox):
    def test_A01_bundle_rename_all_resources(self):
        self.layout.bundle_root.rename(self.layout.bundle_root.with_name('新包名'))
        layout = load_layout(self.common)
        self.assertEqual(len(layout.resources), len(self.layout.resources))
        self.assertTrue(all(p.is_file() for p in layout.resources.values()))

    def test_A02_common_rename(self):
        project = self.project()
        renamed = self.common.with_name('改名公共')
        self.common.rename(renamed)
        self.assertEqual(discover_from_project(project).root, renamed)

    def test_A03_both_names_original_lock(self):
        project = self.project()
        old_lock = (project / '工作流版本锁.json').read_bytes()
        self.layout.bundle_root.rename(self.layout.bundle_root.with_name('改名包'))
        renamed = self.common.with_name('改名公共')
        self.common.rename(renamed)
        self.assertTrue(verify_lock(discover_from_project(project), json.loads(old_lock))['ok'])
        self.assertEqual(old_lock, (project / '工作流版本锁.json').read_bytes())

    def test_A04_workspace_move(self):
        container = self.space / 'workspace'
        container.mkdir()
        moved = container / self.common.name
        self.common.rename(moved)
        self.common = moved
        project = self.project(parent=container)
        dest = self.space / '搬家'
        container.rename(dest)
        project = dest / project.name
        self.assertTrue(verify_lock(discover_from_project(project), read_lock(project / '工作流版本锁.json'))['ok'])
    def test_A05_F1_remote_parent_rename(self):
        project = self.project(parent=self.space / 'projects')
        renamed = self.common.with_name('改名后的公共库')
        self.common.rename(renamed)
        self.assertEqual(discover_from_project(project).root, renamed)

    def test_A06_unrelated_cwd_cli(self):
        cwd = self.space / 'unrelated'; cwd.mkdir()
        proc = cli(self.common / 'tools/workflow_paths.py', 'resolve', 'template.project_parameters', '--json', cwd=cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(Path(json.loads(proc.stdout)['path']), self.layout.resources['template.project_parameters'])
        proc = cli(self.common / 'tools/init_project.py', '--root', cwd, '--project-name', 'CLI合成剧', cwd=cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_A07_duplicate_common_and_bundle(self):
        project = self.project()
        duplicate = copy_workflow(self.space / 'duplicate')
        self.assertCode('WORKFLOW_AMBIGUOUS', discover_from_project, project)
        duplicate.rename(self.space / 'maintenance')
        shutil.copytree(self.layout.bundle_root, self.common / '重复包')
        self.assertCode('BUNDLE_AMBIGUOUS', load_layout, self.common)

    def test_A08_explicit_no_fallback(self):
        project = self.project()
        copy_workflow(self.space / 'duplicate')
        self.assertEqual(discover_from_project(project, explicit_common=self.common).root, self.common)
        self.assertCode('PATH_NOT_DIRECTORY', discover_from_project, project, explicit_common=self.space / 'missing')

    def test_A09_hint_boundaries_identity_missing(self):
        project = self.project()
        binding = json.loads((project / '工作流绑定.json').read_bytes())
        outside = self.space / 'outside' / 'wrong'; outside.mkdir(parents=True)
        (outside / 'workflow.manifest.json').write_bytes(b'not-json')
        for hint in (outside, self.space / 'missing'):
            binding['path_hint'] = str(hint)
            (project / '工作流绑定.json').write_bytes(encoded(binding))
            self.assertEqual(discover_from_project(project).root, self.common)
        wrong = self.space / 'wrong'; wrong.mkdir()
        (wrong / 'workflow.manifest.json').write_bytes(encoded({'workflow_id': 'other'}))
        binding['path_hint'] = str(wrong)
        (project / '工作流绑定.json').write_bytes(encoded(binding))
        self.assertCode('WORKFLOW_ID_MISMATCH', discover_from_project, project)

    def test_A10_windows_case_same_directory_dedup(self):
        project = self.project()
        scopes = [self.space, project / '..', Path(str(self.space).upper())]
        binding = make_binding(project, self.layout, search_roots=scopes)
        self.assertEqual(len(binding['search_roots']), 1)
        (project / '工作流绑定.json').write_bytes(encoded(binding))
        self.assertEqual(discover_from_project(project).root, self.common)

    def test_A11_strict_json_manifest(self):
        marker = self.common / 'workflow.manifest.json'
        original = marker.read_bytes()
        marker.write_bytes(b'\xef\xbb\xbf' + original)
        self.assertEqual(load_layout(self.common).root, self.common)
        for raw in (b'{', b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}', b'[]', b'\xff'):
            marker.write_bytes(raw)
            with self.subTest(raw=raw), self.assertRaises(WorkflowError):
                load_layout(self.common)
        for key, value in (('schema','bad'), ('resources', []), ('rule_version', 1)):
            data = json.loads(original); data[key] = value; marker.write_bytes(encoded(data))
            with self.subTest(key=key), self.assertRaises(WorkflowError):
                load_layout(self.common)

    def test_A12_paths_and_real_junction(self):
        marker = self.common / 'workflow.manifest.json'
        original = json.loads(marker.read_bytes())
        for value in ('../outside.md', 'C:/private.md', '//host/share/x', '/x', 'a\\b'):
            data = json.loads(encoded(original)); data['resources']['doc.readme']['path'] = value
            marker.write_bytes(encoded(data))
            self.assertCode('RESOURCE_PATH_INVALID', load_layout, self.common)
        marker.write_bytes(encoded(original))
        # 在本次临时目录中创建真正的 NTFS junction，不模拟重解析点属性。
        link = self.common / 'linked'
        proc = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(link), str(self.space)], capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        try:
            self.assertCode('PATH_LINK_REJECTED', reject_links, link / 'anything')
            self.assertCode('PATH_LINK_REJECTED', load_layout, self.common)
        finally:
            os.rmdir(link)

    def test_A34_maintenance_is_excluded(self):
        project = self.project()
        copy_workflow(self.common / 'maintenance' / 'backups' / 'copy')
        (self.common / 'maintenance' / 'bundle.manifest.json').write_bytes(self.layout.resources['meta.bundle'].read_bytes())
        self.assertEqual(discover_from_project(project).root, self.common)
        self.assertFalse(any('maintenance' in p.relative_to(self.common).parts for p in load_layout(self.common).resources.values()))

    def test_explicit_scope_required_for_drive_root(self):
        with patch('tools.workflow_paths.Path.home', return_value=self.space):
            self.assertCode('SEARCH_SCOPE_REQUIRED', make_binding, self.space / 'project', self.layout)

    def test_explicit_relative_scope_before_project_exists(self):
        result=initialize(self.space,'显式范围项目',common_root=self.common,search_roots=[Path('..')])
        project=Path(result['project'])
        self.assertEqual(discover_from_project(project).root,self.common)
