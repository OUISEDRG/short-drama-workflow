import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import apply_upgrade as upgrade


class UpgraderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def test_unique_anchor_replaces_exactly_once(self):
        op={'path':'a.md','op':'replace','old':'old','new':'new'}
        self.assertEqual(upgrade.transform('header\nold\nfooter',op),'header\nnew\nfooter')

    def test_missing_anchor_stops_instead_of_guessing(self):
        with self.assertRaises(ValueError): upgrade.transform('changed',{'path':'a','op':'replace','old':'old','new':'new'})

    def test_ambiguous_anchor_stops(self):
        with self.assertRaises(ValueError): upgrade.transform('old old',{'path':'a','op':'replace','old':'old','new':'new'})

    def test_section_preserves_surrounding_content(self):
        op={'path':'a','op':'section','begin':'# B','end':'# C','new':'# B\nNEW\n'}
        self.assertEqual(upgrade.transform('# A\nKEEP\n# B\nOLD\n# C\nKEEP',op),'# A\nKEEP\n# B\nNEW\n# C\nKEEP')

    def test_path_traversal_is_not_allowed(self):
        with self.assertRaises(ValueError): upgrade.safe_path(self.root,'../outside.md')

    def test_apply_backs_up_original_and_verifies_bytes(self):
        target=self.root/'a.md'; target.write_bytes(b'OLD')
        change=upgrade.Change(target,b'OLD',b'NEW')
        backup=self.root/'backup'; upgrade.apply_changes([change],backup)
        self.assertEqual(target.read_bytes(),b'NEW')
        data=json.loads((backup/'manifest.json').read_text())
        self.assertEqual((backup/data[0]['backup']).read_bytes(),b'OLD')

    def test_preflight_concurrent_modification_stops_without_write(self):
        target=self.root/'a.md'; target.write_bytes(b'CHANGED BY USER')
        with self.assertRaises(RuntimeError): upgrade.apply_changes([upgrade.Change(target,b'OLD',b'NEW')],self.root/'backup')
        self.assertEqual(target.read_bytes(),b'CHANGED BY USER')
        self.assertFalse((self.root/'backup').exists())

    def test_failed_second_write_rolls_back_first_file(self):
        a=self.root/'a.md'; b=self.root/'b.md'; a.write_bytes(b'A'); b.write_bytes(b'B')
        actual_write=upgrade.atomic_write
        def fail_b(path,data):
            if path==b and data==b'B_NEW': raise OSError('simulated disk failure')
            actual_write(path,data)
        with patch.object(upgrade,'atomic_write',side_effect=fail_b):
            with self.assertRaises(OSError): upgrade.apply_changes([upgrade.Change(a,b'A',b'A_NEW'),upgrade.Change(b,b'B',b'B_NEW')],self.root/'backup')
        self.assertEqual(a.read_bytes(),b'A'); self.assertEqual(b.read_bytes(),b'B')

    def test_failed_new_file_is_removed_only_if_created_by_this_run(self):
        a=self.root/'new.md'; b=self.root/'b.md'; b.write_bytes(b'B')
        actual_write=upgrade.atomic_write
        def fail_b(path,data):
            if path==b: raise OSError('simulated disk failure')
            actual_write(path,data)
        with patch.object(upgrade,'atomic_write',side_effect=fail_b):
            with self.assertRaises(OSError): upgrade.apply_changes([upgrade.Change(a,None,b'NEW'),upgrade.Change(b,b'B',b'B_NEW')],self.root/'backup')
        self.assertFalse(a.exists()); self.assertEqual(b.read_bytes(),b'B')

    def test_plan_serialization_is_read_only(self):
        a=self.root/'a.md'; a.write_bytes(b'A')
        plan=upgrade.serial_plan([upgrade.Change(a,b'A',b'NEW')])
        self.assertEqual(a.read_bytes(),b'A'); self.assertEqual(plan[0]['before_sha256'],upgrade.sha(b'A'))

if __name__=='__main__': unittest.main()
