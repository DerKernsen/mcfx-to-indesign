"""Convert the observed CEWE 8.2.1 MCFX layout to editable InDesign frames.

Based on format observations from a saved project and the MIT-licensed
https://github.com/stfnk/Cewe2pdf. This is deliberately conservative: the
converter stops on image rotation, spanning frames, or nonempty text.
"""
from pathlib import Path
from collections import Counter
from contextlib import closing
import argparse
import hashlib
import html.parser
import io
import json
import math
import sqlite3
import sys
import tempfile
import xml.etree.ElementTree as ET

from PIL import Image, ImageOps
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

def sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class TextOnly(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.visible = []
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('head', 'style', 'script'):
            self.depth += 1

    def handle_endtag(self, tag):
        if tag in ('head', 'style', 'script'):
            self.depth -= 1

    def handle_data(self, value):
        if not self.depth:
            self.visible.append(value)


def convert(source, output, unit_mm=0.1, progress=None):
    """Convert a saved MCFX; return a report and optionally emit progress text."""
    if not math.isfinite(unit_mm) or unit_mm <= 0:
        raise ValueError('--unit-mm must be a positive, finite number')
    scale = unit_mm * 72 / 25.4
    src, out = Path(source).resolve(), Path(output).resolve()
    if not src.is_file():
        raise FileNotFoundError('Source file not found')
    if out.exists():
        raise FileExistsError('Output already exists; refusing to overwrite')
    def notify(message):
        if progress:
            progress(message)

    notify('Reading saved project...')
    with closing(sqlite3.connect(src.as_uri() + '?mode=ro', uri=True)) as db:
        row = db.execute('SELECT Data FROM Files WHERE Filename=?', ('data.mcf',)).fetchone()
        if not row:
            raise ValueError('No data.mcf in Files table')
        xml = bytes(row[0]).split(b'\0', 1)[0]
        root = ET.fromstring(xml)
        nodes = root.findall('page')
        if len(nodes) < 5 or [x.get('type') for x in nodes[:3]] != ['fullcover', 'spine', 'fullcover']:
            raise ValueError('Unsupported cover structure')
        if any(a.get('areatype') == 'imagearea' for page in nodes[1:3] for a in page.findall('area')):
            raise ValueError('Images in secondary cover nodes are not supported')
        if any(x.get('type') not in ('normalpage', 'emptypage') for x in nodes[3:]):
            raise ValueError('Unsupported page structure')
        if (len(nodes) - 3) % 2:
            raise ValueError('Expected complete paired page nodes')
        bw = float(nodes[3].find('bundlesize').get('width'))
        bh = float(nodes[3].find('bundlesize').get('height'))
        half = bw / 2
        if any(abs(float(p.find('bundlesize').get('width'))-bw)>0.01 or abs(float(p.find('bundlesize').get('height'))-bh)>0.01 for p in nodes[3:]):
            raise ValueError('Interior spread sizes vary; unsupported')
        coverw = float(nodes[0].find('bundlesize').get('width'))
        coverh = float(nodes[0].find('bundlesize').get('height'))

        unknown = Counter(a.get('areatype') for page in nodes for a in page.findall('area') if a.get('areatype') not in ('imagearea','smartlayoutarea','textarea','spinetextarea'))
        if unknown:
            raise ValueError('Unsupported area types: ' + str(dict(unknown)))
        for a in root.iter('area'):
            if a.get('areatype') in ('textarea','spinetextarea'):
                text = a.find('text')
                if text is not None:
                    parser = TextOnly()
                    parser.feed(text.text or '')
                    if ''.join(parser.visible).strip():
                        raise ValueError('Nonempty text needs explicit conversion; refusing to discard it')
        if any(float(a.find('position').get('rotation', '0')) for a in root.iter('area') if a.get('areatype')=='imagearea'):
            raise ValueError('Rotated image frames are not supported')

        notify('Extracting images and reconstructing page frames...')
        out.mkdir(parents=True)
        links = out / 'Links'
        links.mkdir()
        assets = {}
        preview_paths = {}

        def asset(name):
            name = name.removeprefix('safecontainer:/')
            if name in assets:
                return assets[name]
            found = db.execute('SELECT Data FROM Files WHERE Filename=?', (name,)).fetchone()
            if not found:
                raise ValueError('Missing embedded image ' + name)
            data = bytes(found[0])
            item_id = len(assets) + 1
            with Image.open(io.BytesIO(data)) as im:
                im.load()
                if im.format != 'JPEG':
                    raise ValueError('Only embedded JPEG photos are supported: ' + name)
                if im.getexif().get(274,1) != 1:
                    raise ValueError('Nontrivial image orientation not yet supported: ' + name)
                size = im.size
                if Path(name).suffix.lower() == '.jpeg' or im.info.get('progressive'):
                    # InDesign failed on a progressive JPEG in one tested project.
                    # TIFF preserves the already-decoded pixels without another JPEG loss.
                    filename = f'asset_{item_id:03d}.tif'
                    kwargs = {'compression':'tiff_deflate'}
                    if im.info.get('icc_profile'):
                        kwargs['icc_profile'] = im.info['icc_profile']
                    im.save(links / filename, **kwargs)
                    with Image.open(links / filename) as check:
                        if check.mode != im.mode or check.size != im.size or hashlib.sha256(check.tobytes()).digest() != hashlib.sha256(im.tobytes()).digest():
                            raise ValueError('TIFF pixel verification failed: ' + name)
                else:
                    filename = f'asset_{item_id:03d}.jpg'
                    (links / filename).write_bytes(data)
                    if hashlib.sha256((links/filename).read_bytes()).digest()!=hashlib.sha256(data).digest():
                        raise ValueError('JPEG extraction verification failed: ' + name)
                info = {'file':filename,'size':list(size),'source':name,'source_sha256':hashlib.sha256(data).hexdigest()}
                assets[name] = info
                if item_id % 10 == 0:
                    notify(f'Extracted {item_id} unique images...')
            return info

        def parse_area(a, xoff=0):
            pos = a.find('position')
            x = float(pos.get('left')) - xoff
            y = float(pos.get('top'))
            w = float(pos.get('width'))
            h = float(pos.get('height'))
            item = {'frame':[x,y,w,h], 'z':float(pos.get('zposition','0'))}
            image = a.find('image')
            filename = image.get('filename') if image is not None else None
            if filename:
                info = asset(filename)
                cut = image.find('cutout')
                if cut is None:
                    raise ValueError('Missing crop information')
                sc = float(cut.get('scale','1'))
                item['image'] = {'file':info['file'], 'bounds':[x+float(cut.get('left','0')), y+float(cut.get('top','0')), info['size'][0]*sc, info['size'][1]*sc]}
            else:
                item['image'] = None
            return item

        cover_areas = sorted((parse_area(a) for a in nodes[0].findall('area') if a.get('areatype')=='imagearea'),key=lambda x:x['z'])
        pages = []
        pairs = list(zip(nodes[3::2], nodes[4::2]))
        for pair_index, pair in enumerate(pairs):
            all_areas = [a for page in pair for a in page.findall('area') if a.get('areatype')=='imagearea']
            for side in (0, 1):
                if (pair_index == 0 and side == 0) or (pair_index == len(pairs)-1 and side == 1):
                    continue
                items = []
                for a in all_areas:
                    pos = a.find('position')
                    x,w = float(pos.get('left')),float(pos.get('width'))
                    if x < half-0.01 and x+w > half+0.01:
                        raise ValueError('Image frame crosses the spread center')
                    if (0 if x<half else 1)==side:
                        items.append(parse_area(a, half*side))
                pages.append(sorted(items,key=lambda x:x['z']))
        expected = int(root.find('articleConfig').get('normalpages'))
        if len(pages) != expected:
            raise ValueError(f'Expected {expected} interior pages, got {len(pages)}')

        # PDF is an independent, downsampled visual reference only; the native
        # InDesign project uses the extracted full-resolution linked assets.
        def draw_pdf_item(c, item, page_h, scratch):
            x,y,w,h = [n*scale for n in item['frame']]
            data=item['image']
            if data is None:
                return
            f = links/data['file']
            if data['file'] not in preview_paths:
                tmp=Path(scratch)/(f.stem+'.jpg')
                with Image.open(f) as im:
                    im=ImageOps.exif_transpose(im).convert('RGB')
                    im.thumbnail((1600,1600))
                    im.save(tmp,'JPEG',quality=85)
                preview_paths[data['file']]=tmp
            ix,iy,iw,ih=[n*scale for n in data['bounds']]
            c.saveState()
            path=c.beginPath();path.rect(x,page_h-y-h,w,h);c.clipPath(path,stroke=0,fill=0)
            c.drawImage(ImageReader(str(preview_paths[data['file']])),ix,page_h-iy-ih,iw,ih)
            c.restoreState()
        pdf=out/'CEWE - Layout-Vorschau.pdf'
        notify('Rendering the visual preview...')
        c=canvas.Canvas(str(pdf),pagesize=(coverw*scale,coverh*scale),pageCompression=1)
        with tempfile.TemporaryDirectory() as tmp:
            for it in cover_areas: draw_pdf_item(c,it,coverh*scale,tmp)
            c.showPage()
            for index, page in enumerate(pages, 1):
                c.setPageSize((half*scale,bh*scale))
                for it in page: draw_pdf_item(c,it,bh*scale,tmp)
                c.showPage()
                if index % 10 == 0 or index == len(pages):
                    notify(f'Rendered {index} of {len(pages)} interior pages...')
        c.save()

        notify('Writing the InDesign script and conversion report...')
        payload={'width':half,'height':bh,'coverwidth':coverw,'coverheight':coverh,'scale':scale,'pages':pages,'cover':cover_areas}
        (out/'layout.json').write_text(json.dumps(payload,indent=2),encoding='utf-8')
        (out/'asset-manifest.json').write_text(json.dumps(list(assets.values()),indent=2,ensure_ascii=False),encoding='utf-8')

        jsx=r'''#target "InDesign"
(function(){
    var data = PROJECT_DATA;
    var linkDir = new Folder(LINK_DIR);
    var outDir = new Folder(OUTPUT_DIR);
    var logFile = new File(outDir.fsName + "/indesign-result.txt");
    function log(s) { logFile.encoding="UTF-8"; logFile.open("w"); logFile.write(s); logFile.close(); }
    var oldUnit=app.scriptPreferences.measurementUnit;
    var interior=null, cover=null;
    function place(page, item) {
        var base=page.bounds, f=item.frame, t=data.scale;
        var rect=page.rectangles.add({geometricBounds:[base[0]+f[1]*t,base[1]+f[0]*t,base[0]+(f[1]+f[3])*t,base[1]+(f[0]+f[2])*t]});
        rect.strokeWeight=0;
        if (!item.image) return;
        var file=new File(linkDir.fsName + "/" + item.image.file);
        if (!file.exists) throw Error("Missing link: " + file.fsName);
        try { rect.place(file); } catch(e) { throw Error("Could not place " + item.image.file + ": " + e.message); }
        var b=item.image.bounds;
        rect.graphics[0].geometricBounds=[base[0]+b[1]*t,base[1]+b[0]*t,base[0]+(b[1]+b[3])*t,base[1]+(b[0]+b[2])*t];
    }
    try {
        app.scriptPreferences.measurementUnit=MeasurementUnits.POINTS;
        interior=app.documents.add();
        interior.documentPreferences.facingPages=true;
        interior.documentPreferences.pageWidth=data.width*data.scale;
        interior.documentPreferences.pageHeight=data.height*data.scale;
        interior.documentPreferences.pagesPerDocument=data.pages.length;
        for(var p=0;p<data.pages.length;p++) for(var j=0;j<data.pages[p].length;j++) place(interior.pages.item(p),data.pages[p][j]);
        var bookFile=new File(outDir.fsName+"/CEWE - Innenteil.indd");
        if(bookFile.exists) throw Error("Refusing to overwrite " + bookFile.fsName);
        interior.save(bookFile);
        cover=app.documents.add();
        cover.documentPreferences.facingPages=false;
        cover.documentPreferences.pageWidth=data.coverwidth*data.scale;
        cover.documentPreferences.pageHeight=data.coverheight*data.scale;
        for(var k=0;k<data.cover.length;k++) place(cover.pages.item(0),data.cover[k]);
        var coverFile=new File(outDir.fsName+"/CEWE - Umschlag.indd");
        if(coverFile.exists) throw Error("Refusing to overwrite " + coverFile.fsName);
        cover.save(coverFile);
        log("SUCCESS\nInterior pages: " + interior.pages.length + "\nInterior graphics: " + interior.allGraphics.length + "\nInterior links: " + interior.links.length + "\nCover graphics: " + cover.allGraphics.length + "\nCover links: " + cover.links.length);
        alert("Conversion complete: " + interior.pages.length + " interior pages and a separate cover. Both documents are saved in the output folder.");
    } catch(e) {
        log("ERROR: " + e.message + " line " + e.line);
        alert("Conversion stopped: " + e.message + " (line " + e.line + "). See indesign-result.txt.");
    } finally { app.scriptPreferences.measurementUnit=oldUnit; }
})();
'''
        jsx=(jsx.replace('PROJECT_DATA',json.dumps(payload,ensure_ascii=True,separators=(',',':')))
                .replace('LINK_DIR',json.dumps(links.as_posix()))
                .replace('OUTPUT_DIR',json.dumps(out.as_posix())))
        (out/'CEWE in InDesign importieren.jsx').write_text(jsx,encoding='utf-8-sig')
        counts=Counter('image' if x['image'] else 'empty' for page in pages for x in page)
        report={'source':str(src),'source_sha256':sha256_file(src),'coordinate_unit_mm':unit_mm,'interior_pages':len(pages),'interior_frames':dict(counts),'cover_frames':len(cover_areas),'embedded_assets':len(assets),'covered_area_types':dict(Counter(a.get('areatype') for a in root.iter('area'))),'limitations':['No support for nonempty text, rotated images, crossing image frames, filters, or arbitrary background artwork; some unsupported features may not be detected.','The PDF is a downsampled visual reference; compare it with CEWE.','The coordinate-unit size is inferred, not a documented format guarantee; verify the printer specifications.']}
        (out/'conversion-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        notify('Conversion complete.')
        return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source', type=Path, help='Path to a quiescent or snapshot MCFX')
    ap.add_argument('output', type=Path, help='New output directory (must not exist)')
    ap.add_argument('--unit-mm', type=float, default=0.1,
                    help='Millimetres per project coordinate unit (default: 0.1; verify against your project)')
    args = ap.parse_args()
    report = convert(args.source, args.output, args.unit_mm)
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
