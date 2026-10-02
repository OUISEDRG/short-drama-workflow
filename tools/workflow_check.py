"""离线静态合同检查。不会调用模型、联网、修改项目或认证成片。"""
from __future__ import annotations
import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sys
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
    if m.get('schema') not in {'JM-segment-check-v1','JM-segment-check-v2'}: issue('SCHEMA_MISSING','schema','需补充本段清单元数据。')
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
    if m.get('schema') == 'JM-segment-check-v2':
        issues += validate_g02_manifest(m)
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
    heading=re.compile(r'【\s*(?:生成段|分镜)\s*(\d+)\s*[｜|]\s*(?:(?:[^｜|]+)[｜|]\s*)?(?:实际总时长\s*)?(\d+(?:\.\d+)?)\s*(?:秒|s)\s*(?:[｜|][^】]+)?】')
    shot_re=re.compile(r'【\s*(\d+(?:\.\d+)?)\s*[–—－-]\s*(\d+(?:\.\d+)?)\s*s\s*[｜|]\s*镜头\s*(\d+)\s*】')
    heads=[(i,heading.fullmatch(line.strip())) for i,line in enumerate(lines,1) if re.match(r'【\s*(?:生成段|分镜)\s*\d',line.strip())]
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
            if section.startswith(('生成段','分镜')) or section in asset_sections or section in ('风格','场景','末态承接','段尾钩子/结果'): current=None
            elif '镜头' in section: add('PROMPT_PARSE_UNCERTAIN',f'prompt:{i}','镜头标签不支持。')
            continue
        if current is not None: current['body'].append(value)
        if re.search(r'(?:对白|发声|画面文字)\s*[〔\[]',value) and not ('对白〔' in value or '画面文字〔' in value):
            add('PROMPT_PARSE_UNCERTAIN',f'prompt:{i}','事件标记写法不支持。')
        if section in asset_sections:
            if value.count('@')==0 and heads and heads[0][1] and '分镜' in lines[heads[0][0]-1]:
                out['assets'].append({'type':asset_sections[section],'referent':value,'full_name':value})
            elif value.count('@')!=1: add('PROMPT_PARSE_UNCERTAIN',f'prompt:{i}','资产引用行无法解析。')
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
            out['dialogue'].append({'id':eid,'speaker':fields[1].strip(),'text':fields[2],'start':Decimal(fields[3]),'end':Decimal(fields[4]),'kind':'offscreen_dialogue' if event[1]=='画外对白' else 'dialogue','shot':current,'line':i,'literal_span':(fields.start(2)-1,fields.end(2)+1)})
        if '画面文字〔' in value:
            event=re.search(r'画面文字〔([^〕]+)〕',value)
            if not event: add('PROMPT_PARSE_UNCERTAIN',f'prompt:{i}','文字标记无法解析。'); continue
            eid=event[1]
            if not re.search(r'[：:]\s*[“"]',value) and re.search('继续|维持|保持',value):
                out['text'].append({'id':eid,'continuation':True,'shot':current,'line':i}); continue
            fields=re.search(r'[：:]\s*[“"]([^”"]+)[”"]\s*[；;]\s*承载面[：:]\s*([^；;]+)\s*[；;]\s*时间[：:]\s*(\d+(?:\.\d+)?)\s*[–—－-]\s*(\d+(?:\.\d+)?)s',value)
            if not fields or current is None: add('PROMPT_PARSE_UNCERTAIN',f'prompt:{i}','文字缺原文、承载面或时段。'); continue
            out['text'].append({'id':eid,'text':fields[1],'surface':fields[2].strip(),'start':Decimal(fields[3]),'end':Decimal(fields[4]),'shot':current,'line':i,'literal_span':(fields.start(1)-1,fields.end(1)+1)})
    if not out['shots']: add('PROMPT_SHOTS_MISSING','prompt','正文没有可解析镜头。')
    return out,q


