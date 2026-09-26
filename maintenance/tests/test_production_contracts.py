from support import *
from tools.workflow_check import validate_manifest
from tools.workflow_paths import discover_from_project
from tools.workflow_lock import verify_lock, read_lock
from tools import migrate_workflow as m


class ProductionContracts(Sandbox):
    def test_A37_standalone_valid_invalid_exit_semantics(self):
        path=self.space/'segment.json'; data=valid_segment();path.write_bytes(encoded(data))
        proc=cli(self.common/'tools/workflow_check.py',path,cwd=self.space)
        self.assertEqual(proc.returncode,0,proc.stdout)
        result=json.loads(proc.stdout);self.assertTrue(result['manifest_passed']);self.assertIsNone(result['static_contract_passed'])
        data['shots'][0]['end']=6;path.write_bytes(encoded(data))
        proc=cli(self.common/'tools/workflow_check.py',path)
        self.assertEqual(proc.returncode,1)
        self.assertIn('SHOT_TOO_LONG',[x['code'] for x in json.loads(proc.stdout)['issues']])

    def test_A38_business_parameters_and_contracts_preserved(self):
        old=json.loads(self.layout.resources['template.project_parameters'].read_bytes())
        old['script']['fact_source']='synthetic-local';old['audio']['custom']={'voice':'local'}
        old['decisions']=[{'source':'synthetic user','scope':'one segment'}]
        raw=m.merge_parameters(encoded(old),self.layout.resources['template.project_parameters'].read_bytes(),common_root=self.common)
        new=json.loads(raw);new['project'].pop('common_root');old['project'].pop('common_root')
        self.assertEqual(new,old)
        self.assertEqual(new['timing']['max_shot_seconds'],5)
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
