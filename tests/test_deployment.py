import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('deployment',ROOT/'deploy.py')
deployment=importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployment)


class DeploymentTests(unittest.TestCase):
    def test_restore_preserves_original_files_and_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            config=root/'config';data=root/'data';state=root/'state';bindir=root/'bin'
            (config/'sway').mkdir(parents=True)
            (config/'sway/config').write_text('old sway config\n')
            (data/'frost').mkdir(parents=True)
            (data/'frost/old.txt').write_text('keep this\n')
            bindir.mkdir()
            (bindir/'frostctl').symlink_to('/old/command')
            state.mkdir()
            (state/'state.json').write_text('{"mode":"light"}')
            with patch.multiple(deployment,CONFIG=config,DATA=data,STATE=state,BIN=bindir),\
                 patch.dict(os.environ,{'HOME':str(root)}),\
                 patch.object(deployment.subprocess,'run',return_value=subprocess.CompletedProcess([],0)):
                self.assertEqual(deployment.deploy(),0)
                self.assertNotEqual((config/'sway/config').read_text(),'old sway config\n')
                backup=next((state/'backups').iterdir())
                deployment.restore(backup)
            self.assertEqual((config/'sway/config').read_text(),'old sway config\n')
            self.assertEqual((data/'frost/old.txt').read_text(),'keep this\n')
            self.assertEqual(os.readlink(bindir/'frostctl'),'/old/command')
            self.assertFalse((data/'fonts/frost').exists())
            self.assertFalse((config/'kitty').exists())
            self.assertEqual((state/'state.json').read_text(),'{"mode":"light"}')

    def test_bad_restore_manifest_is_rejected_before_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            current=root/'current';current.write_text('keep')
            (root/'manifest.json').write_text('[{"destination":"/unexpected/file","backup":null}]')
            with self.assertRaises(RuntimeError):
                deployment.restore(root)
            self.assertEqual(current.read_text(),'keep')


if __name__=='__main__':
    unittest.main()
