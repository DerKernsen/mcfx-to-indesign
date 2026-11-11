"""Test GUI validation and its worker without a display server."""
from pathlib import Path
import queue
import tempfile
import unittest

from mcfx_gui import run_conversion, validate_inputs
from test_conversion import make_project


class GuiLogicTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'sample.mcfx'
        self.output = self.root / 'result'
        make_project(self.source)

    def test_validate_and_convert(self):
        source, output, unit = validate_inputs(str(self.source), str(self.output), '0.1')
        events = queue.Queue()
        run_conversion(source, output, unit, events)
        emitted = []
        while not events.empty():
            emitted.append(events.get_nowait())
        self.assertEqual(emitted[-1][0], 'success')
        self.assertEqual(emitted[-1][1]['interior_pages'], 2)
        self.assertTrue(any(kind == 'progress' for kind, _ in emitted))
        self.assertTrue((self.output / 'CEWE in InDesign importieren.jsx').is_file())

    def test_validation_rejects_bad_paths_and_scale(self):
        for source, output, unit in [('', str(self.output), '0.1'),
                                     (str(self.source), str(self.root), '0.1'),
                                     (str(self.source), str(self.output), 'nan'),
                                     (str(self.source), str(self.output), '-1'),
                                     (str(self.source), str(self.output), 'nope')]:
            with self.subTest(source=source, output=output, unit=unit):
                with self.assertRaises(ValueError):
                    validate_inputs(source, output, unit)

    def test_worker_reports_failure(self):
        events = queue.Queue()
        run_conversion(self.root / 'missing.mcfx', self.output, 0.1, events)
        emitted = []
        while not events.empty():
            emitted.append(events.get_nowait())
        self.assertEqual(emitted[-1][0], 'error')
        self.assertIn('Source file not found', emitted[-1][1])
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
