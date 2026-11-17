"""Controls on a real captured package; copies only, never edits original evidence.

EUNO_CAPTURE=/path/to/tenon-prototype-final python -B -m unittest -v test_evidence
"""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import prototype as p


@unittest.skipUnless(os.environ.get('EUNO_CAPTURE'), 'Set EUNO_CAPTURE to a real completed capture')
class EvidenceControls(unittest.TestCase):
    def setUp(self):
        scratch = Path.home() / 'eunobench/evidence-controls'
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='euno-evidence-control-', dir=scratch)
        self.base = Path(self.temp.name)
        self.capture = self.base / 'capture'
        shutil.copytree(Path(os.environ['EUNO_CAPTURE']), self.capture)
        self.output = self.base / 'replay'

    def tearDown(self): self.temp.cleanup()

    def test_changed_raw_capture_rejected(self):
        raw = self.capture / 'fixed/guest-1/guest.stdout'
        raw.write_bytes(raw.read_bytes() + b'changed\n')
        with self.assertRaisesRegex(ValueError, 'Changed or missing evidence'):
            p.replay(self.capture, self.output)
        self.assertFalse(self.output.exists())

    def test_missing_raw_capture_rejected(self):
        (self.capture / 'fixed/guest-1/guest.stdout').unlink()
        with self.assertRaisesRegex(ValueError, 'Changed or missing evidence'):
            p.replay(self.capture, self.output)

    def test_rehashed_lost_callback_still_rejected(self):
        raw = self.capture / 'fixed/guest-1/guest.stdout'
        original = raw.read_text()
        self.assertIn('timers=100 callbacks=100', original)
        raw.write_text(original.replace('timers=100 callbacks=100', 'timers=100 callbacks=99'))
        process = raw.parent / 'process.json'
        info = json.loads(process.read_text())
        info['stdout_sha256'] = p.sha(raw)
        p.save(process, info)
        p.seal(self.capture)
        with self.assertRaisesRegex(ValueError, 'Timer callbacks/IRQ facts failed'):
            p.replay(self.capture, self.output)
        self.assertFalse(self.output.exists())

    def test_rehashed_wrong_image_still_rejected(self):
        image = self.capture / 'fixed/build/runtime.img'
        image.write_bytes(image.read_bytes() + b'changed')
        p.seal(self.capture)
        with self.assertRaisesRegex(ValueError, 'Build identity mismatch'):
            p.replay(self.capture, self.output)


if __name__ == '__main__': unittest.main()