def validate_prompt_against_manifest(m: dict[str,Any], text: str, parsed=None) -> list[dict[str,str]]:
    if parsed is None: parsed,q=parse_prompt(text)
    else: q=list(parsed.get('parse_issues', []))
    q+=validate_prompt_text(text)
    v2=isinstance(m,dict) and m.get('schema')=='JM-segment-check-v2'
    if is_current(m):
        prepare_execution_view(m,parsed,text)
        q += shot_language.validate_camera_text(m,parsed)
    if v2: q += validate_g02_prompt(m,text,parsed)[0]
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
    if ( {(t,n) for t,r,n in assets} != {(t,n) for t,r,n in expected} if v2 else assets!=expected): add('PROMPT_ASSET_MISMATCH','prompt.assets')
    character={x['referent']:x['full_name'] for x in parsed['assets'] if x['type']=='character'}
    if v2: character={x.get('referent'):x.get('full_name') for x in m.get('asset_bindings',[]) if isinstance(x,dict) and x.get('type')=='character'}
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
                if not isinstance(speaker,str) or e.get('speaker')!=(character.get(speaker,'') if v2 else speaker+'@'+character.get(speaker,'')): add('PROMPT_DIALOGUE_SPEAKER_MISMATCH',at)
    compare(parsed['dialogue'],m.get('dialogue_events',[]) if isinstance(m.get('dialogue_events'),list) else [],'DIALOGUE')
    compare(parsed['text'],m.get('visible_text',[]) if isinstance(m.get('visible_text'),list) else [],'TEXT')
    if not m.get('dialogue_events') and not re.search(r'无人声|无对白(?:和旁白)?',text): add('PROMPT_SILENCE_UNCERTAIN','prompt','无对白段须明确无人声。')
    for i,line in enumerate(text.replace('\r\n','\n').split('\n'),1):
        remaining=line
        for x in parsed['assets']:
            remaining=remaining.replace(x['referent']+'@'+x['full_name'],'')
        if '@' in remaining: add('PROMPT_ASSET_UNKNOWN',f'prompt:{i}')
    return q


G02_PROFILE = 'g02_cinematic_fullname_v1'  # 历史诊断仍受原合同检查
try:
    from . import shot_language_check as shot_language
except ImportError:
    import shot_language_check as shot_language
CURRENT_PROFILE = shot_language.CURRENT_PROFILE
SHOT_FUNCTIONS = {'establish','advance','reaction','evidence','relationship','reveal','result','transition','hook','spatial_reset'}
SECTION_LABELS = {'本分镜资产全名锁','本镜资产全名锁','人物引用','场景引用','站位图引用','道具引用','风格','场景','观看任务','视觉递进','末态承接','段尾钩子/结果'}


def filled(value: Any) -> bool:
    return isinstance(value,str) and bool(value.strip())


def is_current(m):
    return isinstance(m,dict) and isinstance(m.get('quality'),dict) and m['quality'].get('profile')==CURRENT_PROFILE


def masked_literal_lines(m, parsed, text):
    """只屏蔽逐字核实的原文；同一行坐标聚合后倒序处理，保留隔断。"""
    lines=[line.strip() for line in text.replace('\r\n','\n').split('\n')]
    spans={}
    for entries,key in [(parsed.get('dialogue',[]),'dialogue_events'),(parsed.get('text',[]),'visible_text')]:
        authoritative={x.get('id'):x for x in m.get(key,[]) if isinstance(x,dict) and filled(x.get('id'))} if isinstance(m.get(key),list) else {}
        for event in entries:
            source=authoritative.get(event.get('id'))
            if source and not event.get('continuation') and event.get('text')==source.get('text'):
                index=event['line']-1
                spans.setdefault(index,[]).append(event['literal_span'])
    for index,ranges in spans.items():
        if not 0<=index<len(lines): continue
        for a,b in sorted(set(ranges),reverse=True): lines[index]=lines[index][:a]+'\ufffc'+lines[index][b:]
    return lines


