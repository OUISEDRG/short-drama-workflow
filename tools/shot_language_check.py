"""镜头语言静态合同：复用主检查器解析结果，不认证导演语义或样片。"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
import re
from typing import Any

CURRENT_PROFILE = 'g02_cinematic_fullname_v2'


def filled(value):
    return isinstance(value, str) and bool(value.strip())


def normalized(value):
    return re.sub(r'\s+', '', value) if isinstance(value, str) else ''


def seconds(value):
    try:
        d = Decimal(str(value))
        return d if not isinstance(value, bool) and d.is_finite() and d >= 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def validate_camera_fields(segment: Any) -> list[dict]:
    issues = []
    def add(code, at, message): issues.append(dict(code=code, at=at, message=message))
    shots = segment.get('shots') if isinstance(segment, dict) else None
    if not isinstance(shots, list) or not shots:
        add('CAMERA_CONTRACT_MISSING', 'shots', '需要非空镜头数组。'); return issues
    for i, shot in enumerate(shots):
        at = f'shots[{i}].camera'
        camera = shot.get('camera') if isinstance(shot, dict) else None
        if not isinstance(camera, dict) or not camera:
            add('CAMERA_CONTRACT_MISSING', at, '每镜须主动决定摄影机工作方式。'); continue
        kind = camera.get('kind')
        if not isinstance(kind, str) or kind not in {'move', 'optical', 'compound', 'handheld', 'static'}:
            add('CAMERA_CONTRACT_MISSING', at+'.kind', '摄影机类型无效。')
        for key in ('technique', 'purpose', 'start_frame', 'path_and_speed', 'subject_relation', 'end_frame', 'execution'):
            if not filled(camera.get(key)):
                add('CAMERA_CONTRACT_MISSING', at+'.'+key, '摄影机执行字段须为非空文字。')
        if kind == 'static':
            if not filled(camera.get('static_reason')):
                add('CAMERA_STATIC_REASON_MISSING', at+'.static_reason', '固定机位须说明本镜为何需要稳定观看。')
        elif 'static_reason' not in camera or camera.get('static_reason') is not None:
            add('CAMERA_STATIC_REASON_INVALID', at+'.static_reason', '运动镜头的static_reason须为null。')
    return issues + validate_sound_fields(segment)


def validate_sound_fields(segment: Any) -> list[dict]:
    """声音来源门禁亦适用于单段；不需要先进入整集连接校验。"""
    issues = []
    sounds = segment.get('sound_events') if isinstance(segment, dict) else None
    if not isinstance(sounds, list):
        return [dict(code='AUDIO_BRIDGE_EVENT_INVALID', at='sound_events', message='声音事件须为数组，默认空数组。')]
    duration = seconds(segment.get('duration_seconds'))
    dialogue = segment.get('dialogue_events', [])
    seen = {x['id'] for x in dialogue if isinstance(x, dict) and filled(x.get('id'))} if isinstance(dialogue, list) else set()
    for i, event in enumerate(sounds):
        valid = isinstance(event, dict)
        if valid:
            eid = event.get('id'); a, b = seconds(event.get('start')), seconds(event.get('end')); kind = event.get('kind')
            valid = filled(eid) and eid not in seen and a is not None and b is not None and duration is not None and a < b <= duration
            valid = valid and filled(event.get('description')) and filled(event.get('source_ref')) and isinstance(kind, str) and kind in {'environment', 'action', 'authorized_effect'}
            if kind == 'authorized_effect': valid = valid and filled(event.get('authorization_ref'))
            if filled(eid): seen.add(eid)
        if not valid: issues.append(dict(code='AUDIO_BRIDGE_EVENT_INVALID', at=f'sound_events[{i}]', message='声音ID、时间、事实来源或效果授权无效。'))
    return issues


def validate_camera_text(segment: Any, parsed: Any) -> list[dict]:
    issues = []
    shots = segment.get('shots', []) if isinstance(segment, dict) else []
    views = parsed.get('shots', []) if isinstance(parsed, dict) else []
    if not isinstance(shots, list): shots = []
    if not isinstance(views, list): views = []
    bodies = [normalized(s.get('execution_body', '')) if isinstance(s, dict) else '' for s in views]
    for i, shot in enumerate(shots):
        camera = shot.get('camera') if isinstance(shot, dict) else None
        execution = normalized(camera.get('execution')) if isinstance(camera, dict) else ''
        if not execution: continue  # 字段检查负责报告
        at = f'shots[{i}].camera.execution'
        if i >= len(bodies) or execution not in bodies[i]:
            issues.append(dict(code='CAMERA_EXECUTION_NOT_IN_SHOT', at=at, message='摄影机完整执行句未出现在所属镜头的有效B区正文。'))
        if sum(body.count(execution) for body in bodies) > 1:
            issues.append(dict(code='CAMERA_EXECUTION_DUPLICATED', at=at, message='摄影机执行句在镜头正文中重复，不能靠复制满足归属。'))
    return issues


def validate_connections(episode: Any, parsed_segments: Any) -> list[dict]:
    issues = []
    def add(code, at, message): issues.append(dict(code=code, at=at, message=message))
    if not isinstance(episode, dict):
        add('CONNECTION_COVERAGE_INVALID', 'episode', '整集须为对象。'); return issues
    if not filled(episode.get('camera_strategy')):
        add('CAMERA_STRATEGY_MISSING', 'camera_strategy', '整集须有覆盖普通对白、证据与结果的摄影策略。')
    segments = episode.get('segments')
    if not isinstance(segments, list) or not segments:
        add('CONNECTION_COVERAGE_INVALID', 'segments', '需要非空整集段列表。'); return issues
    if not isinstance(parsed_segments, list): parsed_segments = []
    nodes = []; lookup = {}; events = {}
    for si, segment in enumerate(segments):
        if not isinstance(segment, dict):
            add('CONNECTION_REF_INVALID', f'segments[{si}]', '段须为对象。'); continue
        sid = segment.get('segment_id'); shots = segment.get('shots')
        if not filled(sid) or not isinstance(shots, list):
            add('CONNECTION_REF_INVALID', f'segments[{si}]', '段ID或镜头数组无效。'); continue
        parsed = parsed_segments[si] if si < len(parsed_segments) and isinstance(parsed_segments[si], dict) else {}
        views = parsed.get('shots', []); views = views if isinstance(views, list) else []
        for ki, shot in enumerate(shots):
            key = (sid, shot.get('id')) if isinstance(shot, dict) else None
            if key is None or not filled(key[1]) or key in lookup:
                add('CONNECTION_REF_INVALID', f'segments[{si}].shots[{ki}]', '镜头定位必须段内唯一且可解析。'); continue
            nodes.append(key)
            view = views[ki] if ki < len(views) and isinstance(views[ki], dict) else {}
            lookup[key] = (segment, shot, normalized(view.get('execution_body', '')))
        sounds = segment.get('sound_events')
        if not isinstance(sounds, list):
            add('AUDIO_BRIDGE_EVENT_INVALID', f'segments[{si}].sound_events', '声音事件须为数组，默认空数组。'); sounds = []
        speech = segment.get('dialogue_events', [])
        speech = speech if isinstance(speech, list) else []
        for ei, event in enumerate(speech + sounds):
            is_sound = ei >= len(speech)
            at = f'segments[{si}].'+('sound_events' if is_sound else 'dialogue_events')
            eid = event.get('id') if isinstance(event, dict) else None
            if not filled(eid):
                add('AUDIO_BRIDGE_EVENT_INVALID', at, '事件ID须为非空字符串。'); continue
            a, b = seconds(event.get('start')), seconds(event.get('end'))
            duration = seconds(segment.get('duration_seconds'))
            valid = a is not None and b is not None and duration is not None and a < b <= duration
            if is_sound:
                kind = event.get('kind')
                valid = valid and filled(event.get('description')) and filled(event.get('source_ref')) and isinstance(kind, str) and kind in {'environment', 'action', 'authorized_effect'}
                if kind == 'authorized_effect': valid = valid and filled(event.get('authorization_ref'))
            key = (sid, eid)
            if key in events or not valid:
                add('AUDIO_BRIDGE_EVENT_INVALID', at+'.'+eid, '事件来源、时间、授权或唯一身份无效。')
            else: events[key] = (segment, event)
    edges = episode.get('connections')
    if not isinstance(edges, list):
        add('CONNECTION_COVERAGE_INVALID', 'connections', '需要完整有序连接数组。'); return issues
    expected = list(zip(nodes, nodes[1:])); actual = []
    def key_of(value):
        if isinstance(value, dict) and filled(value.get('segment_id')) and filled(value.get('shot_id')):
            return value['segment_id'], value['shot_id']
        return None
    for i, edge in enumerate(edges):
        at = f'connections[{i}]'
        if not isinstance(edge, dict):
            add('CONNECTION_REF_INVALID', at, '连接须为对象。'); actual.append(None); continue
        left, right = key_of(edge.get('from')), key_of(edge.get('to'))
        actual.append((left, right))
        if left not in lookup or right not in lookup:
            add('CONNECTION_REF_INVALID', at, '前后段ID及镜头ID必须存在。'); continue
        before, x, out_body = lookup[left]; after, y, in_body = lookup[right]
        for field in ('technique', 'cut_trigger', 'out_execution', 'in_execution'):
            if not filled(edge.get(field)): add('CONNECTION_CONTRACT_INVALID', at+'.'+field, '衔接决定须为非空文字。')
        relation = edge.get('spacetime_relation')
        if not isinstance(relation, str) or relation not in {'同一动作', '同场连续', '同时异地', '时间省略', '回忆', '想象'}:
            add('CONNECTION_CONTRACT_INVALID', at+'.spacetime_relation', '先明确合法时空关系。')
        elements = edge.get('match_elements')
        if not isinstance(elements, list) or not all(filled(v) for v in elements) or (edge.get('technique') != '普通硬切' and not elements):
            add('CONNECTION_CONTRACT_INVALID', at+'.match_elements', '特殊转场须列出可观察匹配条件；普通硬切可为空。')
        edit = edge.get('visual_edit')
        if not isinstance(edit, str) or edit not in {'hard_cut', 'match_cut', 'dissolve'}:
            add('CONNECTION_VISUAL_EDIT_MISMATCH', at+'.visual_edit', '实际视觉剪接类型无效。')
        elif left[0] == right[0] and y.get('transition_in') != edit:
            add('CONNECTION_VISUAL_EDIT_MISMATCH', at+'.visual_edit', '连接与后镜实际剪接登记不一致。')
        for field, body in [('out_execution', out_body), ('in_execution', in_body)]:
            phrase = normalized(edge.get(field))
            if not phrase or body.count(phrase) != 1:
                add('CONNECTION_EXECUTION_MISSING', at+'.'+field, '衔接执行句须在对应镜头有效正文中完整出现一次。')
        bridge = edge.get('audio_bridge')
        if not isinstance(bridge, dict):
            add('AUDIO_BRIDGE_EVENT_INVALID', at+'.audio_bridge', '声桥须为对象。'); continue
        mode, refs, execution = bridge.get('mode'), bridge.get('event_refs'), bridge.get('execution')
        if not isinstance(mode, str) or mode not in {'none', 'J', 'L', 'sound_match', 'accent'} or not isinstance(refs, list):
            add('AUDIO_BRIDGE_EVENT_INVALID', at+'.audio_bridge', '声桥类型或事件数组无效。'); continue
        if mode == 'none':
            if refs != [] or execution != '': add('AUDIO_BRIDGE_EVENT_INVALID', at+'.audio_bridge', '无声桥须空引用与空执行句。')
            continue
        if mode in {'J', 'L'} and left[0] != right[0]:
            add('AUDIO_BRIDGE_CROSS_REQUEST_UNVERIFIED', at+'.audio_bridge', '跨独立生成请求的J/L能力未核验，不得宣称完整合同通过。')
        phrase = normalized(execution)
        appropriate = out_body if mode == 'J' else in_body if mode == 'L' else out_body + '\ufffc' + in_body
        if not phrase or appropriate.count(phrase) != 1:
            add('AUDIO_BRIDGE_EXECUTION_MISSING', at+'.audio_bridge.execution', '声画关系完整执行句未在对应端正文落实。')
        resolved = []
        for ref in refs:
            if isinstance(ref, dict) and filled(ref.get('segment_id')) and filled(ref.get('event_id')):
                key = (ref['segment_id'], ref['event_id'])
            elif filled(ref):
                candidates = [k for k in events if k[1] == ref and k[0] in {left[0], right[0]}]
                key = candidates[0] if len(candidates) == 1 else None
            else: key = None
            if key not in events or key[0] not in {left[0], right[0]} or key in resolved:
                add('AUDIO_BRIDGE_EVENT_INVALID', at+'.audio_bridge.event_refs', '事件须已登记、位于连接两端且可唯一定位。')
            else: resolved.append(key)
        if not refs or (mode == 'sound_match' and len(resolved) < 2):
            add('AUDIO_BRIDGE_EVENT_INVALID', at+'.audio_bridge.event_refs', '声桥须引用事件；声音匹配至少两个两端事件。')
        source = before.get('time_source', {}); offset = seconds(source.get('range_start', 0)) if isinstance(source, dict) else None
        local_cut = seconds(x.get('end')); cut = offset + local_cut if offset is not None and local_cut is not None else None
        times = []
        for key in resolved:
            seg, event = events[key]; src = seg.get('time_source', {})
            origin = seconds(src.get('range_start', 0)) if isinstance(src, dict) else None
            a, b = seconds(event.get('start')), seconds(event.get('end'))
            if origin is not None and a is not None and b is not None: times.append((origin+a, origin+b))
        if cut is None or not times:
            add('AUDIO_BRIDGE_TIME_INVALID', at+'.audio_bridge', '无法核对声音绝对时间。')
        elif mode in {'J', 'L'} and not all(a < cut < b for a, b in times):
            add('AUDIO_BRIDGE_TIME_INVALID', at+'.audio_bridge', 'J/L声音须真实跨越视觉切点，不能恰好开始或结束。')
        elif mode == 'accent' and not any(a <= cut <= b for a, b in times):
            add('AUDIO_BRIDGE_TIME_INVALID', at+'.audio_bridge', '卡点事件须覆盖该切点。')
        elif mode == 'sound_match' and not (any(a < cut for a, b in times) and any(b > cut for a, b in times)):
            add('AUDIO_BRIDGE_TIME_INVALID', at+'.audio_bridge', '声音匹配须有切点两侧可核对的事件。')
    if actual != expected:
        add('CONNECTION_COVERAGE_INVALID', 'connections', '必须按顺序覆盖全部N−1相邻切点，含生成段边界。')
    return issues
