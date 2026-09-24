import json
from pathlib import Path
import tempfile
import unittest
from init_project import initialize


class InitializerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.common = self.root / '_通用短剧工作流'; self.common.mkdir()
        self.template = self.common / '项目启动说明.template.md'; self.template.write_text('PROJECT TEMPLATE', encoding='utf-8')
        self.config = self.common / 'Codex适配剧梦提示词库（模版）0914/dreamina-short-drama-production/assets/项目参数.template.json'
        self.config.parent.mkdir(parents=True); self.config.write_text(json.dumps({'schema': 'JM-v3.5', 'project': {}, 'authorization': {'platform_generation': False}}), encoding='utf-8')
        (self.common / 'AGENTS.project.template.md').write_text('Workflow: {{COMMON_ROOT}}', encoding='utf-8')
        (self.common / '制作台账.template.json').write_text(json.dumps({'schema': 'JM-ledger-v1', 'segments': []}), encoding='utf-8')

    def test_creates_config_without_authorizing_generation(self):
        initialize(self.root, 'NewProject')
        data = json.loads((self.root/'NewProject/项目参数.json').read_text(encoding='utf-8-sig'))
        self.assertFalse(data['authorization']['platform_generation'])
        self.assertTrue((self.root/'NewProject/AGENTS.md').exists())

    def test_repeated_initialization_preserves_every_existing_file(self):
        initialize(self.root, 'Existing')
        p=self.root/'Existing'
        (p/'项目启动说明.md').write_bytes(b'USER CUSTOM CONFIG')
        (p/'项目参数.json').write_bytes(b'{"user": "DECISION"}')
        before={f.name:f.read_bytes() for f in p.iterdir() if f.is_file()}
        initialize(self.root, 'Existing')
        self.assertEqual(before,{f.name:f.read_bytes() for f in p.iterdir() if f.is_file()})

    def test_missing_template_does_not_partially_initialize(self):
        self.template.unlink()
        with self.assertRaises(FileNotFoundError): initialize(self.root, 'Missing')
        self.assertFalse((self.root/'Missing').exists())

    def test_path_traversal_is_rejected(self):
        for name in ('../Elsewhere', '..', 'A/B', 'A\\B', '_通用短剧工作流', 'CON', 'NUL.txt', 'Name.'):
            with self.subTest(name=name):
                with self.assertRaises(ValueError): initialize(self.root, name)

    def test_old_asset_file_is_untouched(self):
        initialize(self.root, 'Existing'); image=self.root/'Existing/人物/asset.png'; image.write_bytes(b'original')
        initialize(self.root, 'Existing'); self.assertEqual(image.read_bytes(),b'original')

if __name__ == '__main__': unittest.main()