def eligible_lines(text):
    """保持行号，排除注释、代码围栏、未知附录和交付说明。"""
    text=re.sub(r'<!--[\s\S]*?(?:-->|\Z)',lambda m:re.sub(r'[^\n]',' ',m[0]),text.replace('\r\n','\n'))
    lines=text.split('\n'); fence=None; blocked=False; result=[]
    allowed=SECTION_LABELS
    for line in lines:
        v=line.strip()
        if v.startswith('>'): result.append(''); continue  # 引用说明不是模型执行正文
        marker=re.match(r'^\s*(`{3,}|~{3,})(.*)$',line)
        if fence is not None:
            if marker and marker[1][0]==fence[0] and len(marker[1])>=fence[1] and not marker[2].strip(): fence=None
            result.append(''); continue
        if marker:
            fence=(marker[1][0],len(marker[1])); result.append(''); continue
        head=re.fullmatch(r'【([^】]+)】',v)
        if re.match(r'^(?:交付说明[：:]|#{1,6}\s)',v): blocked=True
        if head and head[1] not in allowed and not re.match(r'(?:分镜|生成段)\s*\d|\d+(?:\.\d+)?\s*[–—－-]',head[1]): blocked=True
        result.append('' if blocked else line)
    return result


def prepare_execution_view(m,parsed,text):
    masked=masked_literal_lines(m,parsed,text); eligible=eligible_lines('\n'.join(masked))
    for i,shot in enumerate(parsed.get('shots',[])):
        start=shot['line']; end=parsed['shots'][i+1]['line']-1 if i+1<len(parsed['shots']) else len(eligible)
        body=[]
        for j in range(start,end):
            if j>=len(eligible) or not eligible[j].strip(): continue
            if eligible[j].strip()=='【本镜资产全名锁】': continue
            if re.fullmatch(r'【[^】]+】',eligible[j].strip()): break
            body.append(eligible[j])
        shot['execution_body']='\n'.join(body)
    parsed['execution_text']='\n'.join(eligible)
    return parsed


