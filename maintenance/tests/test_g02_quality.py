from support import *
from copy import deepcopy
import re
from tools import workflow_check as wc
from test_production_contracts import segment_with_shots, supported_prompt


PROFILE = 'g02_cinematic_fullname_v1'


def golden_segment(duration=25, number=1, setting='户外庭院'):
    bounds = [(i, min(i+2.5, duration)) for i in [j*2.5 for j in range(int(duration/2.5)+1)] if i < duration]
    m = segment_with_shots(duration, bounds)
    m.update(schema='JM-segment-check-v2', segment_number=number, segment_id=f'synthetic-{number}')
    m['asset_bindings'] = [
        {'type':'character','referent':'合成甲','aliases':['甲'], 'full_name':'人物/合成甲_庭院_正式造型.png','status':'verified'},
        {'type':'scene','referent':setting,'aliases':[], 'full_name':f'场景/{setting}_全景.png','status':'verified'}]
    m['quality'] = {'profile':PROFILE, 'viewing_task':'确认动作线索如何改变观看关系',
        'visual_progression':['空间建立','动作证据','接收反应','结果落地'],
        'start_state':'动作尚未启动', 'relationship_change':'行动权转移', 'end_state':'动作结果可见',
        'end_hook':'线索保留', 'segment_duration_exception':None}
    for i,s in enumerate(m['shots']):
        s.update(function=['establish','advance','evidence','reaction','result'][i%5],
            new_information=f'第{i+1}阶段的新信息', visible_evidence='动作改变与空间关系可观察',
            cut_trigger='动作阶段变化需要新的观看位置', end_state='视线与持物连续',
            asset_lock_required=False, asset_full_names=[x['full_name'] for x in m['asset_bindings']])
    p = supported_prompt(m).replace('【生成段','【分镜')
    for b in m['asset_bindings']:
        p = p.replace(b['referent']+'@'+b['full_name'], b['full_name'])
    lines=p.splitlines(); pos=next(i for i,x in enumerate(lines) if x=='【风格】')
    lines[pos:pos] = ['【本分镜资产全名锁】']+[b['full_name'] for b in m['asset_bindings']]+[
        '【观看任务】',m['quality']['viewing_task'],'【视觉递进】',' → '.join(m['quality']['visual_progression'])]
    # 合成边界测试文本，不冒充导演质量或原EP14附件。
    for i in range(len(lines)-1,-1,-1):
        if 's｜镜头' in lines[i]:
            lines.insert(i+1, '摄影位置沿已建立轴线观察动作起势接触结果与接收反应，画面保留空间纵深和实际环境声。'*max(9,int(225/duration)))
            lines.insert(i+1,'；'.join(b['full_name']+'保留对应动作归属与空间关系' for b in m['asset_bindings']))
    pos=lines.index('【末态承接】')
    lines[pos+1]=m['quality']['end_state']
    lines += ['【段尾钩子/结果】',m['quality']['end_hook']]
    return m,'\n'.join(lines)+'\n'


