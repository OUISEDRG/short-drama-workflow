"""新摄影/连接合同的离线回归；合成数据不代表平台绑定。"""
from support import *
from copy import deepcopy
import importlib.util
import inspect
from tools import workflow_check as wc
from test_g02_quality import golden_segment

CURRENT = 'g02_cinematic_fullname_v2'


def camera(number=1, kind='move'):
    return dict(kind=kind, technique='短距离推进', purpose='让观看范围落到动作证据',
        start_frame='左前侧平视中景', path_and_speed='沿既有轴线均匀前移',
        subject_relation='主体保持原站位，背景产生轻微视差', end_frame='结束于手部与面部同框',
        execution=f'摄影机沿已建立轴线前移，保留第{number}镜动作证据，结束于手部与面部同框。',
        static_reason='保持可读证据承载面' if kind=='static' else None)


def current_segment(number=1):
    m,p=golden_segment(number=number); m['quality']['profile']=CURRENT; m['sound_events']=[]
    for s in m['shots']:
        s['camera']=camera(number*100+s['number'])
        header=f"【{s['start']}–{s['end']}s｜镜头{s['number']}】"
        p=p.replace(header,header+'\n'+s['camera']['execution'])
    return m,p


def episode_data():
    segments=[]; parts=[]
    for i in [1,2]:
        m,p=current_segment(i);m['time_source']={'kind':'user','seconds':50,'range_start':(i-1)*25,'range_end':i*25}
        segments.append(m);parts.append(p)
    root={'schema':'JM-episode-check-v1','time_source':{'kind':'user','seconds':50,'range_start':0,'range_end':50},'segments':segments,
          'camera_strategy':'前段聚焦动作证据，后段横向展开关系，沿既有轴线保持阅读重点。','connections':[]}
    flat=[(i,m,s) for i,m in enumerate(segments) for s in m['shots']]
    for index,((ai,a,x),(bi,b,y)) in enumerate(zip(flat,flat[1:]),1):
        out=f'前镜第{index}个动作结果保持到边界，随后硬切。'
        into=f'硬切进入第{index+1}个观看位置，承接已完成动作状态。'
        c={'from':{'segment_id':a['segment_id'],'shot_id':x['id']},'to':{'segment_id':b['segment_id'],'shot_id':y['id']},
           'spacetime_relation':'同场连续','technique':'普通硬切','visual_edit':'hard_cut','match_elements':[],
           'cut_trigger':'新的动作证据需要新取景','out_execution':out,'in_execution':into,
           'audio_bridge':{'mode':'none','event_refs':[],'execution':''}}
        root['connections'].append(c)
        for pos,s,phrase in [(ai,x,out),(bi,y,into)]:
            header=f"【{s['start']}–{s['end']}s｜镜头{s['number']}】"
            parts[pos]=parts[pos].replace(header,header+'\n'+phrase)
    return root,'## A. 本集导演方案\n合成内部依据。\n## B. 本集唯一视频Prompt\n'+''.join(parts)


