from support import *
from tools.workflow_lock import verify_lock


class LockTests(Sandbox):
    def test_A19_raw_bytes_changed(self):
        lock = make_lock(self.layout)
        path = self.layout.resources['skill.director']
        path.write_bytes(path.read_bytes() + b'\n')
        result = verify_lock(self.layout, lock)
        self.assertFalse(result['ok'])
        self.assertIn('skill.director', result['changed_resources'])

    def test_A20_same_version_added_removed_invalid_hash(self):
        lock = make_lock(self.layout)
        lock['resources']['old.unknown'] = {'sha256': 'a'*64, 'path_hint': 'old.md'}
        del lock['resources']['skill.acting']
        result = verify_lock(self.layout, lock)
        self.assertEqual(result['missing_resources'], ['old.unknown'])
        self.assertEqual(result['added_resources'], ['skill.acting'])
        lock['resources']['old.unknown']['sha256'] = 'z'*64
        self.assertCode('LOCK_INVALID', verify_lock, self.layout, lock)

    def test_A21_manifest_redirect_is_locked(self):
        lock = make_lock(self.layout)
        marker = self.layout.resources['meta.workflow']; data = json.loads(marker.read_bytes())
        path = self.common / 'alternate.md'; path.write_bytes(b'alternate')
        data['resources']['doc.readme']['path'] = path.name; marker.write_bytes(encoded(data))
        result = verify_lock(load_layout(self.common), lock)
        self.assertIn('meta.workflow', result['changed_resources'])
        self.assertIn('doc.readme', result['changed_resources'])
        self.assertIn('doc.readme', result['relocated_resources'])

    def test_A35_maintenance_not_runtime_digest(self):
        from maintenance.maintain import aggregate, hashes, source_files
        lock = make_lock(self.layout); before = aggregate(hashes(source_files(self.common)))
        path = self.common / 'maintenance' / 'README.md'
        path.write_bytes(path.read_bytes() + b'\nmaintenance edit')
        self.assertTrue(verify_lock(self.layout, lock)['ok'])
        self.assertNotEqual(before, aggregate(hashes(source_files(self.common))))

    def test_A36_root_readme_remains_locked(self):
        lock = make_lock(self.layout)
        path = self.layout.resources['doc.readme']; path.write_bytes(path.read_bytes() + b'\n')
        self.assertIn('doc.readme', verify_lock(self.layout, lock)['changed_resources'])