def validate_g02_manifest(m: dict[str,Any]) -> list[dict[str,str]]:
    issues=[]
    def add(code,at,message): issues.append({'code':code,'at':at,'message':message})
    quality=m.get('quality')
    if not isinstance(quality,dict): quality={}
    if quality.get('profile') not in (G02_PROFILE,CURRENT_PROFILE):
        add('QUALITY_PROFILE_INVALID','quality.profile','v2清单必须声明正式G02 profile。')
    if is_current(m): issues += shot_language.validate_camera_fields(m)
    for key,code in [('viewing_task','VIEWING_TASK_MISSING'),('start_state','SEGMENT_START_STATE_MISSING'),('relationship_change','RELATIONSHIP_CHANGE_MISSING'),('end_state','SEGMENT_END_STATE_MISSING')]:
        if not filled(quality.get(key)): add(code,'quality.'+key,'必须填写可观察的导演结果。')
    progression=quality.get('visual_progression')
    if not isinstance(progression,list) or len(progression)<2 or not all(filled(x) for x in progression):
        add('VISUAL_PROGRESSION_MISSING','quality.visual_progression','必须至少两个有效信息阶段。')
    duration=number_or_none(m.get('duration_seconds')); low=Decimal(20); high=Decimal(30)
    exception=quality.get('segment_duration_exception')
    if exception is not None:
        valid=isinstance(exception,dict) and filled(exception.get('reason')) and filled(exception.get('source'))
        a=number_or_none(exception.get('min')) if isinstance(exception,dict) else None
        b=number_or_none(exception.get('max')) if isinstance(exception,dict) else None
        if not valid or a is None or b is None or a<=0 or b<a:
            add('SEGMENT_EXCEPTION_INVALID','quality.segment_duration_exception','例外必须记录有效min/max、reason和具体source，不接受静默降低标准。')
        else: low,high=a,b
    if duration is not None:
        if duration<low: add('PROMPT_SEGMENT_TOO_SHORT','duration_seconds',f'分镜须至少{low}秒。')
        if duration>high: add('PROMPT_SEGMENT_TOO_LONG','duration_seconds',f'分镜须不超过{high}秒。')
    shots=m.get('shots') if isinstance(m.get('shots'),list) else []
    functions=set()
    for i,s in enumerate(shots):
        if not isinstance(s,dict): continue
        if not filled(s.get('function')) or s['function'] not in SHOT_FUNCTIONS: add('SHOT_FUNCTION_MISSING',f'shots[{i}].function','镜头须有合法主要功能。')
        else: functions.add(s['function'])
        for key in ('new_information','visible_evidence','cut_trigger','end_state'):
            if not filled(s.get(key)): add('SHOT_QUALITY_FIELD_MISSING',f'shots[{i}].{key}','镜头账本字段不得空缺。')
    if len(functions)<3:
        review=quality.get('function_diversity_exception')
        if not isinstance(review,dict) or not all(filled(review.get(k)) for k in ('reason','source','director_review')):
            add('FLAT_SHOT_DESIGN','shots','普通分镜至少3类镜头功能；特殊动作段必须附导演审查及例外依据。')
    bindings=m.get('asset_bindings') if isinstance(m.get('asset_bindings'),list) else []
    names=[b.get('full_name') for b in bindings if isinstance(b,dict)]
    referents=[b.get('referent') for b in bindings if isinstance(b,dict)]
    if len(names)!=len(set(str(x) for x in names)) or len(referents)!=len(set(str(x) for x in referents)):
        add('ASSET_IDENTITY_AMBIGUOUS','asset_bindings','全名与实例指代须一一对应，不允许同名多个身份。')
    for i,b in enumerate(bindings):
        if not isinstance(b,dict): continue
        if b.get('status')!='verified' or re.search('计划占位|待确认|请选择',str(b.get('full_name',''))):
            add('ASSET_NOT_VERIFIED',f'asset_bindings[{i}]','计划占位资产只能保留计划稿，不能宣称生成准备就绪。')
        if not isinstance(b.get('aliases',[]),list) or not all(filled(x) for x in b.get('aliases',[])):
            add('ASSET_ALIAS_LIST_INVALID',f'asset_bindings[{i}].aliases','别名列表需要非空字符串。')
    for i,s in enumerate(shots):
        if not isinstance(s,dict): continue
        used=s.get('asset_full_names')
        if not isinstance(used,list) or not used or any(not filled(x) or x not in names for x in used):
            add('SHOT_ASSET_BINDING_INVALID',f'shots[{i}].asset_full_names','镜头必须列出实际使用的已绑定资产全名。')
    return issues


def prompt_sections(text: str) -> dict[str,str]:
    sections={}; current=None
    for line in text.splitlines():
        match=re.fullmatch(r'【([^】]+)】',line.strip())
        if match:
            current=match[1]; sections.setdefault(current,[])
        elif current: sections[current].append(line)
    return {k:'\n'.join(v).strip() for k,v in sections.items()}


def count_detail(text: str, names: list[str]) -> dict[str,int]:
    # 计正文，不计标题、资产区、导演方案或交付说明；所有全名重复出现均剔除。
    text=re.split(r'(?m)^\s*(?:交付说明[：:]|##\s+[C-Z]\.)',text,maxsplit=1)[0]
    raw='\n'.join(line for line in text.splitlines() if not re.fullmatch(r'【[^】]+】',line.strip()))
    stripped=raw
    for name in sorted(set(names),key=len,reverse=True): stripped=stripped.replace(name,'')
    removed=len(raw)-len(stripped)
    stripped=stripped.replace('`','')
    return {'raw_chars':len(raw),'asset_name_chars_removed':removed,
            'detail_cjk_after_asset_strip':len(re.findall(r'[\u3400-\u4dbf\u4e00-\u9fff\U00020000-\U0002fa1f]',stripped))}


