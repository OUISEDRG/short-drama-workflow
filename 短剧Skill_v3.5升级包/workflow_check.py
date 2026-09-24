"""离线静态合同检查。不会调用模型、联网、修改项目或认证成片。"""
from __future__ import annotations
import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from typing import Any


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
    if not isinstance(source,dict): source={}
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
    shots=m.get('shots',[])
    if not isinstance(shots,list): shots=[]
    if not shots: issue('SHOTS_MISSING','shots','必须列出真实连续镜头。')
    shot_ids: set[str]=set(); previous=Decimal(0)
    for i,s in enumerate(shots):
        at=f'shots[{i}]'
        if not isinstance(s,dict): issue('INVALID_SHOT',at,'镜头必须是对象。'); continue
        sid=s.get('id')
        if not isinstance(sid,str) or not sid: issue('SHOT_ID_MISSING',at,'镜头需要稳定编号。')
        elif sid in shot_ids: issue('CONTINUOUS_SHOT_REUSED',at,'不能重复一个连续镜头编号来拆分其时长。')
        else: shot_ids.add(sid)
        a,b=interval(s,at)
        if a is not None and b is not None:
            if b-a>Decimal('5'): issue('SHOT_TOO_LONG',at,'一个连续镜头不得超过5秒。')
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
        # 此检查只能发现明显异文字体系；不能识别所有英文、西语错词或伪词。
        if base_lang in {'es','en','pt','fr','de','it'} and re.search(r'[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]',text):
            issue('FOREIGN_SCRIPT',at,'主语言为拉丁字母语言时出现中日韩字符。')
    def bounded(item: dict[str,Any],at: str) -> None:
        a,b=interval(item,at)
        if duration is not None and b is not None and b>duration:
            issue('EVENT_OUT_OF_RANGE',at,'声音或可见文字超出本段时长。')
    src=m.get('source_dialogue',{})
    if not isinstance(src,dict): src={}; issue('SOURCE_DIALOGUE_INVALID','source_dialogue','权威对白必须以事件ID映射原文。')
    events=m.get('dialogue_events',[])
    if not isinstance(events,list): events=[]
    seen: list[str]=[]
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
        if not e.get('speaker'): issue('SPEAKER_MISSING',at,'正常对白须明确发声者。')
        if eid in src and src[eid]!=e.get('text'): issue('DIALOGUE_CHANGED',at,'不得改写权威对白。')
        language(e,at); bounded(e,at)
    if set(seen)!=set(src): issue('DIALOGUE_MISSING_OR_ADDED','dialogue_events','权威对白有遗漏或新增。')
    if list(dict.fromkeys(seen))!=list(src): issue('DIALOGUE_ORDER_CHANGED','dialogue_events','对白顺序与权威清单不同。')
    narration=m.get('source_narration',{})
    if not isinstance(narration,dict): narration={}
    coverage=m.get('narration_coverage',[])
    if not isinstance(coverage,list): coverage=[]
    covered=set()
    for i,n in enumerate(coverage):
        if not isinstance(n,dict): continue
        if n.get('visual_evidence') and n.get('shot_ids') and all(x in shot_ids for x in n['shot_ids']): covered.add(n.get('source_id'))
    if covered!=set(narration): issue('NARRATION_COVERAGE_MISSING','narration_coverage','旁白信息须映射到存在的镜头和可见证据；不能直接丢弃。')
    visible=m.get('visible_text',[])
    if not isinstance(visible,list): visible=[]
    for i,t in enumerate(visible):
        at=f'visible_text[{i}]'
        if not isinstance(t,dict): issue('INVALID_TEXT',at,'文字项必须是对象。'); continue
        language(t,at); bounded(t,at)
        if not t.get('surface'): issue('TEXT_SURFACE_MISSING',at,'明确屏幕、标牌等承载面，不能无因浮字。')
    return issues


def validate_prompt_text(text: str) -> list[dict[str,str]]:
    issues=[]
    if re.search(r'【(?:音色|声音|音频)引用】',text):
        issues.append({'code':'INDEPENDENT_VOICE_REFERENCE','at':'prompt','message':'最终提示词仍有独立声音引用模块。'})
    if re.search(r'@[^\s\n@]+\.(?:wav|mp3|aac|m4a)\b',text,re.I):
        issues.append({'code':'INDEPENDENT_AUDIO_BINDING','at':'prompt','message':'最终提示词存在独立音频文件@引用。'})
    if re.search(r'(?:文字|字层|屏幕|标题|标签).{0,25}(?:后期覆盖|后期处理|后期制作|后期替换)',text):
        issues.append({'code':'SCREEN_TEXT_DEFERRED','at':'prompt','message':'最终提示词仍将画面文字转后期。'})
    return issues


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--prompt',type=Path)
    args=parser.parse_args()
    try:
        data=json.loads(args.manifest.read_text(encoding='utf-8-sig'))
        issues=validate_manifest(data)
        if args.prompt: issues+=validate_prompt_text(args.prompt.read_text(encoding='utf-8-sig'))
    except (OSError,ValueError,TypeError) as exc:
        print(json.dumps({'ok':False,'error':str(exc)},ensure_ascii=False)); return 2
    print(json.dumps({'static_contract_passed':not issues,'issues':issues,
        'not_verified':['实际视频切点与单镜时长','音轨原文/说话人/语言','全部画面文字拼写与主语言','旁白画面是否完整承载原意','真实人物音频绑定']},ensure_ascii=False,indent=2))
    return 1 if issues else 0

if __name__=='__main__': raise SystemExit(main())
