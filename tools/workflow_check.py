"""离线静态合同检查。不会调用模型、联网、修改项目或认证成片。"""
from __future__ import annotations
import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from typing import Any

MAX_SHOT_SECONDS = Decimal('3')


def validate_manifest(m: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    def issue(code: str, at: str, message: str) -> None:
        issues.append({'code': code, 'at': at, 'message': message})
    def number(value: Any, at: str) -> Decimal | None:
        try:
            if isinstance(value, bool): raise ValueError('布尔值不是时间')
            d = Decimal(str(value))
            if not d.is_finite() or d < 0: raise ValueError('时间须有限且非负')
            return d
        except (InvalidOperation, ValueError, TypeError):
            issue('INVALID_TIME', at, '需要有限的非负秒数。'); return None
    def interval(item: dict[str, Any], at: str) -> tuple[Decimal | None, Decimal | None]:
        a=number(item.get('start'),at+'.start'); b=number(item.get('end'),at+'.end')
        if a is not None and b is not None and b <= a:
            issue('INVALID_INTERVAL',at,'结束必须晚于开始。')
        return a,b
    if not isinstance(m,dict):
        return [{'code':'INVALID_MANIFEST','at':'root','message':'清单必须为JSON对象。'}]
    lang=m.get('main_language')
    if not isinstance(lang,str) or not lang.strip():
        issue('MAIN_LANGUAGE_MISSING','main_language','先确定本剧主语言。'); lang=''
    base_lang=lang.lower().split('-')[0]
    duration=number(m.get('duration_seconds'),'duration_seconds')
    source=m.get('time_source',{})
    if not isinstance(source,dict): issue('FIELD_TYPE_INVALID','time_source','需要来源对象。'); source={}
    kind=source.get('kind')
    expected=None
    if kind=='user':
        expected=number(source.get('seconds'),'time_source.seconds')
        if 'range_start' in source or 'range_end' in source:
            a=number(source.get('range_start'),'time_source.range_start')
            b=number(source.get('range_end'),'time_source.range_end')
            if a is not None and b is not None:
                if expected is not None and b>expected:
                    issue('EVENT_OUT_OF_RANGE','time_source','生成段区间超过用户指定的整集预算。')
                expected=b-a
                if expected<=0: issue('INVALID_INTERVAL','time_source','生成段区间必须为正时长。')
    elif kind=='srt':
        a=number(source.get('range_start'),'time_source.range_start'); b=number(source.get('range_end'),'time_source.range_end')
        if a is not None and b is not None:
            expected=b-a
            if expected<=0: issue('INVALID_INTERVAL','time_source','SRT范围必须为正时长。')
    else:
        issue('TIMING_NOT_CONFIRMED','time_source','缺少用户要求或已确认SRT；估时稿不能冒充已确认提交稿。')
    if duration is not None and expected is not None and duration!=expected:
        issue('DURATION_SOURCE_MISMATCH','duration_seconds','总时长不等于本次用户要求或所选SRT范围。')
    if duration==0: issue('INVALID_INTERVAL','duration_seconds','总时长必须大于0。')
    if m.get('has_independent_voice_reference') is not False:
        issue('INDEPENDENT_VOICE_REFERENCE','audio','不得输出独立音色/声音/音频引用模块。')
    if m.get('character_attached_audio_preserved') is not True:
        issue('ATTACHED_AUDIO_NOT_PRESERVED','audio','必须核对人物附带音频保留；无此类音频时也须先核对。')
    if m.get('screen_text_mode')!='direct_generation':
        issue('SCREEN_TEXT_NOT_DIRECT','screen_text_mode','画面文字由视频直接生成，不转交后期。')
    if m.get('schema')!='JM-segment-check-v1': issue('SCHEMA_MISSING','schema','需补充本段清单元数据。')
    if not isinstance(m.get('segment_id'),str) or not m.get('segment_id','').strip(): issue('SEGMENT_ID_MISSING','segment_id','需要稳定段ID。')
    if type(m.get('segment_number')) is not int or m.get('segment_number',0)<1: issue('SEGMENT_NUMBER_INVALID','segment_number','需要正整数段号。')
    review=m.get('source_review')
    if not isinstance(review,dict): issue('SOURCE_REVIEW_MISSING','source_review','旧清单需补充来源确认元数据。'); review={}
    for key in ('dialogue','narration','visible_text'):
        if review.get(key)!='confirmed': issue('SOURCE_REVIEW_UNCONFIRMED','source_review.'+key,'来源尚未确认。')
    shots=m.get('shots')
    if not isinstance(shots,list): issue('FIELD_TYPE_INVALID','shots','需要数组。'); shots=[]
    if not shots: issue('SHOTS_MISSING','shots','必须列出真实连续镜头。')
    shot_ids: set[str]=set(); previous=Decimal(0)
    for i,s in enumerate(shots):
        at=f'shots[{i}]'
        if not isinstance(s,dict): issue('INVALID_SHOT',at,'镜头必须是对象。'); continue
        sid=s.get('id')
        if not isinstance(sid,str) or not sid: issue('SHOT_ID_MISSING',at,'镜头需要稳定编号。')
        elif sid in shot_ids: issue('CONTINUOUS_SHOT_REUSED',at,'不能重复一个连续镜头编号来拆分其时长。')
        else: shot_ids.add(sid)
        if type(s.get('number')) is not int or s['number']!=i+1: issue('SHOT_NUMBER_INVALID',at+'.number','镜号须从1连续递增。')
        a,b=interval(s,at)
        if a is not None and b is not None:
            if b-a>MAX_SHOT_SECONDS: issue('SHOT_TOO_LONG',at,'一个连续镜头不得超过3秒。')
            if a!=previous: issue('TIMELINE_GAP_OR_OVERLAP',at,'视觉时间轴不连续或重叠。')
            previous=b
        transition=s.get('transition_in')
        if (i==0 and transition!='start') or (i>0 and transition not in {'hard_cut','match_cut','dissolve'}):
            issue('MISSING_REAL_CUT',at,'镜头之间须明确实际剪接；继续、转焦、节拍变化不是新镜头。')
    if duration is not None and previous!=duration:
        issue('TIMELINE_END_MISMATCH','shots','最后一个镜头必须结束于段落总时长。')
    def language(item: dict[str,Any],at: str) -> None:
        text=item.get('text')
        if not isinstance(text,str) or not text.strip(): issue('TEXT_MISSING',at,'需要实际原文，不可留空。'); return
        if item.get('language')!=lang: issue('LANGUAGE_MISMATCH',at,'文字/声音必须使用本剧主语言。')
        # 此检查只能发现明显异文字体系；不能识别目标语言的错词或伪词。
        if base_lang in {'es','en','pt','fr','de','it'} and re.search(r'[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]',text):
            issue('FOREIGN_SCRIPT',at,'主语言为拉丁字母语言时出现中日韩字符。')
    def bounded(item: dict[str,Any],at: str) -> None:
        a,b=interval(item,at)
        if duration is not None and b is not None and b>duration:
            issue('EVENT_OUT_OF_RANGE',at,'声音或可见文字超出本段时长。')
    src=m.get('source_dialogue')
    if not isinstance(src,dict): src={}; issue('SOURCE_DIALOGUE_INVALID','source_dialogue','权威对白必须以事件ID映射原文。')
    for eid,original in src.items():
        if not isinstance(eid,str) or not eid.strip() or not isinstance(original,str) or not original.strip(): issue('SOURCE_DIALOGUE_INVALID','source_dialogue.'+str(eid),'ID和原文须为非空字符串。')
    meta=m.get('source_dialogue_meta')
    if not isinstance(meta,dict): meta={}; issue('DIALOGUE_META_MISSING','source_dialogue_meta','需补充权威说话人、类型、顺序与来源。')
    if set(meta)!=set(src): issue('DIALOGUE_META_MISMATCH','source_dialogue_meta','元数据与原文ID须一一对应。')
    orders=[]
    for eid,entry in meta.items():
        at='source_dialogue_meta.'+str(eid)
        if not isinstance(entry,dict): issue('FIELD_TYPE_INVALID',at,'需要对象。'); continue
        if not isinstance(entry.get('speaker'),str) or not entry['speaker'].strip(): issue('SPEAKER_MISSING',at,'权威说话人缺失。')
        if entry.get('kind') not in {'dialogue','offscreen_dialogue'}: issue('DIALOGUE_KIND_INVALID',at,'对白类型无效。')
        if type(entry.get('order')) is not int or entry['order']<1: issue('DIALOGUE_ORDER_INVALID',at,'顺序号须为正整数。')
        else: orders.append(entry['order'])
        if not isinstance(entry.get('source_ref'),str) or not entry['source_ref'].strip(): issue('SOURCE_REF_MISSING',at,'需要具体来源位置。')
    if sorted(orders)!=list(range(1,len(meta)+1)): issue('DIALOGUE_ORDER_INVALID','source_dialogue_meta','顺序号须唯一且连续。')
    events=m.get('dialogue_events')
    if not isinstance(events,list): issue('FIELD_TYPE_INVALID','dialogue_events','需要数组。'); events=[]
    seen: list[str]=[]
    starts=[]
    for i,e in enumerate(events):
        at=f'dialogue_events[{i}]'
        if not isinstance(e,dict): issue('INVALID_EVENT',at,'事件必须是对象。'); continue
        eid=e.get('id')
        if not isinstance(eid,str) or not eid:
            issue('SPEECH_ID_MISSING',at,'声音事件ID必须是非空字符串。'); continue
        if eid in seen: issue('DUPLICATE_SPEECH_EVENT',at,'一句对白跨镜不能重复启动。')
        seen.append(eid)
        if e.get('kind') not in {'dialogue','offscreen_dialogue'}:
            issue('NARRATION_MUST_BE_VISUAL',at,'旁白只转画面；真实现场/画外对白保留。')
        if not isinstance(e.get('speaker'),str) or not e['speaker'].strip(): issue('SPEAKER_MISSING',at,'正常对白须明确发声者。')
        if eid in src and src[eid]!=e.get('text'): issue('DIALOGUE_CHANGED',at,'不得改写权威对白。')
        if eid in meta and isinstance(meta[eid],dict):
            if e.get('speaker')!=meta[eid].get('speaker'): issue('DIALOGUE_SPEAKER_MISMATCH',at,'发声者与来源不符。')
            if e.get('kind')!=meta[eid].get('kind'): issue('DIALOGUE_KIND_MISMATCH',at,'对白类型与来源不符。')
        language(e,at); bounded(e,at)
        start=number(e.get('start'),at+'.start')
        if start is not None: starts.append(start)
    if set(seen)!=set(src): issue('DIALOGUE_MISSING_OR_ADDED','dialogue_events','权威对白有遗漏或新增。')
    ordered=[eid for eid,v in sorted(meta.items(),key=lambda pair:pair[1].get('order',999999) if isinstance(pair[1],dict) and type(pair[1].get('order')) is int else 999999)]
    if seen!=ordered: issue('DIALOGUE_ORDER_CHANGED','dialogue_events','对白顺序与权威清单不同。')
    if starts!=sorted(starts): issue('DIALOGUE_TIME_ORDER_CHANGED','dialogue_events','实际发声起点顺序颠倒。')
    narration=m.get('source_narration')
    if not isinstance(narration,dict): issue('FIELD_TYPE_INVALID','source_narration','需要来源对象。'); narration={}
    for nid,original in narration.items():
        if not isinstance(nid,str) or not nid.strip() or not isinstance(original,str) or not original.strip(): issue('SOURCE_NARRATION_INVALID','source_narration.'+str(nid),'ID和来源文字须为非空字符串。')
    coverage=m.get('narration_coverage')
    if not isinstance(coverage,list): issue('FIELD_TYPE_INVALID','narration_coverage','需要数组。'); coverage=[]
    covered=set()
    for i,n in enumerate(coverage):
        if not isinstance(n,dict): issue('NARRATION_COVERAGE_INVALID',f'narration_coverage[{i}]','覆盖项需要对象。'); continue
        ids=n.get('shot_ids')
        if isinstance(ids,list) and ids and isinstance(n.get('visual_evidence'),str) and n['visual_evidence'].strip() and all(isinstance(x,str) and x in shot_ids for x in ids): covered.add(n.get('source_id'))
        else: issue('NARRATION_COVERAGE_INVALID',f'narration_coverage[{i}]','镜头或可见证据无效。')
    if covered!=set(narration): issue('NARRATION_COVERAGE_MISSING','narration_coverage','旁白信息须映射到存在的镜头和可见证据；不能直接丢弃。')
    visible=m.get('visible_text')
    if not isinstance(visible,list): issue('FIELD_TYPE_INVALID','visible_text','需要数组。'); visible=[]
    text_ids=set()
    for i,t in enumerate(visible):
        at=f'visible_text[{i}]'
        if not isinstance(t,dict): issue('INVALID_TEXT',at,'文字项必须是对象。'); continue
        tid=t.get('id')
        if not isinstance(tid,str) or not tid.strip() or tid in text_ids: issue('TEXT_ID_INVALID',at,'文字事件ID缺失或重复。')
        else: text_ids.add(tid)
        language(t,at); bounded(t,at)
        if not isinstance(t.get('surface'),str) or not t['surface'].strip(): issue('TEXT_SURFACE_MISSING',at,'明确屏幕、标牌等承载面，不能无因浮字。')
    bindings=m.get('asset_bindings')
    if not isinstance(bindings,list): issue('FIELD_TYPE_INVALID','asset_bindings','需要数组。'); bindings=[]
    pairs=set()
    for i,b in enumerate(bindings):
        if not isinstance(b,dict) or b.get('type') not in {'character','scene','position','prop'} or any(not isinstance(b.get(k),str) or not b[k].strip() for k in ('referent','full_name')): issue('ASSET_BINDING_INVALID',f'asset_bindings[{i}]','资产类型、指代或全名无效。'); continue
        pair=(b['referent'],b['full_name'])
        if pair in pairs: issue('ASSET_BINDING_DUPLICATE',f'asset_bindings[{i}]','重复绑定。')
        pairs.add(pair)
    known_characters={b['referent'] for b in bindings if isinstance(b,dict) and b.get('type')=='character' and isinstance(b.get('referent'),str)}
    for eid,entry in meta.items():
        if isinstance(entry,dict) and isinstance(entry.get('speaker'),str) and entry['speaker'] not in known_characters:
            issue('DIALOGUE_SPEAKER_UNKNOWN','source_dialogue_meta.'+str(eid),'说话人没有对应的人物指代绑定。')
    return issues


def validate_prompt_text(text: str) -> list[dict[str,str]]:
    issues=[]
    if re.search(r'【(?:音色|声音|音频)引用】',text):
        issues.append({'code':'INDEPENDENT_VOICE_REFERENCE','at':'prompt','message':'最终提示词仍有独立声音引用模块。'})
    if re.search(r'@[^\s\n@]+\.(?:wav|mp3|aac|m4a)\b',text,re.I):
        issues.append({'code':'INDEPENDENT_AUDIO_BINDING','at':'prompt','message':'最终提示词存在独立音频文件@引用。'})
    for clause in re.split(r'[。；;\n]',text):
        if not re.search(r'(?:画面文字|文字|字层|屏幕|标题|标签).{0,35}后期(?:覆盖|处理|制作|替换)',clause): continue
        if re.search(r'(?:禁止|不得|不交给|不安排|不由|不做|无须|无需).{0,18}后期',clause): continue
        if re.search(r'可能|待定|考虑|视情况|或许',clause):
            issues.append({'code':'PROMPT_PARSE_UNCERTAIN','at':'prompt','message':'画面文字后期安排不明确，需人工确认。'})
            continue
        issues.append({'code':'SCREEN_TEXT_DEFERRED','at':'prompt','message':'最终提示词仍将画面文字转后期。'})
    return issues


def parse_prompt(text: str) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """仅解析排版规范第24节的单段结构。"""
    out: dict[str,Any]={'shots':[],'dialogue':[],'text':[],'assets':[]}
    q=[]
    def add(code,at,message='正文无法可靠解析。'): q.append({'code':code,'at':at,'message':message})
    if not isinstance(text,str) or not text.strip(): add('PROMPT_EMPTY','prompt','正文为空。'); return out,q
    lines=text.lstrip('\ufeff').replace('\r\n','\n').split('\n')
    heading=re.compile(r'【\s*生成段\s*(\d+)\s*[｜|]\s*(\d+(?:\.\d+)?)\s*秒\s*】')
    shot_re=re.compile(r'【\s*(\d+(?:\.\d+)?)\s*[–—－-]\s*(\d+(?:\.\d+)?)\s*s\s*[｜|]\s*镜头\s*(\d+)\s*】')
    heads=[(i,heading.fullmatch(line.strip())) for i,line in enumerate(lines,1) if line.strip().startswith('【生成段')]
    if len(heads)>1: add('MULTI_SEGMENT_PROMPT','prompt','请逐段检查。'); return out,q
    if not heads or not heads[0][1]: add('PROMPT_PARSE_UNCERTAIN','prompt.heading','段标题无法解析。')
    else: out['segment_number']=int(heads[0][1][1]); out['duration']=Decimal(heads[0][1][2])
    section=None; current=None
    asset_sections={'人物引用':'character','场景引用':'scene','站位图引用':'position','道具引用':'prop'}
    for i,line in enumerate(lines,1):
        value=line.strip()
        if not value: continue
        match=shot_re.fullmatch(value)
        if match:
            current={'start':Decimal(match[1]),'end':Decimal(match[2]),'number':int(match[3]),'line':i,'body':[]}
            out['shots'].append(current); section=None; continue
        if value.startswith('【') and value.endswith('】'):
            section=value[1:-1].strip()
            if section.startswith('生成段') or section in asset_sections or section in ('风格','场景','末态承接'): current=None
            elif '镜头' in section: add('PROMPT_PARSE_UNCERTAIN',f'prompt:{i}','镜头标签不支持。')
            continue
        if current is not None: current['body'].append(value)
        if re.search(r'(?:对白|发声|画面文字)\s*[〔\[]',value) and not ('对白〔' in value or '画面文字〔' in value):
            add('PROMPT_PARSE_UNCERTAIN',f'prompt:{i}','事件标记写法不支持。')
        if section in asset_sections:
            if value.count('@')!=1: add('PROMPT_PARSE_UNCERTAIN',f'prompt:{i}','资产引用行无法解析。')
            else:
                referent,full=(part.strip() for part in value.split('@',1))
                if not referent or not full: add('PROMPT_PARSE_UNCERTAIN',f'prompt:{i}','缺资产指代或全名。')
                else: out['assets'].append({'type':asset_sections[section],'referent':referent,'full_name':full})
        if '对白〔' in value:
            event=re.search(r'(现场对白|画外对白|对白)〔([^〕]+)〕',value)
            if not event: add('PROMPT_PARSE_UNCERTAIN',f'prompt:{i}','对白标记无法解析。'); continue
            eid=event[2]
            if '原文：' not in value and re.search('沿前镜|继续|连续到',value):
                out['dialogue'].append({'id':eid,'continuation':True,'shot':current,'line':i}); continue
            fields=re.search(r'：\s*([^；;]+)\s*[；;]\s*原文[：:]\s*[“"]([^”"]+)[”"]\s*[；;]\s*时间[：:]\s*(\d+(?:\.\d+)?)\s*[–—－-]\s*(\d+(?:\.\d+)?)s',value)
            if not fields or current is None: add('PROMPT_PARSE_UNCERTAIN',f'prompt:{i}','对白缺说话人、原文或时段。'); continue
            out['dialogue'].append({'id':eid,'speaker':fields[1].strip(),'text':fields[2],'start':Decimal(fields[3]),'end':Decimal(fields[4]),'kind':'offscreen_dialogue' if event[1]=='画外对白' else 'dialogue','shot':current,'line':i})
        if '画面文字〔' in value:
            event=re.search(r'画面文字〔([^〕]+)〕',value)
            if not event: add('PROMPT_PARSE_UNCERTAIN',f'prompt:{i}','文字标记无法解析。'); continue
            eid=event[1]
            if not re.search(r'[：:]\s*[“"]',value) and re.search('继续|维持|保持',value):
                out['text'].append({'id':eid,'continuation':True,'shot':current,'line':i}); continue
            fields=re.search(r'[：:]\s*[“"]([^”"]+)[”"]\s*[；;]\s*承载面[：:]\s*([^；;]+)\s*[；;]\s*时间[：:]\s*(\d+(?:\.\d+)?)\s*[–—－-]\s*(\d+(?:\.\d+)?)s',value)
            if not fields or current is None: add('PROMPT_PARSE_UNCERTAIN',f'prompt:{i}','文字缺原文、承载面或时段。'); continue
            out['text'].append({'id':eid,'text':fields[1],'surface':fields[2].strip(),'start':Decimal(fields[3]),'end':Decimal(fields[4]),'shot':current,'line':i})
    if not out['shots']: add('PROMPT_SHOTS_MISSING','prompt','正文没有可解析镜头。')
    return out,q


def validate_prompt_against_manifest(m: dict[str,Any], text: str) -> list[dict[str,str]]:
    parsed,q=parse_prompt(text)
    q+=validate_prompt_text(text)
    if not isinstance(m,dict) or not parsed['shots']: return q
    def add(code,at,message='正文与清单不一致。'): q.append({'code':code,'at':at,'message':message})
    if parsed.get('segment_number')!=m.get('segment_number'): add('PROMPT_SEGMENT_MISMATCH','prompt.heading')
    expected_duration=number_or_none(m.get('duration_seconds'))
    if parsed.get('duration')!=expected_duration: add('PROMPT_DURATION_MISMATCH','prompt.heading')
    ms=m.get('shots') if isinstance(m.get('shots'),list) else []; ps=parsed['shots']
    if len(ps)!=len(ms): add('PROMPT_SHOT_COUNT_MISMATCH','prompt.shots')
    previous=Decimal(0); numbers=set()
    for i,s in enumerate(ps):
        at=f'prompt:{s["line"]}'
        if s['number'] in numbers or s['number']!=i+1: add('PROMPT_SHOT_NUMBER_INVALID',at)
        numbers.add(s['number'])
        if s['end']<=s['start']: add('PROMPT_SHOT_INTERVAL_INVALID',at)
        if s['end']-s['start']>MAX_SHOT_SECONDS: add('PROMPT_SHOT_TOO_LONG',at,'一个连续镜头不得超过3秒。')
        if s['start']!=previous: add('PROMPT_TIMELINE_GAP_OR_OVERLAP',at)
        previous=s['end']
        if i<len(ms) and isinstance(ms[i],dict) and (s['number']!=ms[i].get('number') or s['start']!=number_or_none(ms[i].get('start')) or s['end']!=number_or_none(ms[i].get('end'))): add('PROMPT_SHOT_MISMATCH',at)
        body=' '.join(s['body'])
        if i>0 and not re.search('硬切|匹配剪接|叠化|切至|切换',body): add('PROMPT_CUT_UNCERTAIN',at,'未见明确切换。')
        if i>0 and i<len(ms) and isinstance(ms[i],dict) and ms[i].get('transition_in')=='hard_cut' and '硬切' not in body: add('PROMPT_CUT_MISMATCH',at)
    if parsed.get('duration') is not None and previous!=parsed['duration']: add('PROMPT_TIMELINE_END_MISMATCH','prompt.shots')
    assets={(x['type'],x['referent'],x['full_name']) for x in parsed['assets']}
    expected={(x['type'],x['referent'],x['full_name']) for x in m.get('asset_bindings',[]) if isinstance(x,dict) and all(isinstance(x.get(k),str) for k in ('type','referent','full_name'))} if isinstance(m.get('asset_bindings'),list) else set()
    if assets!=expected: add('PROMPT_ASSET_MISMATCH','prompt.assets')
    character={x['referent']:x['full_name'] for x in parsed['assets'] if x['type']=='character'}
    def compare(entries,items,kind):
        definitions={}; seen=[]
        for e in entries:
            eid=e['id']; at=f'prompt:{e["line"]}'
            if e.get('continuation'):
                if eid not in definitions or e['shot'] is None or not (e['shot']['start']<definitions[eid]['end'] and e['shot']['end']>definitions[eid]['start']): add('PROMPT_EVENT_CONTINUATION_INVALID',at)
                continue
            if eid in definitions: add('PROMPT_EVENT_DUPLICATE',at)
            definitions[eid]=e; seen.append(eid)
        expected_map={x.get('id'):x for x in items if isinstance(x,dict)}
        if set(definitions)!=set(expected_map): add('PROMPT_'+kind+'_EVENT_MISMATCH','prompt.'+kind)
        if kind=='DIALOGUE' and seen!=[x.get('id') for x in items if isinstance(x,dict)]: add('PROMPT_DIALOGUE_ORDER_MISMATCH','prompt.dialogue')
        for eid,e in definitions.items():
            x=expected_map.get(eid)
            if not x: continue
            at=f'prompt:{e["line"]}'
            if any(e.get(k)!=x.get(k) for k in (('text','kind') if kind=='DIALOGUE' else ('text','surface'))): add('PROMPT_'+kind+'_MISMATCH',at)
            if e['start']!=number_or_none(x.get('start')) or e['end']!=number_or_none(x.get('end')): add('PROMPT_'+kind+'_TIME_MISMATCH',at)
            if e['shot'] is None or not (e['shot']['start']<e['end'] and e['shot']['end']>e['start']): add('PROMPT_EVENT_SHOT_MISMATCH',at)
            if kind=='DIALOGUE':
                speaker=x.get('speaker')
                if not isinstance(speaker,str) or e.get('speaker')!=speaker+'@'+character.get(speaker,''): add('PROMPT_DIALOGUE_SPEAKER_MISMATCH',at)
    compare(parsed['dialogue'],m.get('dialogue_events',[]) if isinstance(m.get('dialogue_events'),list) else [],'DIALOGUE')
    compare(parsed['text'],m.get('visible_text',[]) if isinstance(m.get('visible_text'),list) else [],'TEXT')
    if not m.get('dialogue_events') and not re.search(r'无人声|无对白(?:和旁白)?',text): add('PROMPT_SILENCE_UNCERTAIN','prompt','无对白段须明确无人声。')
    for i,line in enumerate(text.replace('\r\n','\n').split('\n'),1):
        remaining=line
        for x in parsed['assets']:
            remaining=remaining.replace(x['referent']+'@'+x['full_name'],'')
        if '@' in remaining: add('PROMPT_ASSET_UNKNOWN',f'prompt:{i}')
    return q


def number_or_none(value: Any) -> Decimal | None:
    try:
        result=Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation,ValueError,TypeError): return None


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--prompt',type=Path)
    args=parser.parse_args()
    try:
        data=json.loads(args.manifest.read_text(encoding='utf-8-sig'),parse_constant=lambda x: (_ for _ in ()).throw(ValueError('非法数值 '+x)))
        prompt=args.prompt.read_text(encoding='utf-8-sig') if args.prompt else None
        manifest_issues=validate_manifest(data)
        prompt_issues=validate_prompt_against_manifest(data,prompt) if prompt is not None else []
        issues=manifest_issues+prompt_issues
    except (OSError,ValueError,TypeError) as exc:
        print(json.dumps({'manifest_passed':False,'prompt_checked':False,'prompt_consistency_passed':False,'static_contract_passed':False,'issues':[{'code':'INPUT_READ_OR_JSON_ERROR','at':'input','message':str(exc)}]},ensure_ascii=False)); return 2
    print(json.dumps({'manifest_passed':not manifest_issues,'prompt_checked':prompt is not None,'prompt_consistency_passed':not prompt_issues if prompt is not None else None,'static_contract_passed':not issues if prompt is not None else (False if manifest_issues else None),'issues':issues,
        'not_verified':['实际视频切点与单镜时长','音轨原文/说话人/语言','全部画面文字拼写与主语言','旁白画面是否完整承载原意','真实人物音频绑定']},ensure_ascii=False,indent=2))
    return 1 if issues else 0

if __name__=='__main__': raise SystemExit(main())
