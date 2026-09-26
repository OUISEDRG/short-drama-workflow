from support import *
from unittest.mock import patch
from maintenance import maintain as mm
import zipfile


def passing_check(root):
    return {'ok':True,'tests_run':1,'tests_passed':1,'failures':0,'errors':0,'skipped':[],
            'runtime_digest':mm.aggregate({r:i['sha256'] for r,i in make_lock(load_layout(root))['resources'].items()}),
            'source_digest':mm.aggregate(mm.hashes(mm.source_files(root)))}


def passing_smoke(root):
    load_layout(root)
    return {'ok':True,'test_double':True}


class MaintenanceTests(Sandbox):
    def test_A33_readonly_doctor_resolve_list_plan_check(self):
        project=self.project();before=snapshot(self.common);project_before=snapshot(project)
        for command in (('doctor','--json'),('list-resources','--json'),('resolve','skill.director','--json')):
            proc=cli(self.common/'tools/workflow_paths.py',*command)
            self.assertEqual(proc.returncode,0,proc.stdout)
        from tools.migrate_workflow import plan
        plan(project,self.common)
        with patch.object(mm,'run_tests',return_value={'tests_run':1,'tests_passed':1,'failures':0,'errors':0,'skipped':[]}):
            self.assertTrue(mm.check(self.common)['ok'])
        self.assertEqual(before,snapshot(self.common));self.assertEqual(project_before,snapshot(project))

    def test_A39_missing_zero_and_load_failure(self):
        tests=self.common/'maintenance'/'tests'
        source=(tests/'test_paths.py').read_bytes()
        for name in mm.TEST_FILES:
            if name.startswith('test_'):
                (tests/name).write_bytes(b'')
        (tests/'test_paths.py').write_bytes(b'raise RuntimeError("synthetic test import failure")')
        result=mm.check(self.common)
        self.assertFalse(result['ok']);self.assertGreater(result['errors'],0)
        (tests/'test_paths.py').write_bytes(b'')
        result=mm.check(self.common)
        self.assertFalse(result['ok']);self.assertEqual(result['exit_code'],3)
        shutil.rmtree(tests)
        self.assertFalse(mm.check(self.common)['ok'])

    def test_A39_baseline_invalid_and_changed(self):
        path=self.space/'baseline.json';path.write_bytes(encoded({'schema':'bad'}))
        result=mm.check(self.common,baseline=path)
        self.assertFalse(result['ok']);self.assertEqual(result['protection_comparison'],'not_completed')
        baseline={'schema':'JM-maintenance-baseline-v1','collected_at':'synthetic test',
                  'protected_resources':{rid:digest(self.layout.resources[rid].read_bytes()) for rid in mm.PROTECTED},
                  'parameters_business':json.loads(self.layout.resources['template.project_parameters'].read_bytes()),
                  'excluded_parameter_fields':[]}
        path.write_bytes(encoded(baseline))
        mm.protection_check(self.common,self.layout,path)
        self.layout.resources['skill.acting'].write_bytes(self.layout.resources['skill.acting'].read_bytes()+b'\n')
        self.assertCode('PROTECTED_CHANGED',mm.protection_check,self.common,self.layout,path)

    def test_A40_failed_and_skipped_test_no_archive(self):
        for result in ({'ok':False,'tests_run':1,'skipped':[]}, {'ok':True,'tests_run':1,'skipped':['required']}):
            self.assertCode('RELEASE_CHECK_FAILED',mm.release,self.common,checker=lambda root:result,smoker=passing_smoke)
            self.assertFalse((self.common/'maintenance/releases').exists())

    def test_A41_source_change_aborts_release(self):
        def changed(root):
            result=passing_check(root)
            path=self.common/'README.md';path.write_bytes(path.read_bytes()+b'\nconcurrent edit')
            return result
        self.assertCode('RELEASE_SOURCE_CHANGED',mm.release,self.common,checker=changed,smoker=passing_smoke)
        self.assertFalse((self.common/'maintenance/releases').exists())

    def test_A42_allowlist_zip_hashes_and_exclusions(self):
        for rel in ('maintenance/backups/private.md','maintenance/releases/old.zip','private-project/script.md','maintenance/reports/old.json'):
            path=self.common/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'private synthetic test marker')
        result=mm.release(self.common,checker=passing_check,smoker=passing_smoke)
        with zipfile.ZipFile(result['package']) as archive:
            self.assertEqual(set(archive.namelist()),set(mm.source_files(self.common)))
            self.assertFalse(any('backups/' in n or 'releases/' in n or 'private-project' in n or 'reports/' in n for n in archive.namelist()))
        self.assertTrue(result['complete'])
        self.assertEqual(digest(Path(result['package']).read_bytes()),result['zip_sha256'])
        self.assertIn('maintenance/tests/test_maintenance.py',result['files'])
        for name in mm.FIXTURE_FILES:
            self.assertIn('maintenance/tests/fixtures/' + name, result['files'])

    def test_historical_fixture_allowlist_missing_and_unknown_refused(self):
        path = self.common/'maintenance/tests/fixtures/provenance.json'
        original = path.read_bytes()
        path.unlink()
        self.assertCode('SOURCE_MISSING', mm.release, self.common,
                        checker=passing_check, smoker=passing_smoke)
        path.write_bytes(original)
        (path.parent/'unreviewed.json').write_bytes(b'{}')
        self.assertCode('TEST_FIXTURE_SET_INVALID', mm.release, self.common,
                        checker=passing_check, smoker=passing_smoke)
        self.assertFalse((self.common/'maintenance/releases').exists())

    def test_A42_missing_or_forbidden_resource_refuses(self):
        (self.common/'maintenance/tests/test_lock.py').unlink()
        self.assertCode('SOURCE_MISSING',mm.release,self.common,checker=passing_check,smoker=passing_smoke)
        marker=self.common/'workflow.manifest.json';data=json.loads(marker.read_bytes())
        path=self.common/'maintenance/backups/rule.md';path.parent.mkdir(parents=True);path.write_bytes(b'synthetic')
        data['resources']['extra.rule']={'path':'maintenance/backups/rule.md','required':True};marker.write_bytes(encoded(data))
        self.assertCode('RESOURCE_PATH_INVALID',load_layout,self.common)

    def test_A43_no_overwrite_reports_and_archives(self):
        report=mm.write_report(self.common,'maintenance/reports/unit.json',{'ok':True})
        before=report.read_bytes()
        self.assertCode('OUTPUT_EXISTS',mm.write_report,self.common,report,{'ok':False})
        self.assertEqual(report.read_bytes(),before)
        result=mm.release(self.common,checker=passing_check,smoker=passing_smoke)
        before=snapshot(self.common/'maintenance/releases')
        self.assertCode('OUTPUT_EXISTS',mm.release,self.common,checker=passing_check,smoker=passing_smoke)
        self.assertEqual(before,snapshot(self.common/'maintenance/releases'))
        self.assertCode('OUTPUT_OUT_OF_SCOPE',mm.write_report,self.common,'../outside.json',{})

    def test_A43_release_io_failure_no_complete_output(self):
        real_open=Path.open
        def faulty(path,mode='r',*args,**kwargs):
            if mode=='xb' and path.suffix=='.json' and path.parent.name=='releases':
                raise OSError('synthetic record output failure')
            return real_open(path,mode,*args,**kwargs)
        with patch.object(Path,'open',faulty):
            self.assertCode('RELEASE_IO_FAILED',mm.release,self.common,checker=passing_check,smoker=passing_smoke)
        self.assertFalse(list((self.common/'maintenance/releases').glob('*.zip')))
        self.assertFalse(list((self.common/'maintenance/releases').glob('*.json')))

    def test_A43_output_paths_use_tool_root(self):
        path=mm.output_path(self.common,'maintenance/reports/result.json','reports')
        self.assertEqual(path,self.common/'maintenance/reports/result.json')
        self.assertCode('OUTPUT_OUT_OF_SCOPE',mm.output_path,self.common,self.space/'x','releases')