def validate_g02_prompt(m: dict[str,Any], text: str, parsed=None):
    if parsed is None: parsed,_=parse_prompt(text)
    issues=[]
    def add(code,at,message): issues.append({'code':code,'at':at,'message':message})
    bindings=[b for b in m.get('asset_bindings',[]) if isinstance(b,dict)] if isinstance(m.get('asset_bindings'),list) else []
    names=[b['full_name'] for b in bindings if filled(b.get('full_name'))]
    quality=m.get('quality') if isinstance(m.get('quality'),dict) else {}
    sections=prompt_sections(text)
    lock=sections.get('本分镜资产全名锁','')
    if not lock or any(n not in lock for n in names): add('SEGMENT_ASSET_LOCK_MISSING','prompt.assets','分镜锁必须列出本分镜所有资产完整名。')
    for label,key,code in [('观看任务','viewing_task','VIEWING_TASK_MISSING'),('视觉递进','visual_progression','VISUAL_PROGRESSION_MISSING'),('末态承接','end_state','SEGMENT_END_STATE_MISSING')]:
        body=sections.get(label,'')
        if not body: add(code,'prompt.'+label,'执行正文缺少必填导演字段。')
        value=quality.get(key)
        values=value if isinstance(value,list) else [value]
        expected=' → '.join(value) if isinstance(value,list) and all(filled(v) for v in value) else value
        if filled(expected) and body.strip()!=expected.strip(): add('PROMPT_QUALITY_MISMATCH','prompt.'+label,'正文导演结果与清单内容/顺序不一致。')
    if not sections.get('段尾钩子/结果'): add('SEGMENT_END_RESULT_MISSING','prompt.end_hook','段尾必须显示钩子或明确结果。')
    shots=m.get('shots') if isinstance(m.get('shots'),list) else []
    for i,s in enumerate(shots):
        if not isinstance(s,dict) or i>=len(parsed['shots']): continue
        body='\n'.join(parsed['shots'][i]['body'])
        if type(s.get('asset_lock_required')) is not bool: add('SHOT_LOCK_POLICY_INVALID',f'prompt.shots[{i}]','须显式判定本镜是否高风险并需要资产锁。')
        if s.get('asset_lock_required') is True:
            marker='【本镜资产全名锁】'
            # 解析器不把标签加入body；用原始镜头区间定位。
            start=parsed['shots'][i]['line']-1
            end=parsed['shots'][i+1]['line']-1 if i+1<len(parsed['shots']) else len(text.splitlines())
            part='\n'.join(text.splitlines()[start:end])
            lock_body=prompt_sections(part).get('本镜资产全名锁','')
            if marker not in part or any(not filled(n) or n not in lock_body for n in s.get('asset_full_names',[]) if isinstance(s.get('asset_full_names'),list)):
                add('SHOT_ASSET_LOCK_MISSING',f'prompt.shots[{i}]','高风险镜头须显式列出本镜所有实际使用资产。')
    counts=count_detail('\n'.join(eligible_lines(text)) if is_current(m) else text,names)
    minimum=2501
    override=quality.get('detail_override')
    if override is not None:
        if not isinstance(override,dict) or type(override.get('min_cjk')) is not int or override.get('min_cjk',0)<1 or not all(filled(override.get(k)) for k in ('reason','source')):
            add('DETAIL_OVERRIDE_INVALID','quality.detail_override','字数覆盖必须记录正整数min_cjk、reason、source。')
        else: minimum=override['min_cjk']
    if counts['detail_cjk_after_asset_strip']<minimum:
        add('PROMPT_DETAIL_TOO_SHORT','prompt',f"去资产名后{counts['detail_cjk_after_asset_strip']}汉字，要求至少{minimum}。")
    execution_lines=masked_literal_lines(m,parsed,text)
    if is_current(m):
        execution_lines=['' if line in {'【'+label+'】' for label in SECTION_LABELS} else line for line in execution_lines]
    execution='\n'.join(execution_lines)
    for n in sorted(set(names),key=len,reverse=True): execution=execution.replace(n,'')
    aliases={'女主','女配','男主','男配','男二','女孩','男人','女人','她','他','他们','她们','两人','双方','对方','当前人物','这个角色','当前场景','当前空间','这个场景','原场景','这里','房间里','同上'}
    for b in bindings:
        if filled(b.get('referent')): aliases.add(b['referent'])
        if isinstance(b.get('aliases'),list): aliases.update(x for x in b['aliases'] if filled(x))
    # 不在asset段之外使用角色叙事名；顶部也必须只有全名，@简写不作为新稿语法。
    for alias in sorted(aliases,key=len,reverse=True):
        pattern=re.escape(alias)
        if alias=='他': pattern=r'(?<!其)他'
        if alias.isascii() and re.search(r'\w',alias): pattern=r'(?<!\w)'+pattern+r'(?!\w)'
        if re.search(pattern,execution): add('PROMPT_ASSET_ALIAS_FORBIDDEN','prompt',f'执行正文出现资产别名/模糊指代：{alias}')
    if '@' in execution: add('ASSET_FULL_NAME_REQUIRED','prompt','G02执行身份仅使用完整绑定名，不输出指代@简称。')
    if re.search(r'(?:人物|场景|道具|Top)/[^\s`，。；；“”"【】]+\.(?:png|jpg|jpeg|webp)(?![A-Za-z0-9_])',execution,re.I):
        add('PROMPT_ASSET_UNKNOWN','prompt','正文调用了未列入绑定映射的资产文件名。')
    if any(x['code']=='PROMPT_ASSET_ALIAS_FORBIDDEN' for x in issues): add('G02_ASSET_IDENTITY_GATE_FAILED','prompt','全程资产身份门禁失败。')
    report={'segment':m.get('segment_number'),'duration':m.get('duration_seconds'),**counts,
            'detail_min_cjk':minimum,'shot_function_count':len({s['function'] for s in shots if isinstance(s,dict) and filled(s.get('function'))}),
            'viewing_task':bool(sections.get('观看任务')),'visual_progression':bool(sections.get('视觉递进')),
            'end_state':bool(sections.get('末态承接')),'full_asset_lock':bool(lock),'result':'FAIL' if issues else 'PASS'}
    return issues,report


