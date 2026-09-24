import copy
import unittest
from workflow_check import validate_manifest


def good_manifest():
    return {
        'main_language': 'es',
        'time_source': {'kind': 'user', 'seconds': 8},
        'duration_seconds': 8,
        'shots': [
            {'id': 'S01', 'start': 0, 'end': 4, 'transition_in': 'start'},
            {'id': 'S02', 'start': 4, 'end': 8, 'transition_in': 'hard_cut'},
        ],
        'source_dialogue': {'D01': 'No tengo nada que ver.'},
        'dialogue_events': [
            {'id': 'D01', 'kind': 'dialogue', 'speaker': 'Vivian', 'text': 'No tengo nada que ver.', 'language': 'es', 'start': 0, 'end': 7.5},
        ],
        'source_narration': {'N01': 'La mirada se detuvo en el informe.'},
        'narration_coverage': [{'source_id': 'N01', 'shot_ids': ['S02'], 'visual_evidence': '角色停止翻页，视线落在报告上。'}],
        'screen_text_mode': 'direct_generation',
        'visible_text': [{'id': 'T01', 'text': 'INFORME', 'language': 'es', 'surface': '平板实体屏幕', 'start': 4, 'end': 8}],
        'has_independent_voice_reference': False,
        'character_attached_audio_preserved': True,
    }


class ManifestTests(unittest.TestCase):
    def codes(self, value):
        return {e['code'] for e in validate_manifest(value)}

    def test_long_dialogue_crosses_actual_cut_without_repetition(self):
        self.assertEqual(validate_manifest(good_manifest()), [])

    def test_exactly_five_seconds_is_accepted(self):
        m = good_manifest(); m['shots'][0]['end'] = 5; m['shots'][1]['start'] = 5
        self.assertEqual(validate_manifest(m), [])

    def test_more_than_five_seconds_fails(self):
        m = good_manifest(); m['shots'][0]['end'] = 5.001; m['shots'][1]['start'] = 5.001
        self.assertIn('SHOT_TOO_LONG', self.codes(m))

    def test_beats_cannot_relabel_one_continuous_shot(self):
        m = good_manifest(); m['shots'][1]['id'] = 'S01'; m['shots'][1]['transition_in'] = 'continue'
        self.assertIn('CONTINUOUS_SHOT_REUSED', self.codes(m))
        self.assertIn('MISSING_REAL_CUT', self.codes(m))

    def test_nan_time_is_rejected(self):
        m = good_manifest(); m['shots'][0]['end'] = float('nan')
        self.assertIn('INVALID_TIME', self.codes(m))

    def test_time_gap_fails(self):
        m = good_manifest(); m['shots'][1]['start'] = 4.1
        self.assertIn('TIMELINE_GAP_OR_OVERLAP', self.codes(m))

    def test_duration_cannot_default_to_ninety(self):
        m = good_manifest(); m['duration_seconds'] = 90
        self.assertIn('DURATION_SOURCE_MISMATCH', self.codes(m))

    def test_missing_authoritative_time_fails_submission_gate(self):
        m = good_manifest(); m['time_source'] = {'kind': 'estimate', 'seconds': 8}
        self.assertIn('TIMING_NOT_CONFIRMED', self.codes(m))

    def test_srt_long_cue_does_not_force_long_shot(self):
        m = good_manifest(); m['time_source'] = {'kind': 'srt', 'range_start': 10, 'range_end': 18}
        self.assertEqual(validate_manifest(m), [])

    def test_chinese_screen_text_in_spanish_fails(self):
        m = good_manifest(); m['visible_text'][0]['text'] = '调查结果'
        self.assertIn('FOREIGN_SCRIPT', self.codes(m))

    def test_chinese_directing_notes_are_not_rendered_text(self):
        m = good_manifest(); m['shots'][0]['description'] = '卡洛斯@卡洛斯_角色资产.png 低头看报告。'
        self.assertEqual(validate_manifest(m), [])

    def test_wrong_declared_language_fails_even_if_latin(self):
        m = good_manifest(); m['visible_text'][0]['text'] = 'REPORT'; m['visible_text'][0]['language'] = 'en'
        self.assertIn('LANGUAGE_MISMATCH', self.codes(m))

    def test_chinese_project_can_have_chinese_text(self):
        m = good_manifest(); m['main_language'] = 'zh'; m['visible_text'][0].update(text='报告', language='zh')
        m['dialogue_events'][0].update(text='这和我没有关系。', language='zh'); m['source_dialogue']['D01'] = '这和我没有关系。'
        self.assertEqual(validate_manifest(m), [])

    def test_voice_over_cannot_be_spoken(self):
        m = good_manifest(); m['dialogue_events'][0]['kind'] = 'VO'
        self.assertIn('NARRATION_MUST_BE_VISUAL', self.codes(m))

    def test_real_offscreen_dialogue_is_preserved(self):
        m = good_manifest(); m['dialogue_events'][0]['kind'] = 'offscreen_dialogue'
        self.assertEqual(validate_manifest(m), [])

    def test_independent_voice_section_is_rejected(self):
        m = good_manifest(); m['has_independent_voice_reference'] = True
        self.assertIn('INDEPENDENT_VOICE_REFERENCE', self.codes(m))

    def test_attached_character_audio_is_protected(self):
        m = good_manifest(); m['character_attached_audio_preserved'] = False
        self.assertIn('ATTACHED_AUDIO_NOT_PRESERVED', self.codes(m))

    def test_duplicate_dialogue_event_is_rejected(self):
        m = good_manifest(); m['dialogue_events'].append(copy.deepcopy(m['dialogue_events'][0]))
        self.assertIn('DUPLICATE_SPEECH_EVENT', self.codes(m))

    def test_missing_dialogue_is_rejected(self):
        m = good_manifest(); m['dialogue_events'] = []
        self.assertIn('DIALOGUE_MISSING_OR_ADDED', self.codes(m))

    def test_rewritten_dialogue_is_rejected(self):
        m = good_manifest(); m['dialogue_events'][0]['text'] = 'No fui yo.'
        self.assertIn('DIALOGUE_CHANGED', self.codes(m))

    def test_dropped_narration_information_is_rejected(self):
        m = good_manifest(); m['narration_coverage'] = []
        self.assertIn('NARRATION_COVERAGE_MISSING', self.codes(m))

    def test_screen_text_cannot_be_deferred_to_post(self):
        m = good_manifest(); m['screen_text_mode'] = 'postproduction'
        self.assertIn('SCREEN_TEXT_NOT_DIRECT', self.codes(m))

    def test_text_without_surface_is_rejected(self):
        m = good_manifest(); m['visible_text'][0]['surface'] = ''
        self.assertIn('TEXT_SURFACE_MISSING', self.codes(m))


if __name__ == '__main__':
    unittest.main()

class AdditionalBoundaryTests(unittest.TestCase):
    def test_user_episode_budget_can_supply_segment_range(self):
        m=good_manifest(); m['time_source']={'kind':'user','seconds':120,'range_start':20,'range_end':28}
        self.assertEqual(validate_manifest(m),[])

    def test_segment_cannot_exceed_user_episode_budget(self):
        m=good_manifest(); m['time_source']={'kind':'user','seconds':25,'range_start':20,'range_end':28}
        self.assertIn('EVENT_OUT_OF_RANGE',{e['code'] for e in validate_manifest(m)})

    def test_invalid_speech_id_reports_error_not_exception(self):
        m=good_manifest(); m['dialogue_events'][0]['id']=[]
        self.assertIn('SPEECH_ID_MISSING',{e['code'] for e in validate_manifest(m)})
