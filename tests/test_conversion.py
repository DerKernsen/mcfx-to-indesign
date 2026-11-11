"""Offline end-to-end tests with synthetic SQLite projects and images."""
import hashlib
from contextlib import closing
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image


SCRIPT = Path(__file__).resolve().parents[1] / 'mcfx_to_indesign.py'


def image_bytes():
    image = Image.new('RGB', (80, 60), (27, 90, 144))
    buffer = io.BytesIO()
    image.save(buffer, 'JPEG', quality=90, progressive=True)
    return buffer.getvalue()


def image_area(left, top=100, width=1000, height=750, *, filled=True, rotation=0):
    area = ET.Element('area', {'areatype': 'imagearea'})
    ET.SubElement(area, 'position', {
        'left': str(left), 'top': str(top), 'width': str(width),
        'height': str(height), 'rotation': str(rotation), 'zposition': '101',
    })
    image = ET.SubElement(area, 'image', {'filename': 'safecontainer:/photo.jpeg'} if filled else {})
    if filled:
        ET.SubElement(image, 'cutout', {'left': '-30', 'top': '-20', 'scale': '15'})
    return area


def make_project(path, *, rotation=0, crossing=False, text=False):
    root = ET.Element('fotobook')
    ET.SubElement(root, 'articleConfig', {'normalpages': '2'})
    types = ['fullcover', 'spine', 'fullcover', 'emptypage', 'normalpage', 'normalpage', 'emptypage']
    pages = []
    for kind in types:
        page = ET.SubElement(root, 'page', {'type': kind})
        ET.SubElement(page, 'bundlesize', {'width': '5400', 'height': '2050'})
        pages.append(page)
    pages[0].append(image_area(100))
    pages[3].append(image_area(2800, rotation=rotation))
    pages[5].append(image_area(2600 if crossing else 100))
    pages[5].append(image_area(1300, filled=False))
    if text:
        area = ET.SubElement(pages[0], 'area', {'areatype': 'textarea'})
        ET.SubElement(area, 'text').text = '<html><body><p>Visible text</p></body></html>'
    xml = ET.tostring(root, encoding='utf-8', xml_declaration=True) + b'\0' + b'\xfb' * 16
    with closing(sqlite3.connect(path)) as db:
        db.execute('CREATE TABLE Files(Filename TEXT PRIMARY KEY, Data BLOB, LastModified INTEGER)')
        db.execute('INSERT INTO Files VALUES (?, ?, ?)', ('data.mcf', xml, 0))
        db.execute('INSERT INTO Files VALUES (?, ?, ?)', ('photo.jpeg', image_bytes(), 0))
        db.commit()


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'synthetic.mcfx'
        self.out = self.root / 'output'

    def run_converter(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(self.source), str(self.out), *args],
            capture_output=True, text=True, timeout=60,
        )

    def test_complete_conversion_and_pixel_preservation(self):
        make_project(self.source)
        before = hashlib.sha256(self.source.read_bytes()).digest()
        result = self.run_converter()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, hashlib.sha256(self.source.read_bytes()).digest())
        layout = json.loads((self.out / 'layout.json').read_text(encoding='utf-8'))
        report = json.loads((self.out / 'conversion-report.json').read_text(encoding='utf-8'))
        self.assertEqual(len(layout['pages']), 2)
        self.assertEqual(layout['pages'][0][0]['frame'], [100.0, 100.0, 1000.0, 750.0])
        self.assertEqual(layout['pages'][0][0]['image']['bounds'], [70.0, 80.0, 1200.0, 900.0])
        self.assertIsNone(layout['pages'][1][1]['image'])
        self.assertEqual(report['interior_frames'], {'image': 2, 'empty': 1})
        self.assertEqual(report['embedded_assets'], 1)  # Reused image extracted once.
        self.assertEqual(report['coordinate_unit_mm'], 0.1)
        asset = layout['pages'][0][0]['image']['file']
        self.assertTrue(asset.endswith('.tif'))
        with Image.open(io.BytesIO(image_bytes())) as original, Image.open(self.out / 'Links' / asset) as converted:
            self.assertEqual(original.tobytes(), converted.tobytes())
        self.assertTrue((self.out / 'CEWE - Layout-Vorschau.pdf').read_bytes().startswith(b'%PDF-'))
        jsx = (self.out / 'CEWE in InDesign importieren.jsx').read_text(encoding='utf-8-sig')
        self.assertIn('rect.graphics[0].geometricBounds', jsx)
        self.assertIn('CEWE - Innenteil.indd', jsx)
        self.assertTrue((self.out / 'asset-manifest.json').is_file())

    def test_existing_output_is_never_overwritten(self):
        make_project(self.source)
        self.out.mkdir()
        marker = self.out / 'keep.txt'
        marker.write_text('unchanged', encoding='utf-8')
        result = self.run_converter()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(marker.read_text(encoding='utf-8'), 'unchanged')

    def test_nonempty_text_and_rotation_are_rejected(self):
        for kwargs, message in [({'text': True}, 'Nonempty text'), ({'rotation': 10}, 'Rotated image')]:
            with self.subTest(kwargs=kwargs):
                if self.source.exists():
                    self.source.unlink()
                make_project(self.source, **kwargs)
                result = self.run_converter()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertFalse(self.out.exists())

    def test_crossing_frame_is_rejected(self):
        make_project(self.source, crossing=True)
        result = self.run_converter()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('crosses the spread center', result.stderr)

    def test_unit_override_is_recorded(self):
        make_project(self.source)
        result = self.run_converter('--unit-mm', '0.2')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.out / 'conversion-report.json').read_text(encoding='utf-8'))
        self.assertEqual(data['coordinate_unit_mm'], 0.2)
        bad = self.run_converter('--unit-mm', 'nan')
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn('positive, finite', bad.stderr)


if __name__ == '__main__':
    unittest.main()