def parse_episode_prompt(text: str):
    """截取B区，按分镜拆分；不让A区计数或豁免正文错误。"""
    match=re.search(r'^##\s+B\.\s*本集唯一视频Prompt\s*$',text,re.M)
    if match: text=text[match.end():]
    text=re.split(r'^##\s+(?:C\.|[A-Z]\.)\s',text,maxsplit=1,flags=re.M)[0]
    starts=list(re.finditer(r'^【\s*(?:分镜|生成段)\s*\d[^\n]*$',text,re.M))
    return [text[m.start():starts[i+1].start() if i+1<len(starts) else len(text)].strip() for i,m in enumerate(starts)]


def validate_delivery(data: Any, prompt: str | None, *, required_profile: str | None=None):
    manifests=[]; prompt_issues=[]; reports=[]; warnings=[]
    episode=isinstance(data,dict) and data.get('schema')=='JM-episode-check-v1'
    segments=data.get('segments') if episode else [data]
    if not isinstance(segments,list) or not segments:
        return ([{'code':'EPISODE_SEGMENTS_MISSING','at':'segments','message':'整集清单需要非空segments数组。'}],[],[],[])
    current=required_profile==CURRENT_PROFILE or any(is_current(m) for m in segments)
    if required_profile is not None:
        for i,m in enumerate(segments):
            if required_profile!=CURRENT_PROFILE or not isinstance(m,dict) or m.get('schema')!='JM-segment-check-v2' or not is_current(m):
                manifests.append({'code':'CURRENT_PROFILE_REQUIRED','at':f'segments[{i}].quality.profile','message':'本次正式交付要求当前v2 profile与v2段清单，旧版仅作历史诊断。'})
    if current and episode and prompt is not None and len(re.findall(r'^##\s+B\.\s*本集唯一视频Prompt\s*$',prompt,re.M))!=1:
        prompt_issues.append({'code':'PROMPT_EXECUTION_SECTION_REQUIRED','at':'prompt','message':'当前整集交付必须且只能有一个规范B区。'})
    parts=parse_episode_prompt(prompt) if prompt is not None and episode else ([prompt] if prompt is not None else [])
    if prompt is not None and len(parts)!=len(segments): prompt_issues.append({'code':'PROMPT_SEGMENT_COUNT_MISMATCH','at':'prompt','message':'分镜数量必须与清单一致。'})
    ids=set(); parsed_segments=[]
    for i,m in enumerate(segments):
        manifests+=validate_manifest(m)
        if not isinstance(m,dict): continue
        if episode:
            if m.get('schema')!='JM-segment-check-v2': manifests.append({'code':'EPISODE_SEGMENT_SCHEMA_INVALID','at':f'segments[{i}].schema','message':'整集G02仅接受v2分镜，旧v1用单段历史诊断。'})
            sid=m.get('segment_id')
            if m.get('segment_number')!=i+1 or not filled(sid) or sid in ids:
                manifests.append({'code':'EPISODE_SEGMENT_ORDER_INVALID','at':f'segments[{i}]','message':'整集分镜须连续编号且ID唯一。'})
            if filled(sid): ids.add(sid)
        if prompt is None and m.get('schema')=='JM-segment-check-v2':
            prompt_issues.append({'code':'G02_PROMPT_REQUIRED','at':f'segments[{i}]','message':'正式G02必须同时检查实际正文。'})
        if i<len(parts):
            parsed,parse_issues=parse_prompt(parts[i]); parsed['parse_issues']=parse_issues
            if isinstance(m,dict): prepare_execution_view(m,parsed,parts[i])
            parsed_segments.append(parsed)
            checks=validate_prompt_against_manifest(m,parts[i],parsed); prompt_issues+=checks
            if m.get('schema')=='JM-segment-check-v2':
                report=validate_g02_prompt(m,parts[i],parsed)[1]
                report['result']='FAIL' if checks or validate_manifest(m) else 'PASS'; reports.append(report)
    if episode:
        if current:
            manifests += shot_language.validate_connections(data,parsed_segments)
            bodies=[shot_language.normalized(s.get('execution_body','')) for p in parsed_segments for s in p.get('shots',[])]
            for si,m in enumerate(segments):
                if not isinstance(m,dict) or not isinstance(m.get('shots'),list): continue
                for ki,s in enumerate(m['shots']):
                    c=s.get('camera') if isinstance(s,dict) else None
                    phrase=shot_language.normalized(c.get('execution')) if isinstance(c,dict) else ''
                    if phrase and sum(body.count(phrase) for body in bodies)>1:
                        prompt_issues.append({'code':'CAMERA_EXECUTION_DUPLICATED','at':f'segments[{si}].shots[{ki}]','message':'摄影机执行句在整集B区镜头中重复。'})
        source=data.get('time_source')
        coverage_ok=isinstance(source,dict) and source.get('kind') in {'user','srt'}
        begin=number_or_none(source.get('range_start')) if isinstance(source,dict) else None
        finish=number_or_none(source.get('range_end')) if isinstance(source,dict) else None
        if begin is None or finish is None or begin<0 or finish<=begin: coverage_ok=False
        previous=begin
        for m in segments:
            item=m.get('time_source') if isinstance(m,dict) else None
            a=number_or_none(item.get('range_start')) if isinstance(item,dict) else None
            b=number_or_none(item.get('range_end')) if isinstance(item,dict) else None
            if not isinstance(item,dict) or not isinstance(source,dict) or item.get('kind')!=source.get('kind') or a is None or b is None or a!=previous or b<=a:
                coverage_ok=False
            if isinstance(item,dict) and isinstance(source,dict) and source.get('kind')=='user' and item.get('seconds')!=source.get('seconds'): coverage_ok=False
            if isinstance(item,dict) and isinstance(source,dict) and item.get('source_ref')!=source.get('source_ref'): coverage_ok=False
            previous=b
        if previous!=finish: coverage_ok=False
        languages={m.get('main_language') for m in segments if isinstance(m,dict) and filled(m.get('main_language'))}
        if len(languages)!=1: coverage_ok=False
        if not coverage_ok: manifests.append({'code':'EPISODE_SOURCE_COVERAGE_INVALID','at':'time_source','message':'整集与逐段须同来源、同主语言并连续覆盖已确认绝对区间，不得缺口/重叠。'})
    if episode and len(parts)>1:
        from difflib import SequenceMatcher
        for i in range(len(parts)):
            for j in range(i):
                a=re.sub(r'【[^】]+】','',parts[i]); b=re.sub(r'【[^】]+】','',parts[j])
                for m in segments:
                    if not isinstance(m,dict): continue
                    for item in m.get('asset_bindings',[]) if isinstance(m.get('asset_bindings'),list) else []:
                        if isinstance(item,dict) and filled(item.get('full_name')): a=a.replace(item['full_name'],''); b=b.replace(item['full_name'],'')
                if SequenceMatcher(None,a,b,autojunk=False).ratio()>=0.8:
                    warnings.append({'code':'BOILERPLATE_DUPLICATION_WARNING','at':f'segments[{j},{i}]','message':'去资产名正文相似度≥0.8，须语义审查重复模板。'})
    return manifests,prompt_issues,reports,warnings


