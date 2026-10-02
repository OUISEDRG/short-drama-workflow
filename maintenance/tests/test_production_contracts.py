from support import *
from tools.workflow_check import validate_manifest
from tools.workflow_paths import discover_from_project
from tools.workflow_lock import verify_lock, read_lock
from tools import migrate_workflow as m
from tools import workflow_check as wc
from decimal import Decimal
from copy import deepcopy
import re


def segment_with_shots(duration, boundaries):
    data = valid_segment()
    data['duration_seconds'] = duration
    data['time_source'] = {'kind': 'user', 'seconds': duration}
    data['shots'] = [{'id': 's' + str(i), 'number': i, 'start': a, 'end': b,
                      'transition_in': 'start' if i == 1 else 'hard_cut'}
                     for i, (a, b) in enumerate(boundaries, 1)]
    return data


def long_dialogue_segment():
    data = segment_with_shots(8, [(0, 2.5), (2.5, 5), (5, 8)])
    data['asset_bindings'] = [{'type': 'character', 'referent': '合成发声者',
                               'full_name': '合成人物_测试状态'}]
    data['source_dialogue'] = {'D01': 'He esperado todo este tiempo para decirte la verdad.'}
    data['source_dialogue_meta'] = {'D01': {'speaker': '合成发声者', 'kind': 'dialogue',
                                          'order': 1, 'source_ref': 'synthetic-script:1'}}
    data['dialogue_events'] = [{'id': 'D01', 'speaker': '合成发声者', 'kind': 'dialogue',
                               'text': data['source_dialogue']['D01'], 'language': 'es',
                               'start': 0, 'end': 8}]
    return data


def supported_prompt(data):
    lines = [f"【生成段{data['segment_number']}｜{data['duration_seconds']}秒】"]
    sections = {'character': '人物引用', 'scene': '场景引用', 'position': '站位图引用', 'prop': '道具引用'}
    for kind, section in sections.items():
        assets = [x for x in data['asset_bindings'] if x['type'] == kind]
        if assets:
            lines.append('【' + section + '】')
            lines.extend(x['referent'] + '@' + x['full_name'] for x in assets)
    lines += ['【风格】', '真人电影，主语言西语，无BGM。', '【场景】', '合成室内，轴线与持物持续。']
    for i, shot in enumerate(data['shots']):
        lines += [f"【{shot['start']}–{shot['end']}s｜镜头{shot['number']}】",
                  '固定近景，展示动作起势。' if i == 0 else '硬切至侧面取景，承接轴线、视线与持物。']
        for event in data['dialogue_events']:
            if shot['start'] <= event['start'] < shot['end']:
                asset = next(x for x in data['asset_bindings'] if x['referent'] == event['speaker'])
                tag = '现场对白' if event['kind'] == 'dialogue' else '画外对白'
                lines.append(f"{tag}〔{event['id']}〕：{event['speaker']}@{asset['full_name']}；原文：“{event['text']}”；时间：{event['start']}–{event['end']}s")
            elif shot['start'] < event['end'] and shot['end'] > event['start']:
                lines.append(f"对白〔{event['id']}〕沿前镜连续到结束位置，不重复原句、不重新发声。")
        for event in data['visible_text']:
            if shot['start'] <= event['start'] < shot['end']:
                lines.append(f"画面文字〔{event['id']}〕：“{event['text']}”；承载面：{event['surface']}；时间：{event['start']}–{event['end']}s")
            elif shot['start'] < event['end'] and shot['end'] > event['start']:
                lines.append(f"画面文字〔{event['id']}〕维持在原承载面，不生成额外文本。")
    if not data['dialogue_events']:
        lines.append('无人声。')
    lines += ['【末态承接】', '保留动作结果与下一段依赖的持物状态。']
    return '\n'.join(lines) + '\n'


