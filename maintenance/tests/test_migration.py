from support import *
from tools import migrate_workflow as m
from tools.workflow_lock import read_lock, verify_lock
from tools.workflow_paths import discover_from_project
from unittest.mock import patch


class MigrationTests(Sandbox):
    def test_custom_absolute_path_with_standard_suffix_is_blocked(self):
        original = json.loads(self.layout.resources['template.project_parameters'].read_bytes())
        original['authorities']['skills']['ai-short-drama-director'] = {
            'path': 'D:/CustomRules/ai-short-drama-director/SKILL.md', 'review_note': 'preserve'}
        raw = encoded(original)
        self.assertCode('PARAMETERS_MERGE_REVIEW_REQUIRED', m.merge_parameters,
            raw, self.layout.resources['template.project_parameters'].read_bytes(), common_root=self.common)
        self.assertEqual(raw, encoded(original))

    def test_custom_string_section_is_not_normalized_away(self):
        original = json.loads(self.layout.resources['template.project_parameters'].read_bytes())
        original['authorities']['content'] = 'sd25-video-prompt-compiler/references/视频模型工作流配置_SD2.5_v3.4.md#9.3'
        self.assertCode('PARAMETERS_MERGE_REVIEW_REQUIRED', m.merge_parameters,
            encoded(original), self.layout.resources['template.project_parameters'].read_bytes(), common_root=self.common)

    def test_real_legacy_lock_without_schema_can_be_planned(self):
        project = self.historical_project('legacy-3.5-noschema')
        old = json.loads((project / '工作流版本锁.json').read_bytes())
        self.assertNotIn('schema', old)
        before = snapshot(project)
        spec = m.plan(project, self.common)
        self.assertEqual(before, snapshot(project))
        self.assertFalse(spec['blockers'], spec['blockers'])
        self.assertEqual(spec['source_lock_format'], 'legacy-3.5-noschema')
        self.assertEqual(len(spec['legacy_mapping']), len(old['files']))

    def test_v1_0_default_agents_can_upgrade(self):
        original = (FIXTURES / 'infrastructure-1.0' / 'AGENTS.project.template.md').read_bytes()
        result = m.merge_agents(original, self.layout.resources['template.project_agents'].read_bytes())
        self.assertIn(m.BLOCK_START.encode(), result)

    def test_custom_same_filename_different_parent_is_blocked_without_writes(self):
        cases = [
            ('skills', 'ai-short-drama-director', {'path': 'custom/ai-short-drama-director/SKILL.md'}),
            ('skills', 'ai-short-drama-director', {'path': '/custom/ai-short-drama-director/SKILL.md'}),
            ('skills', 'ai-short-drama-director', 'custom/ai-short-drama-director/SKILL.md'),
            (None, 'content', 'custom/视频模型工作流配置_SD2.5_v3.4.md#7.3'),
            (None, 'content', 'custom/sd25-video-prompt-compiler/references/视频模型工作流配置_SD2.5_v3.4.md#7.3'),
            (None, 'layout', 'custom/视频提示词输出规范_资产全名版.md#24'),
            (None, 'platform_content', 'custom/dreamina-sd25-prompt-adapter/SKILL.md'),
        ]
        for index, (nested, key, value) in enumerate(cases):
            with self.subTest(value=value):
                project = self.project(name='自定义来源-' + str(index))
                path = project / '项目参数.json'
                data = json.loads(path.read_bytes())
                target = data['authorities'][nested] if nested else data['authorities']
                target[key] = value
                path.write_bytes(encoded(data))
                before = snapshot(project)
                spec = m.plan(project, self.common)
                self.assertTrue(any('PARAMETERS_MERGE_REVIEW_REQUIRED' in x for x in spec['blockers']))
                self.assertEqual(before, snapshot(project))
                self.assertCode('MIGRATION_BLOCKED', self.approve, project, spec)
                self.assertEqual(before, snapshot(project))

    def test_custom_fragment_variants_are_blocked(self):
        content = 'sd25-video-prompt-compiler/references/视频模型工作流配置_SD2.5_v3.4.md'
        cases = [('content', content + '#9.3'), ('content', content),
                 ('content', content + '#7.3#9.3'),
                 ('content', {'path': content}),
                 ('content', {'path': content + '#9.3', 'section': '7.3'}),
                 ('layout', '视频提示词输出规范_资产全名版.md#23'),
                 ('platform_content', 'dreamina-sd25-prompt-adapter/SKILL.md#9'),
                 ('content', {'path': content, 'section': '9.3'})]
        template = self.layout.resources['template.project_parameters'].read_bytes()
        for key, value in cases:
            with self.subTest(key=key, value=value):
                data = json.loads(template)
                data['authorities'][key] = value
                raw = encoded(data)
                self.assertCode('PARAMETERS_MERGE_REVIEW_REQUIRED', m.merge_parameters,
                    raw, template, common_root=self.common)
                self.assertEqual(raw, encoded(data))

    def test_exact_historical_authorities_strings_and_objects_can_migrate(self):
        template = self.layout.resources['template.project_parameters'].read_bytes()
        old_template = (FIXTURES / 'legacy-3.5-noschema' / '项目参数.template.json').read_bytes()
        for object_form in (False, True):
            with self.subTest(object_form=object_form):
                data = json.loads(old_template)
                data['project']['custom_note'] = '保留未知项目字段'
                data['custom_top'] = ['保留', 1]
                data['authorities']['project_private'] = {'path': 'project-only.md'}
                if object_form:
                    targets = [data['authorities']['skills'], data['authorities']]
                    for target in targets:
                        for key, value in list(target.items()):
                            if not isinstance(value, str):
                                continue
                            path, separator, section = value.partition('#')
                            target[key] = {'path': path.replace('/', '\\'), 'review_note': '保留附加说明'}
                            if separator:
                                target[key]['section'] = section
                original = json.loads(encoded(data))
                updated = json.loads(m.merge_parameters(encoded(data), template, common_root=self.common))
                self.assertEqual(updated['custom_top'], original['custom_top'])
                self.assertEqual(updated['project']['custom_note'], original['project']['custom_note'])
                self.assertEqual(updated['authorities']['project_private'], original['authorities']['project_private'])
                expected = json.loads(template)['authorities']
                for key, value in expected.items():
                    if key == 'skills':
                        for skill, authority in value.items():
                            self.assertEqual(updated['authorities']['skills'][skill]['resource_id'], authority['resource_id'])
                    else:
                        for field, desired in value.items():
                            self.assertEqual(updated['authorities'][key][field], desired)
                if object_form:
                    self.assertEqual(updated['authorities']['content']['review_note'], '保留附加说明')

    def test_real_legacy_lock_approval_apply_and_backups(self):
        project = self.historical_project('legacy-3.5-noschema')
        originals = {p.name: p.read_bytes() for p in project.iterdir() if p.is_file()}
        before = snapshot(project)
        spec = m.plan(project, self.common)
        self.assertFalse(spec['blockers'], spec['blockers'])
        self.assertEqual(spec['operation'], 'legacy_migration')
        self.assertTrue(spec['requires_content_upgrade_review'])
        self.assertTrue(spec['changed_resources'])
        self.assertTrue(spec['added_resources'])
        self.assertEqual(before, snapshot(project))
        path = self.space / 'not-approved-plan.json'
        path.write_bytes(encoded(spec))
        self.assertCode('MIGRATION_APPROVAL_MISMATCH', m.apply, project, path, 'f' * 64)
        self.assertEqual(before, snapshot(project))
        result = self.approve(project, spec)
        for name, raw in originals.items():
            self.assertEqual((Path(result['backup']) / name).read_bytes(), raw)
        self.assertTrue(verify_lock(discover_from_project(project), read_lock(project / '工作流版本锁.json'))['ok'])

    def test_unknown_schema_less_json_is_not_trusted(self):
        source = json.loads((FIXTURES / 'legacy-3.5-noschema' / '工作流版本锁.json').read_bytes())
        variants = [{'files': source['files']}, {'other': 'not a historical lock'},
            {**source, 'workflow_version': '3.4'}, {**source, 'workflow_version': 3.5},
            {**source, 'common_root': None}, {**source, 'common_root': ['unexpected']},
            {**source, 'common_root': 'relative/public'}, {**source, 'files': []},
            {**source, 'files': {}}, {**source, 'schema': None},
            {**source, 'schema': 'unknown'}, {**source, 'unexpected_field': 'unpublished format'}]
        for index, data in enumerate(variants):
            with self.subTest(index=index):
                project = self.historical_project('legacy-3.5-noschema', name='无schema异常-' + str(index))
                (project / '工作流版本锁.json').write_bytes(encoded(data))
                before = snapshot(project)
                spec = m.plan(project, self.common)
                self.assertTrue(spec['blockers'])
                self.assertEqual(before, snapshot(project))
                self.assertCode('MIGRATION_BLOCKED', self.approve, project, spec)
                self.assertEqual(before, snapshot(project))

    def test_real_legacy_bad_hash_unknown_duplicate_and_traversal_are_blocked(self):
        source = json.loads((FIXTURES / 'legacy-3.5-noschema' / '工作流版本锁.json').read_bytes())
        entry = next(x for x in source['files'] if 'ai-short-drama-director' in x and x.endswith('SKILL.md'))
        cases = []
        for invalid_hash in ('a' * 63, 'g' * 64, 12, None):
            cases.append({**source['files'], entry: invalid_hash})
        cases.extend([
            {**source['files'], 'project-private.md': 'a' * 64},
            {**source['files'], entry.replace('\\', '/'): source['files'][entry]},
            {**source['files'], '../' + entry.replace('\\', '/'): source['files'][entry]},
            {**source['files'], 'custom/' + entry.replace('\\', '/'): source['files'][entry]},
            {**source['files'], 'D:/CustomRules/' + entry.replace('\\', '/'): source['files'][entry]},
            {k: v for k, v in source['files'].items() if k != entry},
        ])
        for index, files in enumerate(cases):
            with self.subTest(index=index):
                project = self.historical_project('legacy-3.5-noschema', name='旧锁非法资源-' + str(index))
                (project / '工作流版本锁.json').write_bytes(encoded({**source, 'files': files}))
                before = snapshot(project)
                spec = m.plan(project, self.common)
                self.assertTrue(spec['blockers'])
                self.assertEqual(before, snapshot(project))
                self.assertCode('MIGRATION_BLOCKED', self.approve, project, spec)
                self.assertEqual(before, snapshot(project))

    def test_real_v1_0_project_end_to_end_upgrade(self):
        project = self.historical_project('infrastructure-1.0')
        params_path = project / '项目参数.json'
        params = json.loads(params_path.read_bytes())
        params['script']['main_language'] = 'synthetic-language'
        params['custom_top'] = {'keep': 'unknown business setting'}
        params['decisions'] = [{'source': 'synthetic-user', 'scope': 'test', 'value': 'keep'}]
        params_path.write_bytes(encoded(params))
        originals = {p.name: p.read_bytes() for p in project.iterdir() if p.is_file()}
        before = snapshot(project)
        old_lock = json.loads(originals['工作流版本锁.json'])
        self.assertEqual(old_lock['infrastructure_version'], '1.0')
        self.assertEqual(len(old_lock['resources']), 26)
        self.assertNotIn(m.BLOCK_START.encode(), originals['AGENTS.md'])
        spec = m.plan(project, self.common)
        self.assertFalse(spec['blockers'], spec['blockers'])
        self.assertEqual(spec['operation'], 'content_upgrade')
        self.assertIn('infrastructure_version', spec['version_diffs'])
        self.assertIn('AGENTS.md', spec['control_changes'])
        self.assertTrue(spec['requires_content_upgrade_review'])
        self.assertEqual(before, snapshot(project))
        result = self.approve(project, spec)
        for name in result['written']:
            if name in originals:
                self.assertEqual((Path(result['backup']) / name).read_bytes(), originals[name])
        updated_params = json.loads(params_path.read_bytes())
        self.assertEqual(updated_params, params)
        self.assertIn(m.BLOCK_START.encode(), (project / 'AGENTS.md').read_bytes())
        resolved = discover_from_project(project)
        self.assertEqual(resolved.root, self.common)
        self.assertTrue(verify_lock(resolved, read_lock(project / '工作流版本锁.json'))['ok'])
        self.assertTrue(m.plan(project, self.common)['no_op'])

    def test_real_historical_projects_upgrade_after_both_outer_names_change(self):
        self.layout.bundle_root.rename(self.layout.bundle_root.with_name('任意 中文 技能 包'))
        renamed_common = self.common.with_name('任意 中文 公共 工作流')
        self.common.rename(renamed_common)
        self.common = renamed_common
        self.layout = load_layout(self.common)
        for case, count in (('legacy-3.5-noschema', 20), ('infrastructure-1.0', 26)):
            with self.subTest(case=case):
                project = self.historical_project(case, name='双改名历史项目-' + case)
                original_lock = (project / '工作流版本锁.json').read_bytes()
                before = snapshot(project)
                spec = m.plan(project, self.common)
                self.assertFalse(spec['blockers'], spec['blockers'])
                self.assertEqual(before, snapshot(project))
                self.assertTrue(spec['requires_content_upgrade_review'])
                self.assertTrue(spec['changed_resources'])
                if case == 'legacy-3.5-noschema':
                    self.assertEqual(spec['source_lock_format'], 'legacy-3.5-noschema')
                    self.assertEqual(len(spec['legacy_mapping']), count)
                    self.assertEqual(spec['operation'], 'legacy_migration')
                else:
                    self.assertEqual(len(json.loads(original_lock)['resources']), count)
                    self.assertEqual(spec['operation'], 'content_upgrade')
                    self.assertIn('infrastructure_version', spec['version_diffs'])
                result = self.approve(project, spec)
                self.assertEqual((Path(result['backup']) / '工作流版本锁.json').read_bytes(), original_lock)
                resolved = discover_from_project(project)
                self.assertEqual(resolved.root, self.common)
                self.assertEqual(resolved.bundle_root.name, '任意 中文 技能 包')
                self.assertTrue(verify_lock(resolved, read_lock(project / '工作流版本锁.json'))['ok'])


    def test_v1_0_agents_preserves_custom_outside_bytes(self):
        source = (FIXTURES / 'infrastructure-1.0' / 'AGENTS.project.template.md').read_bytes()
        paragraphs = source.split(b'\n\n')
        historical_block = paragraphs[1] + b'\n\n' + paragraphs[2]
        template = self.layout.resources['template.project_agents'].read_bytes()
        a, b = m._block(template)
        for newline in (b'\n', b'\r\n'):
            with self.subTest(newline=newline):
                old = source.replace(b'\n', newline)
                old_block = historical_block.replace(b'\n', newline)
                prefix = b'\xef\xbb\xbf' + '用户自定义前言\r\n保留空行\r\n\r\n'.encode()
                suffix = '\r\n用户尾部说明：不得覆盖字节\r\n'.encode()
                original = prefix + old + suffix
                expected = original.replace(old_block, template[a:b])
                self.assertEqual(m.merge_agents(original, template), expected)
                project = self.historical_project('infrastructure-1.0', name='旧入口字节-' + str(len(newline)))
                (project / 'AGENTS.md').write_bytes(original)
                spec = m.plan(project, self.common)
                self.assertFalse(spec['blockers'], spec['blockers'])
                result = self.approve(project, spec)
                self.assertEqual((project / 'AGENTS.md').read_bytes(), expected)
                self.assertEqual((Path(result['backup']) / 'AGENTS.md').read_bytes(), original)

    def test_v1_0_agents_internal_changes_duplicates_and_conflicts_block(self):
        source = (FIXTURES / 'infrastructure-1.0' / 'AGENTS.project.template.md').read_bytes()
        variants = [source.replace(b'common_root', b'custom_root', 1),
                    source.replace('唯一身份'.encode(), '默认全部信任'.encode(), 1),
                    source + source,
                    source + b'\ncommon_root=D:/CustomRules\n',
                    source + b'\nworkflow_paths.py from custom tool\n',
                    source + b'\nworkflow.manifest.json from custom location\n',
                    source + '\n通用工作流目录：custom\n'.encode(),
                    source + m.BLOCK_START.encode()]
        template = self.layout.resources['template.project_agents'].read_bytes()
        for index, raw in enumerate(variants):
            with self.subTest(index=index):
                self.assertCode('AGENTS_MERGE_REVIEW_REQUIRED', m.merge_agents, raw, template)
                project = self.historical_project('infrastructure-1.0', name='旧入口阻塞-' + str(index))
                (project / 'AGENTS.md').write_bytes(raw)
                before = snapshot(project)
                spec = m.plan(project, self.common)
                self.assertTrue(any('AGENTS_MERGE_REVIEW_REQUIRED' in x for x in spec['blockers']))
                self.assertCode('MIGRATION_BLOCKED', self.approve, project, spec)
                self.assertEqual(before, snapshot(project))


    def test_A23_F2_unknown_authorities_preserved(self):
        old = json.loads(self.layout.resources['template.project_parameters'].read_text(encoding='utf-8-sig'))
        old['custom_top'] = [1, 2]
        old['project']['custom_project'] = 17
        old['authorities']['custom_rule'] = {'must_keep': True}
        old['authorities']['skills']['custom_skill'] = {'custom_resource': 'project.local'}
        old['authorities']['skills']['ai-short-drama-director']['review_note'] = '保留'
        if hasattr(m, 'merge_parameters'):
            result = m.merge_parameters(encoded(old), self.layout.resources['template.project_parameters'].read_bytes(), common_root=self.common)
        else:
            result = m._parameters_update(encoded(old), self.layout)
        new = json.loads(result)
        self.assertEqual(new['custom_top'], old['custom_top'])
        self.assertEqual(new['project']['custom_project'], 17)
        self.assertEqual(new['authorities'], old['authorities'])

    def test_A25_F3_reversed_markers_blocked(self):
        source = (m.BLOCK_END + '\nold\n' + m.BLOCK_START).encode()
        with self.assertRaises(WorkflowError):
            if hasattr(m, 'merge_agents'):
                m.merge_agents(source, self.layout.resources['template.project_agents'].read_bytes())
            else:
                m._agents_update(source)

    def test_A27_F4_cleared_blockers_recomputed(self):
        project = self.legacy()
        old = json.loads((project / '工作流版本锁.json').read_bytes())
        old['files']['unknown-private-rule.md'] = 'a' * 64
        (project / '工作流版本锁.json').write_bytes(encoded(old))
        spec = m.plan(project, self.common)
        self.assertTrue(spec['blockers'])
        spec['blockers'] = []
        before = snapshot(project)
        self.assertCode('MIGRATION_BLOCKED', self.approve, project, spec)
        self.assertEqual(before, snapshot(project))

    def test_A22_legacy_mapping_backup_and_upgrade(self):
        project = self.legacy()
        original = (project / '工作流版本锁.json').read_bytes()
        spec = m.plan(project, self.common)
        self.assertFalse(spec['blockers'])
        self.assertEqual(len(spec['legacy_mapping']), len(self.layout.resources))
        result = self.approve(project, spec)
        self.assertEqual((Path(result['backup']) / '工作流版本锁.json').read_bytes(), original)
        self.assertTrue(verify_lock(self.layout, read_lock(project / '工作流版本锁.json'))['ok'])

    def test_A24_custom_authority_conflicts(self):
        for value in ({'resource_id': 'project.custom'}, {'path': 'my-custom.md'}, {'resource_id': 'reference.compiler', 'section': 'custom'}):
            original = json.loads(self.layout.resources['template.project_parameters'].read_bytes())
            original['authorities']['content'] = value
            with self.subTest(value=value):
                self.assertCode('PARAMETERS_MERGE_REVIEW_REQUIRED', m.merge_parameters,
                    encoded(original), self.layout.resources['template.project_parameters'].read_bytes(), common_root=self.common)

    def test_A25_all_broken_block_forms(self):
        start, end = m.BLOCK_START.encode(), m.BLOCK_END.encode()
        template = self.layout.resources['template.project_agents'].read_bytes()
        for raw in (start, end, start+start+end+end, start+end+start+end, end+start):
            with self.subTest(raw=raw):
                self.assertCode('AGENTS_MERGE_REVIEW_REQUIRED', m.merge_agents, raw, template)

    def test_A26_block_outside_bytes_and_authority_template(self):
        template = self.layout.resources['template.project_agents'].read_bytes()
        a,b = m._block(template); block = template[a:b]
        prefix, suffix = '用户自定义要求\r\n'.encode(), '\r\n其他边界\r\n'.encode()
        original = prefix + m.BLOCK_START.encode() + b'\nold\n' + m.BLOCK_END.encode() + suffix
        self.assertEqual(m.merge_agents(original, template), prefix+block+suffix)
        self.assertEqual(m.merge_agents(None, template), template)

    def test_A28_project_public_and_binding_stale(self):
        for target in ('项目参数.json', '工作流绑定.json', 'public'):
            project = self.project(name='合成剧-' + target)
            spec = m.plan(project, self.common)
            if target == 'public':
                path = self.layout.resources['doc.readme']
            else:
                path = project / target
            path.write_bytes(path.read_bytes()+b'\n')
            before = snapshot(project)
            self.assertCode('MIGRATION_PLAN_STALE', self.approve, project, spec)
            self.assertEqual(before, snapshot(project))

    def test_A29_digest_and_arbitrary_targets(self):
        project = self.legacy(); spec = m.plan(project, self.common)
        path = self.space/'plan.json'; path.write_bytes(encoded(spec))
        before = snapshot(project)
        self.assertCode('MIGRATION_APPROVAL_MISMATCH', m.apply, project, path, 'f'*64)
        spec['control_changes']['../danger.md'] = {}
        self.assertCode('MIGRATION_PLAN_INVALID', self.approve, project, spec)
        self.assertEqual(before, snapshot(project))
        del spec['control_changes']['../danger.md']; spec['operation'] = 'invented'
        self.assertCode('MIGRATION_PLAN_STALE', self.approve, project, spec)

    def test_A30_v2_content_upgrade(self):
        project = self.project()
        path = self.layout.resources['doc.readme']; path.write_bytes(path.read_bytes()+b'\nupdated')
        before_lock = (project / '工作流版本锁.json').read_bytes()
        spec = m.plan(project, self.common)
        self.assertEqual(spec['operation'], 'content_upgrade')
        self.assertEqual(spec['changed_resources'], ['doc.readme'])
        self.assertTrue(spec['requires_content_upgrade_review'])
        result = self.approve(project, spec)
        self.assertEqual((Path(result['backup'])/'工作流版本锁.json').read_bytes(), before_lock)
        self.assertTrue(verify_lock(load_layout(self.common),read_lock(project/'工作流版本锁.json'))['ok'])

    def test_A31_rebind_and_noop(self):
        project = self.project()
        spec = m.plan(project,self.common); before = snapshot(project)
        self.assertEqual(spec['operation'],'no_op')
        self.assertTrue(self.approve(project,spec)['no_op'])
        self.assertEqual(before,snapshot(project))
        original_lock = (project/'工作流版本锁.json').read_bytes()
        renamed = self.common.with_name('公共重命名'); self.common.rename(renamed)
        spec = m.plan(project,renamed)
        self.assertEqual(spec['operation'],'rebind')
        self.assertFalse(spec['requires_content_upgrade_review'])
        result = self.approve(project,spec)
        self.assertNotIn('工作流版本锁.json',result['written'])
        self.assertEqual(original_lock,(project/'工作流版本锁.json').read_bytes())
        self.assertTrue(m.plan(project,renamed)['no_op'])

    def test_A32_repeat_apply_no_duplicate_backup(self):
        project=self.legacy(); spec=m.plan(project,self.common)
        self.approve(project,spec); before=snapshot(project)
        self.assertCode('MIGRATION_PLAN_STALE',self.approve,project,spec)
        self.assertEqual(before,snapshot(project))

    def test_A32_write_failure_restores_owned_bytes(self):
        project=self.legacy(); spec=m.plan(project,self.common); before={n:(project/n).read_bytes() for n in m.CONTROL}
        real_replace=m.os.replace; calls=[]
        def faulty(source,target):
            calls.append(target)
            if len(calls)==2: raise OSError('synthetic replace failure')
            return real_replace(source,target)
        with patch.object(m.os,'replace',faulty):
            self.assertCode('MIGRATION_IO_FAILED',self.approve,project,spec)
        self.assertEqual(before,{n:(project/n).read_bytes() for n in m.CONTROL})
        self.assertFalse(list(project.glob('.workflow-stage-*')))
        self.assertTrue(list(project.glob('_workflow_migration_backups/*/recovery.json')))

    def test_A32_external_change_not_overwritten_on_recovery(self):
        project=self.legacy(); spec=m.plan(project,self.common)
        real_replace=m.os.replace; calls=[]
        def faulty(source,target):
            calls.append(target)
            if len(calls)==2:
                (project/'AGENTS.md').write_bytes(b'new user edit')
                raise OSError('synthetic second replace failure')
            return real_replace(source,target)
        with patch.object(m.os,'replace',faulty):
            self.assertCode('MIGRATION_IO_FAILED',self.approve,project,spec)
        self.assertEqual((project/'AGENTS.md').read_bytes(),b'new user edit')

    def test_missing_unknown_lock_and_removed_resource_blocked(self):
        project=self.project(); path=project/'工作流版本锁.json'; path.unlink()
        self.assertIn('LOCK_MISSING',m.plan(project,self.common)['blockers'])
        path.write_bytes(encoded({'schema':'unknown','files':{}}))
        self.assertIn('LOCK_SCHEMA_UNKNOWN',m.plan(project,self.common)['blockers'])
        old=make_lock(self.layout);old['resources']['removed.rule']={'sha256':'a'*64,'path_hint':'old.md'}
        path.write_bytes(encoded(old))
        self.assertTrue(m.plan(project,self.common)['blockers'])