def number_or_none(value: Any) -> Decimal | None:
    try:
        result=Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation,ValueError,TypeError): return None


def main() -> int:
    if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--prompt',type=Path)
    parser.add_argument('--require-profile',help='正式交付必须显式要求g02_cinematic_fullname_v2；缺省仅为诊断。')
    args=parser.parse_args()
    try:
        data=json.loads(args.manifest.read_text(encoding='utf-8-sig'),parse_constant=lambda x: (_ for _ in ()).throw(ValueError('非法数值 '+x)))
        prompt=args.prompt.read_text(encoding='utf-8-sig') if args.prompt else None
        manifest_issues,prompt_issues,quality,warnings=validate_delivery(data,prompt,required_profile=args.require_profile)
        issues=manifest_issues+prompt_issues
    except (OSError,ValueError,TypeError) as exc:
        print(json.dumps({'manifest_passed':False,'prompt_checked':False,'prompt_consistency_passed':False,'static_contract_passed':False,'required_profile':args.require_profile,'current_contract_passed':False,'sequence_scope':'unknown','issues':[{'code':'INPUT_READ_OR_JSON_ERROR','at':'input','message':str(exc)}]},ensure_ascii=False)); return 2
    print(json.dumps({'manifest_passed':not manifest_issues,'prompt_checked':prompt is not None,'prompt_consistency_passed':not prompt_issues if prompt is not None else None,'static_contract_passed':not issues if prompt is not None else (False if issues else None),'issues':issues,
        'required_profile':args.require_profile,'current_contract_passed':args.require_profile==CURRENT_PROFILE and prompt is not None and not issues,
        'sequence_scope':'episode' if isinstance(data,dict) and data.get('schema')=='JM-episode-check-v1' else 'segment',
        'quality_contract':quality,'warnings':warnings,
        'not_verified':['实际视频切点与单镜时长','音轨原文/说话人/语言','全部画面文字拼写与主语言','旁白画面是否完整承载原意','真实人物音频绑定','导演质量语义审核']},ensure_ascii=False,indent=2))
    return 1 if issues else 0

if __name__=='__main__': raise SystemExit(main())