class ProductionContracts(Sandbox):
    def assert_prompt_contract_failure(self, data, prompt, expected_codes, manifest_passed=True):
        issues = wc.validate_prompt_against_manifest(data, prompt)
        self.assertTrue(set(expected_codes).issubset({x['code'] for x in issues}), issues)
        path = self.space / 'mismatch.json'; path.write_bytes(encoded(data))
        text = self.space / 'mismatch.md'; text.write_text(prompt, encoding='utf-8')
        proc = cli(self.common / 'tools/workflow_check.py', path, '--prompt', text)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stderr, '')
        result = json.loads(proc.stdout)
        self.assertEqual(result['manifest_passed'], manifest_passed)
        self.assertFalse(result['prompt_consistency_passed'])
        self.assertFalse(result['static_contract_passed'])
        self.assertTrue(set(expected_codes).issubset({x['code'] for x in result['issues']}), result)

    def test_layout_third_shot_text_continuation_is_parseable(self):
        data = long_dialogue_segment()
        data['visible_text'] = [{'id': 'TXT-01', 'text': 'Acceso autorizado', 'language': 'es',
                                 'surface': '门上屏幕', 'start': 0, 'end': 8}]
        original = deepcopy(data)
        layout = self.layout.resources['layout.final_prompt'].read_text(encoding='utf-8-sig')
        third = layout.split('【5.00–8.00s｜镜头3】', 1)[1].split('【末态承接】', 1)[0]
        continuation = [line.strip() for line in third.splitlines() if line.strip().startswith('画面文字〔TXT-01〕')]
        self.assertEqual(len(continuation), 1)
        prompt = supported_prompt(data)
        prefix, third_prompt = prompt.split('【5–8s｜镜头3】', 1)
        third_prompt = re.sub(r'(?m)^画面文字〔TXT-01〕[^\n]*$', lambda _: continuation[0], third_prompt)
        prompt = prefix + '【5–8s｜镜头3】' + third_prompt
        self.assertEqual(validate_manifest(data), [])
        self.assertEqual(wc.validate_prompt_against_manifest(data, prompt), [])
        parsed, issues = wc.parse_prompt(prompt)
        self.assertEqual(issues, [])
        definitions = [x for x in parsed['text'] if not x.get('continuation')]
        self.assertEqual(len(definitions), 1)
        self.assertEqual((definitions[0]['start'], definitions[0]['end']), (Decimal(0), Decimal(8)))
        self.assertEqual(sum(bool(x.get('continuation')) for x in parsed['text']), 2)
        self.assertEqual(data, original)
        path = self.space / 'layout.json'; path.write_bytes(encoded(data))
        text = self.space / 'layout.md'; text.write_text(prompt, encoding='utf-8')
        proc = cli(self.common / 'tools/workflow_check.py', path, '--prompt', text)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(proc.stderr, '')
        result = json.loads(proc.stdout)
        self.assertTrue(result['manifest_passed'])
        self.assertTrue(result['static_contract_passed'])
        self.assertEqual(result['issues'], [])

    def test_prompt_more_shots_than_manifest_returns_json_failure(self):
        data = segment_with_shots(4, [(0, 2), (2, 4)])
        prompt = supported_prompt(segment_with_shots(4, [(0, 1), (1, 2), (2, 4)]))
        self.assert_prompt_contract_failure(data, prompt, ['PROMPT_SHOT_COUNT_MISMATCH'])

    def test_prompt_fewer_shots_than_manifest_returns_json_failure(self):
        data = segment_with_shots(4, [(0, 1), (1, 2), (2, 4)])
        prompt = supported_prompt(segment_with_shots(4, [(0, 2), (2, 4)]))
        self.assert_prompt_contract_failure(data, prompt, ['PROMPT_SHOT_COUNT_MISMATCH'])

    def test_manifest_missing_shots_returns_json_failure(self):
        prompt = supported_prompt(segment_with_shots(4, [(0, 2), (2, 4)]))
        for missing in ('absent', 'empty', 'null'):
            with self.subTest(missing=missing):
                data = segment_with_shots(4, [(0, 2), (2, 4)])
                if missing == 'absent':
                    del data['shots']
                else:
                    data['shots'] = [] if missing == 'empty' else None
                self.assert_prompt_contract_failure(data, prompt, ['PROMPT_SHOT_COUNT_MISMATCH'], manifest_passed=False)

    def test_extra_prompt_shot_above_three_seconds_still_rejected(self):
        data = segment_with_shots(8, [(0, 2.5), (2.5, 5), (5, 8)])
        prompt = supported_prompt(segment_with_shots(8, [(0, 1), (1, 2), (2, 4), (4, 8)]))
        self.assert_prompt_contract_failure(data, prompt, ['PROMPT_SHOT_COUNT_MISMATCH', 'PROMPT_SHOT_TOO_LONG'])

    def test_extra_prompt_shot_is_still_checked_independently(self):
        data = segment_with_shots(4, [(0, 2), (2, 4)])
        prompt = supported_prompt(segment_with_shots(4, [(0, 1), (1, 2), (2, 4)]))
        prefix, extra = prompt.split('【2–4s｜镜头3】', 1)
        for tag, body, code in (
            ('【2–4s｜镜头4】', extra, 'PROMPT_SHOT_NUMBER_INVALID'),
            ('【2.1–4s｜镜头3】', extra, 'PROMPT_TIMELINE_GAP_OR_OVERLAP'),
            ('【1.9–4s｜镜头3】', extra, 'PROMPT_TIMELINE_GAP_OR_OVERLAP'),
            ('【4–4s｜镜头3】', extra, 'PROMPT_SHOT_INTERVAL_INVALID'),
            ('【2–4s｜镜头3】', extra.replace('硬切至侧面取景', '镜内转焦'), 'PROMPT_CUT_UNCERTAIN'),
        ):
            with self.subTest(code=code, tag=tag):
                self.assert_prompt_contract_failure(data, prefix + tag + body, ['PROMPT_SHOT_COUNT_MISMATCH', code])

    def assert_manifest_and_prompt_pass(self, data):
        self.assertEqual(validate_manifest(data), [])
        prompt = supported_prompt(data)
        self.assertEqual(wc.validate_prompt_against_manifest(data, prompt), [])
        path = self.space / 'segment.json'; path.write_bytes(encoded(data))
        text = self.space / 'prompt.md'; text.write_text(prompt, encoding='utf-8')
        for args in ((), ('--prompt', text)):
            proc = cli(self.common / 'tools/workflow_check.py', path, *args)
            self.assertEqual(proc.returncode, 0, proc.stdout)
            result = json.loads(proc.stdout)
            self.assertTrue(result['manifest_passed'])
            self.assertEqual(result['static_contract_passed'], True if args else None)
            self.assertIn('实际视频切点与单镜时长', result['not_verified'])
        return prompt

    def test_new_template_uses_three_second_limit(self):
        data = json.loads(self.layout.resources['template.project_parameters'].read_bytes())
        self.assertEqual(data['timing']['max_shot_seconds'], 3)
        self.assertEqual(Decimal(str(data['timing']['max_shot_seconds'])), wc.MAX_SHOT_SECONDS)
        self.assertEqual(data['timing']['minimum_shot_seconds_exclusive'], 0)
        self.assertIsNone(data['timing']['episode_default_seconds'])
        self.assertIsNone(data['timing']['segment_default_seconds'])

    def test_shot_duration_boundaries(self):
        for end in ('0.001', '2.999', '3.000'):
            with self.subTest(end=end):
                self.assert_manifest_and_prompt_pass(segment_with_shots(end, [(0, end)]))

    def test_shots_above_three_seconds_rejected(self):
        for end in ('3.001', '4', '5'):
            with self.subTest(end=end):
                data = segment_with_shots(end, [(0, end)])
                issues = validate_manifest(data)
                self.assertEqual([x['code'] for x in issues], ['SHOT_TOO_LONG'])
                path = self.space / 'overlong.json'; path.write_bytes(encoded(data))
                proc = cli(self.common / 'tools/workflow_check.py', path)
                self.assertEqual(proc.returncode, 1)
                self.assertEqual([x['code'] for x in json.loads(proc.stdout)['issues']], ['SHOT_TOO_LONG'])

    def test_zero_negative_intervals_still_rejected(self):
        for a, b, code in ((0, 0, 'INVALID_INTERVAL'), (2, 1, 'INVALID_INTERVAL'), (-1, 2, 'INVALID_TIME')):
            with self.subTest(a=a, b=b):
                self.assertIn(code, [x['code'] for x in validate_manifest(segment_with_shots(2, [(a, b)]))])

    def test_long_segment_with_short_shots_is_valid(self):
        self.assert_manifest_and_prompt_pass(segment_with_shots(8, [(0, 2.5), (2.5, 5), (5, 8)]))

    def test_prompt_limit_is_checked_independently(self):
        data = segment_with_shots(3, [(0, 3)])
        self.assertEqual(validate_manifest(data), [])
        prompt = supported_prompt(data).replace('【0–3s｜镜头1】', '【0–3.001s｜镜头1】')
        issues = wc.validate_prompt_against_manifest(data, prompt)
        self.assertIn('PROMPT_SHOT_TOO_LONG', [x['code'] for x in issues])

    def test_prompt_exact_three_seconds_passes(self):
        self.assert_manifest_and_prompt_pass(segment_with_shots('3.000', [(0, '3.000')]))

    def test_long_dialogue_across_short_shots(self):
        data = long_dialogue_segment(); original = deepcopy(data)
        prompt = self.assert_manifest_and_prompt_pass(data)
        self.assertEqual(data, original)
        self.assertEqual(prompt.count('原文：'), 1)
        self.assertEqual(prompt.count('对白〔D01〕沿前镜'), 2)
        parsed, issues = wc.parse_prompt(prompt)
        self.assertEqual(issues, [])
        event = next(x for x in parsed['dialogue'] if not x.get('continuation'))
        self.assertEqual((event['start'], event['end']), (Decimal(0), Decimal(8)))
        self.assertEqual(event['text'], original['source_dialogue']['D01'])
        self.assertEqual(event['speaker'], '合成发声者@合成人物_测试状态')

    def test_duplicate_dialogue_still_rejected(self):
        data = long_dialogue_segment()
        data['dialogue_events'].append(deepcopy(data['dialogue_events'][0]))
        self.assertIn('DUPLICATE_SPEECH_EVENT', [x['code'] for x in validate_manifest(data)])
        clean = long_dialogue_segment(); prompt = supported_prompt(clean)
        definition = next(line for line in prompt.splitlines() if '原文：' in line)
        prompt = prompt.replace('对白〔D01〕沿前镜连续到结束位置，不重复原句、不重新发声。', definition, 1)
        self.assertIn('PROMPT_EVENT_DUPLICATE', [x['code'] for x in wc.validate_prompt_against_manifest(clean, prompt)])

    def test_labels_without_real_cut_still_rejected(self):
        clean = segment_with_shots(8, [(0, 2.5), (2.5, 5), (5, 8)])
        for transition in ('continue', 'refocus', 'beat'):
            with self.subTest(transition=transition):
                data = deepcopy(clean); data['shots'][1]['transition_in'] = transition
                self.assertEqual([x['code'] for x in validate_manifest(data)], ['MISSING_REAL_CUT'])
        prompt = supported_prompt(clean).replace('硬切至侧面取景', '镜内转焦')
        self.assertIn('PROMPT_CUT_UNCERTAIN', [x['code'] for x in wc.validate_prompt_against_manifest(clean, prompt)])

    def test_gaps_overlaps_and_numbering_still_checked(self):
        for field, value, code in (('start', 2.6, 'TIMELINE_GAP_OR_OVERLAP'),
                                   ('start', 2.4, 'TIMELINE_GAP_OR_OVERLAP'),
                                   ('id', 's1', 'CONTINUOUS_SHOT_REUSED'),
                                   ('number', 3, 'SHOT_NUMBER_INVALID')):
            with self.subTest(field=field, value=value):
                data = segment_with_shots(8, [(0, 2.5), (2.5, 5), (5, 8)])
                data['shots'][1][field] = value
                self.assertEqual([x['code'] for x in validate_manifest(data)], [code])

    def test_srt_range_and_coverage_preserved(self):
        data = long_dialogue_segment()
        data['time_source'] = {'kind': 'srt', 'range_start': '56.541', 'range_end': '64.541'}
        data['source_narration'] = {'N01': '合成旁白事实：手停在门把上。'}
        data['narration_coverage'] = [{'source_id': 'N01', 'shot_ids': ['s1', 's2', 's3'],
                                      'visual_evidence': '起势、接触与持物结果覆盖原时间。'}]
        data['visible_text'] = [{'id': 'TXT-01', 'text': 'Acceso autorizado', 'language': 'es',
                                 'surface': '门上屏幕', 'start': 0, 'end': 8}]
        original = deepcopy(data); prompt = self.assert_manifest_and_prompt_pass(data)
        self.assertEqual(data, original)
        self.assertEqual(prompt.count('画面文字〔TXT-01〕：“'), 1)
        self.assertEqual(prompt.count('画面文字〔TXT-01〕维持'), 2)
        shortened = deepcopy(data); shortened['duration_seconds'] = 3
        self.assertIn('DURATION_SOURCE_MISMATCH', [x['code'] for x in validate_manifest(shortened)])
        missing = deepcopy(data); missing['narration_coverage'][0]['shot_ids'] = ['missing']
        self.assertIn('NARRATION_COVERAGE_INVALID', [x['code'] for x in validate_manifest(missing)])

    def test_initialized_project_gets_three_second_limit(self):
        project = self.project()
        data = json.loads((project / '项目参数.json').read_bytes())
        self.assertEqual(data['timing']['max_shot_seconds'], 3)
        self.assertEqual(data['workflow_version'], json.loads((self.common/'workflow.manifest.json').read_bytes())['rule_version'])
        self.assertEqual(data['schema'], 'JM-v3.5')
        self.assertEqual(self.layout.rule_version, data['workflow_version'])
        self.assertEqual(self.layout.infrastructure_version, '1.1.1')
        self.assertTrue(verify_lock(discover_from_project(project), read_lock(project / '工作流版本锁.json'))['ok'])

    def test_legacy_parameter_five_is_not_silently_overwritten(self):
        old = json.loads(self.layout.resources['template.project_parameters'].read_bytes())
        old['timing']['max_shot_seconds'] = 5; old['workflow_version'] = '3.5'
        before = deepcopy(old)
        raw = m.merge_parameters(encoded(old), self.layout.resources['template.project_parameters'].read_bytes(), common_root=self.common)
        new = json.loads(raw); before['project']['common_root'] = str(self.common)
        self.assertEqual(new, before)
        self.assertEqual(new['timing']['max_shot_seconds'], 5)

    def test_json_and_input_errors_keep_exit_code_two(self):
        path = self.space / 'bad.json'; path.write_bytes(b'{')
        for target in (path, self.space / 'missing.json'):
            proc = cli(self.common / 'tools/workflow_check.py', target)
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(json.loads(proc.stdout)['issues'][0]['code'], 'INPUT_READ_OR_JSON_ERROR')

    def test_A37_standalone_valid_invalid_exit_semantics(self):
        path=self.space/'segment.json'; data=valid_segment();path.write_bytes(encoded(data))
        proc=cli(self.common/'tools/workflow_check.py',path,cwd=self.space)
        self.assertEqual(proc.returncode,0,proc.stdout)
        result=json.loads(proc.stdout);self.assertTrue(result['manifest_passed']);self.assertIsNone(result['static_contract_passed'])
        data=segment_with_shots(4, [(0, 4)]);path.write_bytes(encoded(data))
        proc=cli(self.common/'tools/workflow_check.py',path)
        self.assertEqual(proc.returncode,1)
        self.assertEqual(['SHOT_TOO_LONG'],[x['code'] for x in json.loads(proc.stdout)['issues']])

    def test_A38_business_parameters_and_contracts_preserved(self):
        old=json.loads(self.layout.resources['template.project_parameters'].read_bytes())
        old['script']['fact_source']='synthetic-local';old['audio']['custom']={'voice':'local'}
        old['decisions']=[{'source':'synthetic user','scope':'one segment'}]
        raw=m.merge_parameters(encoded(old),self.layout.resources['template.project_parameters'].read_bytes(),common_root=self.common)
        new=json.loads(raw);new['project'].pop('common_root');old['project'].pop('common_root')
        self.assertEqual(new,old)
        self.assertEqual(new['timing']['max_shot_seconds'],3)
        self.assertEqual(new['audio']['narration_policy'],'visual_only')
        self.assertFalse(new['authorization']['spend_credits'])
        self.assertEqual(new['creative_priority'],['L0_current_task','L1_project_and_assets','L2_video_compiler','L3_director'])

    def test_A44_temporary_export_names_e2e(self):
        # 真正 ZIP 解包后的同一行为由 release 外置 smoke 记录；这里先验证集成链。
        self.layout.bundle_root.rename(self.layout.bundle_root.with_name('新包'))
        renamed=self.common.with_name('新公共');self.common.rename(renamed);self.common=renamed
        project=self.project(parent=self.space/'new-projects')
        layout=discover_from_project(project)
        self.assertTrue(verify_lock(layout,read_lock(project/'工作流版本锁.json'))['ok'])
        self.assertFalse(validate_manifest(valid_segment()))
        path=layout.resources['doc.readme'];path.write_bytes(path.read_bytes()+b'\nupgrade')
        self.approve(project,m.plan(project,self.common))
        self.assertTrue(verify_lock(load_layout(self.common),read_lock(project/'工作流版本锁.json'))['ok'])

    def test_A45_stable_copy_isolated(self):
        container=self.space/'stable-version';container.mkdir()
        stable=copy_workflow(container/'public')
        parent=self.space/'stable-projects';parent.mkdir()
        project=Path(initialize(parent,'合成稳定剧',common_root=stable,search_roots=[container])['project'])
        before=snapshot(stable);lock_before=(project/'工作流版本锁.json').read_bytes()
        self.layout.resources['doc.readme'].write_bytes(b'maintenance update')
        self.assertEqual(before,snapshot(stable))
        self.assertEqual(lock_before,(project/'工作流版本锁.json').read_bytes())
        self.assertEqual(discover_from_project(project).root,stable)
        self.assertTrue(verify_lock(load_layout(stable),read_lock(project/'工作流版本锁.json'))['ok'])

    def test_A46_readme_commands_plan_apply_cli(self):
        project=self.legacy();path=self.space/'cli-plan.json'
        proc=cli(self.common/'tools/migrate_workflow.py','plan','--project',project,'--common',self.common,'--output',path)
        self.assertEqual(proc.returncode,0,proc.stdout)
        proc=cli(self.common/'tools/migrate_workflow.py','apply','--project',project,'--plan',path,'--approve-plan-sha256',digest(path.read_bytes()))
        self.assertEqual(proc.returncode,0,proc.stdout)
        self.assertTrue(verify_lock(self.layout,read_lock(project/'工作流版本锁.json'))['ok'])