class ShotLanguage(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('tools.shot_language_check'), '新增检查模块尚未实施')
        from tools import shot_language_check
        return shot_language_check

    def codes(self,m,p,strict=True):
        self.assertIn('required_profile',inspect.signature(wc.validate_delivery).parameters,'正式profile约束尚未实施')
        a,b,_,_=wc.validate_delivery(m,p,required_profile=CURRENT if strict else None)
        return {x['code'] for x in a+b}

    def test_new_defaults_require_shot_language(self):
        layout=load_layout(ROOT);p=json.loads(layout.resources['template.project_parameters'].read_bytes())
        self.assertEqual(p['prompt']['quality_profile'],CURRENT)
        self.assertEqual(p['workflow_version'],'3.7.0')
        self.assertEqual(p['prompt']['camera_policy'],'whole_episode_dynamic')
        for key in ['require_camera_execution','require_transition_pairs','static_requires_reason']:self.assertIs(p['prompt'][key],True)
        t=json.loads(layout.resources['template.segment_check'].read_bytes());self.assertEqual(t['quality']['profile'],CURRENT);self.assertEqual(t['sound_events'],[]);self.assertEqual(t['shots'],[])

    def test_camera_fields_missing_null_and_wrong_types(self):
        module=self.module();m,_=current_segment()
        self.assertEqual(module.validate_camera_fields(m),[])
        for bad in [None,[],{},'推进']:
            x=deepcopy(m);x['shots'][0]['camera']=bad
            self.assertIn('CAMERA_CONTRACT_MISSING',{q['code'] for q in module.validate_camera_fields(x)})
        for key in ['kind','technique','purpose','start_frame','path_and_speed','subject_relation','end_frame','execution']:
            for bad in [None,[],{},'']:
                x=deepcopy(m);x['shots'][0]['camera'][key]=bad
                self.assertTrue(module.validate_camera_fields(x),(key,bad))

    def test_static_requires_reason_and_dynamic_reason_is_null(self):
        module=self.module();m,_=current_segment();m['shots'][0]['camera']=camera(kind='static');self.assertEqual(module.validate_camera_fields(m),[])
        m['shots'][0]['camera']['static_reason']='';self.assertIn('CAMERA_STATIC_REASON_MISSING',{x['code'] for x in module.validate_camera_fields(m)})
        m['shots'][0]['camera']=camera();m['shots'][0]['camera']['static_reason']='随便';self.assertTrue(module.validate_camera_fields(m))
        m['shots'][0]['camera']=camera();del m['shots'][0]['camera']['static_reason'];self.assertTrue(module.validate_camera_fields(m))

    def test_valid_current_episode_and_single_scope(self):
        m,p=episode_data();self.assertEqual(self.codes(m,p),set())
        single,part=current_segment();self.assertEqual(self.codes(single,part),set())

    def test_camera_missing_wrong_shot_duplicate_and_a_only(self):
        m,p=episode_data();sentence=m['segments'][0]['shots'][0]['camera']['execution']
        for moved in ['', '\n## C. 附录\n'+sentence]:
            self.assertIn('CAMERA_EXECUTION_NOT_IN_SHOT',self.codes(m,p.replace(sentence,'',1)+moved))
        self.assertIn('CAMERA_EXECUTION_NOT_IN_SHOT',self.codes(m,p.replace(sentence,'',1).replace('## B.',sentence+'\n## B.')))
        wrong=p.replace(sentence,'',1).replace('【2.5–5.0s｜镜头2】','【2.5–5.0s｜镜头2】\n'+sentence,1)
        self.assertIn('CAMERA_EXECUTION_NOT_IN_SHOT',self.codes(m,wrong))
        self.assertIn('CAMERA_EXECUTION_DUPLICATED',self.codes(m,p.replace(sentence,sentence+sentence,1)))

    def test_comments_unknown_appendix_and_delivery_note_do_not_count(self):
        m,p=episode_data();s=m['segments'][0]['shots'][-1]['camera']['execution']
        for replacement in ['<!--'+s+'-->','【附录】\n'+s,'交付说明：'+s,'### 附录\n'+s]:
            self.assertIn('CAMERA_EXECUTION_NOT_IN_SHOT',self.codes(m,p.replace(s,replacement,1)),replacement)

    def test_current_episode_requires_explicit_b_section(self):
        m,p=episode_data();self.assertIn('PROMPT_EXECUTION_SECTION_REQUIRED',self.codes(m,p.replace('## B. 本集唯一视频Prompt','')))

    def test_camera_in_authoritative_literal_cannot_count(self):
        module=self.module();m,_=current_segment();s=m['shots'][0]['camera']['execution']
        parsed={'shots':[{'number':x['number'],'execution_body':'' if i==0 else x['camera']['execution']} for i,x in enumerate(m['shots'])]}
        self.assertIn('CAMERA_EXECUTION_NOT_IN_SHOT',{x['code'] for x in module.validate_camera_text(m,parsed)})

    def test_connections_missing_duplicate_reordered_skipped_invalid_refs(self):
        m,p=episode_data()
        for change in ['missing','duplicate','reorder','skip','bad_id']:
            x=deepcopy(m)
            if change=='missing':x['connections'].pop()
            if change=='duplicate':x['connections'][1]=deepcopy(x['connections'][0])
            if change=='reorder':x['connections'][0],x['connections'][1]=x['connections'][1],x['connections'][0]
            if change=='skip':x['connections'][0]['to']=deepcopy(x['connections'][1]['to'])
            if change=='bad_id':x['connections'][0]['from']['segment_id']='不存在'
            self.assertTrue({'CONNECTION_COVERAGE_INVALID','CONNECTION_REF_INVALID'}&self.codes(x,p),change)

    def test_connection_both_ends_and_visual_edit(self):
        m,p=episode_data();c=m['connections'][9]
        self.assertIn('CONNECTION_EXECUTION_MISSING',self.codes(m,p.replace(c['in_execution'],'')))
        x=deepcopy(m);x['connections'][0]['visual_edit']='match_cut';self.assertIn('CONNECTION_VISUAL_EDIT_MISMATCH',self.codes(x,p))
        self.assertEqual(m['segments'][1]['shots'][0]['transition_in'],'start');self.assertEqual(self.codes(m,p),set())

    def test_camera_strategy_and_malformed_contract_returns_issues(self):
        m,p=episode_data();m['camera_strategy']='';self.assertIn('CAMERA_STRATEGY_MISSING',self.codes(m,p))
        module=self.module()
        for bad in [None,[],{'segments':None},{'segments':[None],'connections':[None]},{'segments':[],'connections':{}}]:
            self.assertTrue(module.validate_connections(bad,[]))
        for bad in [None,[],{'shots':[None]},{'shots':None}]:self.assertTrue(module.validate_camera_fields(bad))

    def test_audio_missing_refs_wrong_time_unauthorized_effect_and_cross_request(self):
        m,p=episode_data();c=m['connections'][0];c['audio_bridge']={'mode':'L','event_refs':['missing'],'execution':'前镜声音延续到后镜。'}
        self.assertIn('AUDIO_BRIDGE_EVENT_INVALID',self.codes(m,p))
        seg=m['segments'][0];seg['sound_events']=[{'id':'S01','description':'桌面纸张轻擦声','start':3,'end':4,'source_ref':'合成输入:纸张移动','kind':'action','authorization_ref':None}]
        c['audio_bridge']['event_refs']=['S01'];self.assertIn('AUDIO_BRIDGE_TIME_INVALID',self.codes(m,p))
        seg['sound_events'][0].update(start=1,end=4,kind='authorized_effect');self.assertIn('AUDIO_BRIDGE_EVENT_INVALID',self.codes(m,p))
        seg['sound_events'][0].update(kind='action');m['connections'][9]['audio_bridge']={'mode':'L','event_refs':['S01'],'execution':'声音延续。'}
        self.assertIn('AUDIO_BRIDGE_CROSS_REQUEST_UNVERIFIED',self.codes(m,p))

    def test_sound_fields_invalid_do_not_crash(self):
        module=self.module();m,p=episode_data()
        for bad in [None,{},[None],[{}],[{'id':[]}]]:
            x=deepcopy(m);x['segments'][0]['sound_events']=bad
            self.assertIn('AUDIO_BRIDGE_EVENT_INVALID',self.codes(x,p))
        for bad in [None,[],{}, {'mode':[],'event_refs':[{}],'execution':None}]:
            x=deepcopy(m);x['connections'][0]['audio_bridge']=bad;self.assertTrue(self.codes(x,p))

    def test_old_profile_is_diagnostic_only_and_cannot_downgrade(self):
        m,p=golden_segment();self.assertEqual(self.codes(m,p,strict=False),set());self.assertIn('CURRENT_PROFILE_REQUIRED',self.codes(m,p))
        x,q=episode_data();x['segments'][1]['quality']['profile']='g02_cinematic_fullname_v1';self.assertIn('CURRENT_PROFILE_REQUIRED',self.codes(x,q))
        del x['segments'][0]['quality']['profile'];self.assertIn('CURRENT_PROFILE_REQUIRED',self.codes(x,q))

    def test_cli_scope_and_current_contract_flags(self):
        self.assertIn('required_profile',inspect.signature(wc.validate_delivery).parameters)
        m,p=episode_data()
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);a=root/'input.json';b=root/'prompt.md';a.write_bytes(encoded(m));b.write_text(p,encoding='utf-8')
            proc=cli(ROOT/'tools/workflow_check.py',a,'--prompt',b,'--require-profile',CURRENT)
            self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr);r=json.loads(proc.stdout);self.assertIs(r['current_contract_passed'],True);self.assertEqual(r['sequence_scope'],'episode')
            single,part=current_segment();a.write_bytes(encoded(single));b.write_text(part,encoding='utf-8');r=json.loads(cli(ROOT/'tools/workflow_check.py',a,'--prompt',b,'--require-profile',CURRENT).stdout);self.assertEqual(r['sequence_scope'],'segment')
            a.write_bytes(encoded(golden_segment()[0]));b.write_text(golden_segment()[1],encoding='utf-8');r=json.loads(cli(ROOT/'tools/workflow_check.py',a,'--prompt',b).stdout);self.assertIs(r['current_contract_passed'],False)

    def test_camera_cross_segment_duplication_is_rejected(self):
        m,p=episode_data();a=m['segments'][0]['shots'][0]['camera']['execution'];b=m['segments'][1]['shots'][0]['camera']['execution']
        m['segments'][1]['shots'][0]['camera']['execution']=a
        self.assertIn('CAMERA_EXECUTION_DUPLICATED',self.codes(m,p.replace(b,a)))

    def test_single_segment_sound_registry_is_checked(self):
        m,p=current_segment();m['sound_events']=[{'id':'bad'}]
        self.assertIn('AUDIO_BRIDGE_EVENT_INVALID',self.codes(m,p))

    def test_format_heading_is_not_asset_alias_but_body_alias_is(self):
        m,p=current_segment();m['asset_bindings'][1]['referent']='场景'
        self.assertEqual(self.codes(m,p),set())
        sentence=m['shots'][0]['camera']['execution']
        self.assertIn('PROMPT_ASSET_ALIAS_FORBIDDEN',self.codes(m,p.replace(sentence,sentence+'场景保持。',1)))

    def test_whitespace_only_matching_and_quotes_comments_fences(self):
        m,p=episode_data();s=m['segments'][0]['shots'][0]['camera']['execution']
        self.assertEqual(self.codes(m,p.replace(s,s[:10]+' \n '+s[10:],1)),set())
        for bad in [s.replace('前移','后移'),s.replace('101','102'),s.replace('，','；'),s.replace('保留','不保留')]:
            self.assertIn('CAMERA_EXECUTION_NOT_IN_SHOT',self.codes(m,p.replace(s,bad,1)))
        for bad in ['```text\n'+s+'\n```','~~~\n'+s+'\n~~~']:
            self.assertIn('CAMERA_EXECUTION_NOT_IN_SHOT',self.codes(m,p.replace(s,bad,1)))
        self.assertEqual(self.codes(m,p.replace(s,'<!--说明--> '+s,1)),set())

    def test_mismatched_and_quoted_fences_never_count_execution(self):
        m,p=episode_data();s=m['segments'][0]['shots'][0]['camera']['execution']
        for block in ['```text\n~~~\n'+s+'\n~~~\n```','````text\n```\n'+s+'\n```\n````','> ```text\n> '+s+'\n> ```']:
            self.assertIn('CAMERA_EXECUTION_NOT_IN_SHOT',self.codes(m,p.replace(s,block,1)))
        segment,part=current_segment();names=[b['full_name'] for b in segment['asset_bindings']]
        minimum=wc.count_detail('\n'.join(wc.eligible_lines(part)),names)['detail_cjk_after_asset_strip']+1
        segment['quality']['detail_override']={'min_cjk':minimum,'reason':'测试围栏不能补字数','source':'独立合成回归'}
        padding='```text\n~~~\n无效代码内容不能补充执行细节\n~~~\n```\n'
        part=part.replace('【0.0–2.5s｜镜头1】','【0.0–2.5s｜镜头1】\n'+padding,1)
        self.assertIn('PROMPT_DETAIL_TOO_SHORT',self.codes(segment,part))

    def test_two_authoritative_literals_same_line_keep_execution_outside(self):
        m,p=current_segment();sentence=m['shots'][0]['camera']['execution'];name=m['asset_bindings'][0]['full_name'];scene=m['asset_bindings'][1]['full_name']
        m['source_dialogue']={'D01':'她'};m['source_dialogue_meta']={'D01':{'speaker':m['asset_bindings'][0]['referent'],'kind':'dialogue','order':1,'source_ref':'合成'}}
        m['dialogue_events']=[{'id':'D01','text':'她','speaker':m['asset_bindings'][0]['referent'],'kind':'dialogue','language':'zh','start':0,'end':1}];m['main_language']='zh'
        m['visible_text']=[{'id':'T01','text':'他','surface':scene,'language':'zh','start':0,'end':1}]
        line=f'现场对白〔D01〕：{name}；原文：“她”；时间：0–1s 画面文字〔T01〕：“他”；承载面：{scene}；时间：0–1s'
        p=p.replace(sentence,line+' '+sentence,1)
        self.assertNotIn('PROMPT_ASSET_ALIAS_FORBIDDEN',self.codes(m,p))
        m['source_dialogue']['D01']=sentence;m['dialogue_events'][0]['text']=sentence
        p=p.replace('原文：“她”','原文：“'+sentence+'”').replace(' '+sentence,'',1)
        self.assertIn('CAMERA_EXECUTION_NOT_IN_SHOT',self.codes(m,p))

    def test_audio_positive_bridge_and_qualified_ambiguous_events(self):
        m,p=episode_data();seg=m['segments'][0];c=m['connections'][0]
        seg['sound_events']=[{'id':'S01','description':'已确认纸张摩擦','start':1,'end':4,'source_ref':'合成动作','kind':'action','authorization_ref':None}]
        text='纸张摩擦声在前镜开始并在硬切后连续至原定结束。'
        c['audio_bridge']={'mode':'L','event_refs':[{'segment_id':seg['segment_id'],'event_id':'S01'}],'execution':text}
        target=m['segments'][0]['shots'][1]['camera']['execution'];p=p.replace(target,target+'\n'+text,1)
        self.assertEqual(self.codes(m,p),set())
        for times in [(2.5,4),(1,2.5)]:
            seg['sound_events'][0].update(start=times[0],end=times[1]);self.assertIn('AUDIO_BRIDGE_TIME_INVALID',self.codes(m,p))
        seg['sound_events'][0].update(start=1,end=4)
        c['audio_bridge']['event_refs']=[{'segment_id':m['segments'][1]['segment_id'],'event_id':'S01'}]
        self.assertIn('AUDIO_BRIDGE_EVENT_INVALID',self.codes(m,p))

    def test_srt_nonzero_origin_uses_absolute_cut(self):
        m,p=episode_data();m['time_source']={'kind':'srt','range_start':100,'range_end':150,'source_ref':'合成SRT'}
        for i,s in enumerate(m['segments']):s['time_source']={'kind':'srt','range_start':100+25*i,'range_end':125+25*i,'source_ref':'合成SRT'}
        self.assertEqual(self.codes(m,p),set())

    def test_duplicate_b_and_invalid_json_flags(self):
        m,p=episode_data();self.assertIn('PROMPT_EXECUTION_SECTION_REQUIRED',self.codes(m,p+'\n## B. 本集唯一视频Prompt\n'))
        with tempfile.TemporaryDirectory() as t:
            f=Path(t)/'bad.json';f.write_text('{bad',encoding='utf-8')
            result=cli(ROOT/'tools/workflow_check.py',f,'--require-profile',CURRENT);self.assertEqual(result.returncode,2)
            data=json.loads(result.stdout);self.assertIs(data['current_contract_passed'],False);self.assertEqual(data['sequence_scope'],'unknown')

    def fixture(self):
        root=ROOT/'maintenance/tests/fixtures/shot-language'
        return json.loads((root/'episode.json').read_text(encoding='utf-8')),(root/'episode.md').read_text(encoding='utf-8')

    def test_full_episode_current_contract_passes(self):
        m,p=self.fixture();a,b,reports,warnings=wc.validate_delivery(m,p,required_profile=CURRENT)
        self.assertEqual(a+b,[]);self.assertEqual(len(reports),2);self.assertTrue(all(x['detail_cjk_after_asset_strip']>=2501 for x in reports))
        self.assertEqual(sum(len(s['shots']) for s in m['segments']),20);self.assertEqual(len(m['connections']),19)

    def test_full_fixture_mutations_fail_in_actual_b_body(self):
        m,p=self.fixture();s=m['segments'][0]['shots'][0]['camera']['execution'];c=m['connections'][9]
        self.assertIn('CAMERA_EXECUTION_NOT_IN_SHOT',self.codes(m,p.replace(s,'',1)))
        self.assertIn('CONNECTION_EXECUTION_MISSING',self.codes(m,p.replace(c['in_execution'],'',1)))
        event=m['segments'][0]['dialogue_events'][0]
        self.assertIn('PROMPT_DIALOGUE_MISMATCH',self.codes(m,p.replace('原文：“'+event['text']+'”','原文：“未经授权改写。”',1)))
        time=f"时间：{event['start']:.2f}–{event['end']:.2f}s"
        self.assertIn(time,p,'变异必须实际命中原正文')
        self.assertIn('PROMPT_DIALOGUE_TIME_MISMATCH',self.codes(m,p.replace(time,'时间：0.00–1.00s',1)))
        name=m['segments'][0]['asset_bindings'][0]['full_name'];self.assertIn('PROMPT_ASSET_ALIAS_FORBIDDEN',self.codes(m,p.replace(name,'女主')))
        # B段缩成空执行，保留全部原正文在A区也不能凑足详细度或摄影句。
        parts=wc.parse_episode_prompt(p);short=[]
        for part in parts:
            import re
            short.append(re.sub(r'(?ms)(【[0-9.]+[–—－-][0-9.]+s｜镜头\d+】).*?(?=【[0-9.]+[–—－-][0-9.]+s｜镜头\d+】|【末态承接】)',r'\1\n硬切。\n',part))
        reduced='## A. 本集导演方案\n'+p.replace('## B. 本集唯一视频Prompt','示例')+'\n## B. 本集唯一视频Prompt\n'+'\n'.join(short)
        self.assertIn('PROMPT_DETAIL_TOO_SHORT',self.codes(m,reduced))

    def test_diagnostic_new_profile_cannot_claim_formal_pass(self):
        m,p=episode_data()
        with tempfile.TemporaryDirectory() as t:
            a=Path(t)/'e.json';b=Path(t)/'p.md';a.write_bytes(encoded(m));b.write_text(p,encoding='utf-8')
            result=json.loads(cli(ROOT/'tools/workflow_check.py',a,'--prompt',b).stdout)
            self.assertIs(result['current_contract_passed'],False);self.assertIsNone(result['required_profile']);self.assertEqual(result['sequence_scope'],'episode')


class ShotLanguageInfrastructure(Sandbox):
    def test_new_project_and_new_reference_lock_are_enforced(self):
        from tools.init_project import initialize
        from tools.workflow_lock import make_lock,verify_lock
        p=Path(initialize(self.space,'合成摄影项目',common_root=self.common)['project'])
        params=json.loads((p/'项目参数.json').read_bytes());self.assertEqual(params['prompt']['quality_profile'],CURRENT)
        layout=load_layout(self.common);lock=make_lock(layout)
        self.assertIn('reference.shot_language',lock['resources']);self.assertIn('tool.shot_language_check',lock['resources'])
        ref=layout.resources['reference.shot_language'];ref.write_bytes(ref.read_bytes()+b'\n')
        self.assertFalse(verify_lock(load_layout(self.common),lock)['ok'])
        # 只读发现差异不写入项目参数与项目锁。
        self.assertEqual(json.loads((p/'项目参数.json').read_bytes()),params)


if __name__=='__main__':unittest.main()
