# MCFX to InDesign

An experimental converter for turning a **supported CEWE Fotowelt `.mcfx`
photo-book project into editable Adobe InDesign image frames**. It reads the
embedded images and layout data, then generates an InDesign script that creates
separate editable interior and cover documents. It also generates a reduced-size
PDF for visual review.

**Early prototype:** validated end to end against one image-based CEWE Fotowelt
8.2.1 project on Windows and with synthetic fixtures. This is not a general
MCFX specification or a print-ready export. Other versions, products, and
projects may differ, and unsupported effects can be omitted without detection.
Compare every page with the source before relying on the result.

## What is editable?

The InDesign output uses separate placed, linked image frames. Frame positions,
image sizes, crop offsets, empty photo frames, and their order are reconstructed
for the supported layout. You can move, replace, resize, or recrop photos in
InDesign. The original full-resolution JPEG is extracted unchanged when
possible. Progressive or `.jpeg` images are converted to TIFF; their decoded
pixel values are checked to avoid an additional JPEG compression step.

The **preview PDF is not an editable InDesign project** and deliberately uses
downsampled images. Open the generated `.indd` files for editing; export your
final print PDF from InDesign after applying the printer's requirements.

## Requirements

- Python 3.9 or later and the Python dependencies Pillow and ReportLab.
- Adobe InDesign with ExtendScript (`.jsx`) support. The Python conversion can
  prepare files without InDesign, but creating `.indd` files requires it.
- A **saved, closed** SQLite-based `.mcfx` project. The converter opens it
  read-only. Close CEWE first or use a consistent SQLite snapshot; copying a
  live database alone may miss its write-ahead log.
- Adequate free disk space. Extracted assets, compatibility TIFFs and preview
  files can be large.

## Installation

```powershell
git clone https://github.com/DerKernsen/mcfx-to-indesign.git
cd mcfx-to-indesign
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install .
```

On macOS or Linux, activate with `source .venv/bin/activate`. Running the JSX
still requires a compatible InDesign installation; the complete workflow has
only been exercised on Windows.

## Convert a project

Save and close the CEWE project, then choose an output path that **does not
exist**. Use your own paths in these examples:

```powershell
mcfx-to-indesign "C:\Photos\family-book.mcfx" "C:\Photos\family-book-export"
```

Alternatively, from a source checkout with dependencies installed:

```powershell
python .\mcfx_to_indesign.py "C:\Photos\family-book.mcfx" "C:\Photos\family-book-export"
```

The command does not overwrite the input or an existing output directory. If
conversion fails after creating the output directory, inspect it and choose a
new output path for the next attempt.

### Create the editable documents

1. Open Adobe InDesign and choose **Window → Utilities → Scripts**.
2. In the Scripts panel, right-click **User** and choose **Reveal in Explorer**
   (or the equivalent Finder command). Copy the generated
   `CEWE in InDesign importieren.jsx` into the Scripts Panel folder.
3. In InDesign, double-click the script. It creates and saves
   `CEWE - Innenteil.indd` and `CEWE - Umschlag.indd` in the output folder.
4. Check the result, particularly image crops, cover, missing links, page size,
   and the printer's bleed, binding, and color requirements.

The generated script contains **absolute paths** to the output folder and its
`Links` directory. Run it before moving the output. The `.indd` files also link
to those local assets; use InDesign's **File → Package** when moving or sharing
the project, and check the Links panel after moving.

### Output

| File or folder | Purpose |
| --- | --- |
| `Links/` | Extracted full-resolution image assets used by InDesign |
| `CEWE in InDesign importieren.jsx` | Generated script that creates the editable documents |
| `CEWE - Innenteil.indd` | Editable interior, created after running the script |
| `CEWE - Umschlag.indd` | Editable wraparound cover, created after running the script |
| `CEWE - Layout-Vorschau.pdf` | Reduced-resolution review PDF; cover followed by individual pages |
| `layout.json` | Intermediate frame and image geometry |
| `asset-manifest.json` | Mapping from embedded filenames to extracted assets and hashes |
| `conversion-report.json` | Source hash, counts, dimensions assumption, and limitations |
| `indesign-result.txt` | Success or error report produced by InDesign |

The JSON manifests and generated JSX can contain **private filenames and local
paths**. The PDF and `Links/` contain your photos. Review carefully before
sharing them. The project's `.gitignore` is a precaution, not a guarantee
against accidentally committing sensitive content.

## Supported layout and limitations

MCFX has been observed as a SQLite database with a `Files` table. The converter
reads `data.mcf` XML and image blobs without modifying the database. For the
tested project, the XML stores spread-wide positions, crop offsets and scale;
these are mapped to individually editable InDesign frames. The unit conversion
defaults to **0.1 mm per project coordinate unit**, inferred from that project.
This is not an official specification. Use `--unit-mm` if you have independently
verified a different unit, and always check the resulting dimensions.

Current boundaries:

- Expects the observed three-node cover and paired interior page structure.
  Images in secondary cover nodes, rotated image frames, frames crossing the
  middle of a spread, varying interior sizes, unsupported area types, and
  nonempty text cause the converter to stop.
- Supports embedded JPEG images with ordinary EXIF orientation. Other image
  types and nontrivial orientation are rejected.
- Empty text areas are ignored. There is no editable-text conversion yet.
- Borders, effects, masks, filters, page numbering, custom artwork or background
  colors are not faithfully converted. **Not every such feature is detected**;
  the converter may finish while omitting them.
- The reconstructed full cover is a starting point, not a printer-approved spine
  or bleed template. The output uses normal InDesign image links, not native
  CEWE layout metadata.
- The original project is read-only, but malformed or untrusted files have not
  been security-audited. Use trusted local projects.

The preview and `.indd` output are separate implementations; verify both against
CEWE. Some photos may appear soft or overly enlarged depending on the original
resolution and crop. InDesign has not been tested automatically in CI.

## Tests

Tests construct a tiny synthetic MCFX database and synthetic images in temporary
directories. They do not need CEWE, InDesign, an account, or real photo books:

```powershell
python -m unittest discover -s tests -v
```

## Acknowledgements and license

The MCFX format and crop logic were investigated using
[stfnk/Cewe2pdf](https://github.com/stfnk/Cewe2pdf) as a reference. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). This project is MIT-licensed;
see [LICENSE](LICENSE). CEWE, Adobe and InDesign are trademarks of their
respective owners. This is an independent project and is not affiliated with
or endorsed by them.