class G02Quality(Sandbox):
    def codes(self,m,p):
        return {x['code'] for x in wc.validate_manifest(m)+wc.validate_prompt_against_manifest(m,p)}

    def test_new_profile_defaults(self):
        p=json.loads(self.layout.resources['template.project_parameters'].read_bytes())
        self.assertEqual(p['prompt'].get('quality_profile'),'g02_cinematic_fullname_v2')
        self.assertEqual(p['prompt']['detail_target_characters'],2501)
        self.assertTrue(p['prompt']['detail_target_is_hard_limit'])

    def test_valid_golden_contract(self):
        m,p=golden_segment()
        self.assertEqual(self.codes(m,p),set())

    def test_detail_asset_padding_does_not_pass(self):
        m,p=golden_segment()
        p=p[:p.index('【0.0–')]+''.join(b['full_name']*100 for b in m['asset_bindings'])
        self.assertIn('PROMPT_DETAIL_TOO_SHORT',self.codes(m,p))

    def test_duration_boundaries(self):
        for value,code in [(19.999,'PROMPT_SEGMENT_TOO_SHORT'),(30.001,'PROMPT_SEGMENT_TOO_LONG')]:
            m,p=golden_segment(value)
            self.assertIn(code,self.codes(m,p))

    def test_explicit_duration_exception(self):
        m,p=golden_segment(15)
        m['quality']['segment_duration_exception']={'min':15,'max':18,'reason':'SRT尾段不足20秒','source':'confirmed-srt:tail'}
        self.assertEqual(self.codes(m,p),set())
        del m['quality']['segment_duration_exception']['source']
        self.assertIn('SEGMENT_EXCEPTION_INVALID',self.codes(m,p))

    def test_alias_in_body_and_arbitrary_quotes_fail(self):
        for alias in ['合成甲','她','两人','当前空间','同上','“合成甲抬头”','甲']:
            m,p=golden_segment()
            self.assertIn('PROMPT_ASSET_ALIAS_FORBIDDEN',self.codes(m,p+alias+'抬头。'))

    def test_authoritative_dialogue_and_screen_text_exempt(self):
        m,p=golden_segment()
        b=m['asset_bindings'][0]
        m['source_dialogue']={'D01':'合成甲，她在这里。'}
        m['main_language']='zh'
        m['source_dialogue_meta']={'D01':{'speaker':b['referent'],'kind':'dialogue','order':1,'source_ref':'synthetic:1'}}
        m['dialogue_events']=[{'id':'D01','speaker':b['referent'],'kind':'dialogue','text':m['source_dialogue']['D01'],'language':'zh','start':0,'end':8}]
        m['visible_text']=[{'id':'TXT-01','text':'合成甲','surface':b['full_name'],'language':'zh','start':0,'end':2}]
        p=p.replace('【0.0–2.5s｜镜头1】','【0.0–2.5s｜镜头1】\n现场对白〔D01〕：'+b['full_name']+'；原文：“合成甲，她在这里。”；时间：0–8s\n画面文字〔TXT-01〕：“合成甲”；承载面：'+b['full_name']+'；时间：0–2s')
        self.assertEqual(self.codes(m,p),set())
        self.assertIn('PROMPT_DIALOGUE_MISMATCH',self.codes(m,p.replace('合成甲，她在这里。','改写原文。')))

    def test_required_quality_and_flatness(self):
        for key,code in [('viewing_task','VIEWING_TASK_MISSING'),('visual_progression','VISUAL_PROGRESSION_MISSING'),('end_state','SEGMENT_END_STATE_MISSING')]:
            m,p=golden_segment(); m['quality'][key]=None
            self.assertIn(code,self.codes(m,p))
        m,p=golden_segment()
        for s in m['shots']: s['function']='advance'
        self.assertIn('FLAT_SHOT_DESIGN',self.codes(m,p))

    def test_asset_lock_missing_and_unverified(self):
        m,p=golden_segment()
        self.assertIn('SEGMENT_ASSET_LOCK_MISSING',self.codes(m,p.replace('【本分镜资产全名锁】','【删除】')))
        m['asset_bindings'][0]['status']='planned'
        self.assertIn('ASSET_NOT_VERIFIED',self.codes(m,p))

    def test_episode_multiple_segments_and_warnings(self):
        a,p=golden_segment(); b,q=golden_segment(number=2)
        for i,m in enumerate([a,b]): m['time_source']={'kind':'user','seconds':50,'range_start':i*25,'range_end':(i+1)*25}
        episode={'schema':'JM-episode-check-v1','time_source':{'kind':'user','seconds':50,'range_start':0,'range_end':50},'segments':[a,b]}
        prompt='## A. 本集导演方案\n内部允许合成甲。\n## B. 本集唯一视频Prompt\n'+p+q
        path=self.space/'episode.json'; path.write_bytes(encoded(episode))
        text=self.space/'episode.md'; text.write_text(prompt,encoding='utf-8')
        proc=cli(self.common/'tools/workflow_check.py',path,'--prompt',text)
        self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
        out=json.loads(proc.stdout)
        self.assertEqual(len(out['quality_contract']),2)
        self.assertIn('BOILERPLATE_DUPLICATION_WARNING',{x['code'] for x in out['warnings']})
        self.assertIn('导演质量语义审核',out['not_verified'])

    def test_v2_without_prompt_is_not_complete(self):
        m,p=golden_segment(); path=self.space/'segment.json'; path.write_bytes(encoded(m))
        proc=cli(self.common/'tools/workflow_check.py',path)
        self.assertEqual(proc.returncode,1,proc.stdout)
        self.assertIn('G02_PROMPT_REQUIRED',{x['code'] for x in json.loads(proc.stdout)['issues']})

    def test_wrong_profile_cannot_disable_v2_gate(self):
        m,p=golden_segment(); m['quality']['profile']='legacy'
        self.assertIn('QUALITY_PROFILE_INVALID',self.codes(m,p))

    def test_dialogue_exemption_does_not_hide_another_quoted_action(self):
        m,p=golden_segment(); b=m['asset_bindings'][0]; m['main_language']='zh'
        phrase='合成甲抬头'
        m['source_dialogue']={'D01':phrase}
        m['source_dialogue_meta']={'D01':{'speaker':b['referent'],'kind':'dialogue','order':1,'source_ref':'synthetic:1'}}
        m['dialogue_events']=[{'id':'D01','speaker':b['referent'],'kind':'dialogue','text':phrase,'language':'zh','start':0,'end':8}]
        p=p.replace('【0.0–2.5s｜镜头1】','【0.0–2.5s｜镜头1】\n现场对白〔D01〕：'+b['full_name']+'；原文：“'+phrase+'”；时间：0–8s')
        self.assertIn('PROMPT_ASSET_ALIAS_FORBIDDEN',self.codes(m,p+'\n执行动作：“'+phrase+'”。'))

    def test_malformed_manifest_returns_issues_without_crash(self):
        m,p=golden_segment(); m['shots'][0]['asset_full_names']=[{}]
        m['quality']['visual_progression']=[{}]
        self.assertTrue(self.codes(m,p))
        m,p=golden_segment(); m['shots'][0]['function']=[]
        self.assertIn('SHOT_FUNCTION_MISSING',self.codes(m,p))
        m,p=golden_segment(); m['dialogue_events']=None
        self.assertTrue(self.codes(m,p))

    def test_unknown_asset_in_body_fails(self):
        m,p=golden_segment()
        self.assertIn('PROMPT_ASSET_UNKNOWN',self.codes(m,p+'人物/未绑定人物.png走进画面。'))

    def test_episode_v1_cannot_bypass_new_gate(self):
        m=segment_with_shots(4,[(0,2),(2,4)])
        manifests,prompts,reports,warnings=wc.validate_delivery({'schema':'JM-episode-check-v1','segments':[m]},supported_prompt(m))
        self.assertIn('EPISODE_SEGMENT_SCHEMA_INVALID',{x['code'] for x in manifests})

    def test_high_risk_shot_lock(self):
        m,p=golden_segment(); m['shots'][0]['asset_lock_required']=True
        self.assertIn('SHOT_ASSET_LOCK_MISSING',self.codes(m,p))
        lock='【本镜资产全名锁】\n'+'\n'.join(m['shots'][0]['asset_full_names'])+'\n'
        p=p.replace('【0.0–2.5s｜镜头1】\n','【0.0–2.5s｜镜头1】\n'+lock)
        self.assertEqual(self.codes(m,p),set())

    def test_ep14_source_is_reference_with_known_identity_failures(self):
        source=FIXTURES/'g02-quality-golden'/'EP14.source.md'
        self.assertEqual(digest(source.read_bytes()),'b27fea3bb6067692599ad0b3329c0d5afaf2485de3c02a8a3fc4703f26b8b2eb')
        parts=wc.parse_episode_prompt(source.read_text(encoding='utf-8-sig'))
        self.assertEqual(len(parts),3)
        for part in parts:
            parsed,issues=wc.parse_prompt(part)
            self.assertGreaterEqual(parsed['duration'],20); self.assertLessEqual(parsed['duration'],30)
            self.assertEqual(len(parsed['shots']),12)
            self.assertTrue(all(0<s['end']-s['start']<=3 for s in parsed['shots']))
            names=re.findall(r'`((?:人物|场景|道具)/[^`]+\.png)`',part)
            self.assertGreater(wc.count_detail(part,names)['detail_cjk_after_asset_strip'],1500)
        self.assertIn('Nora',parts[0]); self.assertIn('计划占位',parts[2])
        counts=[wc.count_detail(part,re.findall(r'`((?:人物|场景|道具)/[^`]+\.png)`',part))['detail_cjk_after_asset_strip'] for part in parts]
        self.assertTrue(any(n<2501 for n in counts),'原稿基准必须如实暴露实际字数缺口，不能强行PASS')

    def test_delivery_note_cannot_pad_detail(self):
        m,p=golden_segment()
        p=re.sub('摄影位置[^\n]+','',p)
        p+='\n交付说明：\n'+'无关说明'*700
        self.assertIn('PROMPT_DETAIL_TOO_SHORT',self.codes(m,p))

    def test_episode_source_overlap_fails(self):
        a,p=golden_segment(); b,q=golden_segment(number=2)
        a['time_source']={'kind':'user','seconds':50,'range_start':0,'range_end':25}
        b['time_source']=deepcopy(a['time_source'])
        root={'schema':'JM-episode-check-v1','time_source':{'kind':'user','seconds':50,'range_start':0,'range_end':50},'segments':[a,b]}
        self.assertIn('EPISODE_SOURCE_COVERAGE_INVALID',{x['code'] for x in wc.validate_delivery(root,p+q)[0]})

    def test_different_scene_and_four_characters(self):
        for setting,count in [('户外桥边',2),('室内走廊',4),('回忆庭院',1)]:
            m,p=golden_segment(setting=setting)
            additions=[]
            for i in range(1,count):
                b={'type':'character','referent':f'合成角色{i}','aliases':[], 'full_name':f'人物/合成角色{i}_{setting}_造型.png','status':'verified'}
                m['asset_bindings'].append(b); additions.append(b['full_name'])
            p=p.replace('【本分镜资产全名锁】','【本分镜资产全名锁】\n'+'\n'.join(additions))
            p=p.replace('【人物引用】','【人物引用】\n'+'\n'.join(additions))
            for s in m['shots']: s['asset_full_names']+=additions
            p+='\n'+'；'.join(n+'保持既定站位与视线' for n in additions)
            self.assertEqual(self.codes(m,p),set())

    def test_narration_visual_only_and_long_speech_not_repeated(self):
        m,p=golden_segment()
        m['source_narration']={'N01':'合成动作经过等待后完成'}
        m['narration_coverage']=[{'source_id':'N01','shot_ids':[s['id'] for s in m['shots']], 'visual_evidence':'动作阶段的起势接触结果承载时间变化'}]
        self.assertEqual(self.codes(m,p),set())
        m['dialogue_events']=[{'id':'N01','speaker':'合成甲','kind':'narration','text':'合成动作经过等待后完成','language':'es','start':0,'end':25}]
        self.assertIn('NARRATION_MUST_BE_VISUAL',self.codes(m,p))

    def test_quality_progression_order_is_verified(self):
        m,p=golden_segment()
        p=p.replace('空间建立 → 动作证据 → 接收反应 → 结果落地','结果落地 → 接收反应 → 动作证据 → 空间建立')
        self.assertIn('PROMPT_QUALITY_MISMATCH',self.codes(m,p))

    def test_long_dialogue_across_ten_cuts_speaks_once(self):
        m,p=golden_segment(); b=m['asset_bindings'][0]
        phrase='He esperado para poder decirte toda la verdad.'
        m['source_dialogue']={'D01':phrase}
        m['source_dialogue_meta']={'D01':{'speaker':b['referent'],'kind':'dialogue','order':1,'source_ref':'synthetic:1'}}
        m['dialogue_events']=[{'id':'D01','speaker':b['referent'],'kind':'dialogue','text':phrase,'language':'es','start':0,'end':25}]
        p=p.replace('【0.0–2.5s｜镜头1】','【0.0–2.5s｜镜头1】\n现场对白〔D01〕：'+b['full_name']+'；原文：“'+phrase+'”；时间：0–25s')
        for s in m['shots'][1:]:
            title=f"【{s['start']}–{s['end']}s｜镜头{s['number']}】"
            p=p.replace(title,title+'\n对白〔D01〕沿前镜连续到原定结束位置，不重念。')
        self.assertEqual(self.codes(m,p),set())
        duplicate='现场对白〔D01〕：'+b['full_name']+'；原文：“'+phrase+'”；时间：0–25s'
        self.assertIn('PROMPT_EVENT_DUPLICATE',self.codes(m,p.replace('对白〔D01〕沿前镜连续到原定结束位置，不重念。',duplicate,1)))

    def test_cli_json_utf8_without_environment_override(self):
        m,p=golden_segment(); path=self.space/'input.json'; path.write_bytes(encoded(m))
        prompt=self.space/'prompt.md'; prompt.write_text(p,encoding='utf-8')
        env=dict(os.environ); env.pop('PYTHONIOENCODING',None); env['PYTHONUTF8']='0'
        proc=subprocess.run([sys.executable,'-B',str(self.common/'tools/workflow_check.py'),str(path),'--prompt',str(prompt)],env=env,capture_output=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertTrue(json.loads(proc.stdout.decode('utf-8'))['static_contract_passed'])
