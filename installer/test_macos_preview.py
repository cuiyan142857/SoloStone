"""Tests for the preview launcher without copying or starting Hearthstone."""
import os
from pathlib import Path
import plistlib
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import macos_preview as preview


class MacPreviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def test_executable_comes_from_bundle_and_cannot_point_outside(self):
        client = self.root / "client"
        bundle = client / preview.APP / "Contents"
        binaries = bundle / "MacOS"
        binaries.mkdir(parents=True)
        executable = binaries / "Hearthstone"
        executable.touch(mode=0o700)
        plist = bundle / "Info.plist"
        plist.write_bytes(plistlib.dumps({"CFBundleExecutable": executable.name}))
        self.assertEqual(preview.game_executable(client), executable)
        plist.write_bytes(plistlib.dumps({"CFBundleExecutable": "../../outside"}))
        with self.assertRaisesRegex(preview.PreviewError, "Invalid Hearthstone bundle executable name"):
            preview.game_executable(client)
        outside = self.root / "outside"
        executable.rename(outside)
        executable.symlink_to(outside)
        plist.write_bytes(plistlib.dumps({"CFBundleExecutable": executable.name}))
        with self.assertRaises(preview.PreviewError):
            preview.game_executable(client)

    def test_cannot_replace_an_unmarked_client(self):
        client = self.root / "client"
        client.mkdir()
        (client / "original").touch()
        staged = self.root / "staged"
        staged.mkdir()
        with self.assertRaises(preview.PreviewError):
            preview.replace_client(self.root, staged)
        self.assertTrue((client / "original").exists())

    def test_failed_replacement_restores_the_active_copy(self):
        client = self.root / "client"
        client.mkdir()
        (client / preview.STAMP).write_text("old", encoding="ascii")
        missing = self.root / "missing"
        with self.assertRaises(FileNotFoundError):
            preview.replace_client(self.root, missing)
        self.assertEqual((client / preview.STAMP).read_text(encoding="ascii"), "old")
        self.assertFalse((self.root / "client.previous").exists())

    def test_save_switch_requires_the_current_run(self):
        run = "previous-run"
        token = "a" * 32
        started = time.time()
        request = self.root / "profile-switch.xml"
        request.write_text(f"<ProfileSwitchRequest><Version>1</Version><RunId>{run}</RunId>"
                           f"<Token>{token}</Token></ProfileSwitchRequest>", encoding="ascii")
        self.assertEqual(preview.switch_token(self.root, run, started), token)
        with self.assertRaisesRegex(preview.PreviewError, "does not match"):
            preview.switch_token(self.root, "other-run", started)
        os.utime(request, (started - 60, started - 60))
        with self.assertRaisesRegex(preview.PreviewError, "stale"):
            preview.switch_token(self.root, run, started)

    def test_launch_refuses_to_create_a_game_process_when_sandbox_check_fails(self):
        with (patch.object(preview, "verified_client", return_value=(None, None, False)),
              patch.object(preview, "check_sandbox", side_effect=preview.PreviewError("denied")),
              patch.object(preview, "launch_once") as start):
            with self.assertRaisesRegex(preview.PreviewError, "denied"):
                preview.launch(self.root)
            start.assert_not_called()

    @unittest.skipUnless(sys.platform == "darwin", "macOS Seatbelt is required")
    def test_seatbelt_denies_network_and_writes_outside_the_preview(self):
        preview.check_sandbox(self.root)


if __name__ == "__main__":
    unittest.main()
