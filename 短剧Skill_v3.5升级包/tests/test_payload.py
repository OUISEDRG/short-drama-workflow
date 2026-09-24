import json
from pathlib import Path
import re
import unittest
from workflow_check import validate_prompt_text

P=Path(__file__).resolve().parents[1]/'payload'
class PayloadTests(unittest.TestCase):
    def test_layout_template_has_no_independent_voice_reference(self):
        text=(P/'视频提示词输出规范_资产全名版.md').read_text(encoding='utf-8')
        template=text.split('# 24. 最终固定模板')[1].split('# 25.')[0]
        self.assertNotRegex(template,r'【(?:声音|音色|音频)引用】')

    def test_defaults_have_no_fixed_duration(self):
        m=json.loads((P/'项目参数.template.json').read_text(encoding='utf-8'))
        self.assertIsNone(m['timing']['episode_default_seconds']); self.assertIsNone(m['timing']['segment_default_seconds'])
        self.assertEqual(m['timing']['max_shot_seconds'],5)

    def test_audio_policies_are_not_conflated(self):
        a=json.loads((P/'项目参数.template.json').read_text(encoding='utf-8'))['audio']
        self.assertEqual(a['narration_policy'],'visual_only')
        self.assertEqual(a['offscreen_dialogue_policy'],'preserve_original_speech')
        self.assertFalse(a['independent_voice_reference']); self.assertTrue(a['preserve_character_attached_audio'])

    def test_no_generation_permission_is_inherited_from_template(self):
        a=json.loads((P/'项目参数.template.json').read_text(encoding='utf-8'))['authorization']
        self.assertFalse(a['platform_generation']); self.assertFalse(a['spend_credits'])

    def test_screen_text_is_direct_not_postproduction(self):
        a=json.loads((P/'项目参数.template.json').read_text(encoding='utf-8'))['screen_text']
        self.assertEqual(a['mode'],'direct_generation'); self.assertFalse(a['postproduction_fallback'])

    def test_legacy_voice_block_is_detected(self):
        self.assertEqual(validate_prompt_text('【音色引用】\n克拉拉@旁白.mp3')[0]['code'],'INDEPENDENT_VOICE_REFERENCE')

    def test_chinese_asset_binding_is_not_treated_as_foreign_screen_text(self):
        self.assertEqual(validate_prompt_text('克拉拉@克拉拉_训练服.png看向屏幕。'),[])

    def test_legacy_screen_postproduction_instruction_is_detected(self):
        self.assertTrue(validate_prompt_text('精确屏幕文字以后期覆盖为准。'))

if __name__=='__main__': unittest.main()
