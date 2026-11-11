"""Create a Windows release ZIP and checksum from a PyInstaller build."""
from importlib import metadata
from pathlib import Path
import argparse
import hashlib
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DEPENDENCIES = [
    'Pillow', 'reportlab', 'charset-normalizer', 'pyinstaller',
    'pyinstaller-hooks-contrib', 'altgraph', 'packaging', 'pefile', 'pywin32-ctypes',
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable', type=Path)
    parser.add_argument('output', type=Path, help='New ZIP file')
    args = parser.parse_args()
    exe, output = args.executable.resolve(), args.output.resolve()
    if not exe.is_file():
        raise SystemExit('Executable not found')
    if output.exists():
        raise SystemExit('Output ZIP already exists')
    output.parent.mkdir(parents=True, exist_ok=True)
    python_license = next((p for p in [Path(sys.base_prefix) / 'LICENSE.txt', Path(sys.base_prefix) / 'LICENSE'] if p.is_file()), None)
    if not python_license:
        raise SystemExit('Python runtime license was not found')

    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.write(exe, 'MCFX-to-InDesign.exe')
        for filename in ['README.md', 'CHANGELOG.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md']:
            archive.write(ROOT / filename, filename)
        archive.write(python_license, 'licenses/Python.txt')
        for filename in ['Tcl-8.6.txt', 'Tk-8.6.txt']:
            archive.write(ROOT / 'licenses' / filename, 'licenses/' + filename)
        for name in DEPENDENCIES:
            dist = metadata.distribution(name)
            license_files = [f for f in dist.files or []
                             if ('license' in str(f).lower() or 'copying' in str(f).lower())
                             and dist.locate_file(f).is_file()]
            if not license_files:
                raise SystemExit('No license found for ' + name)
            for f in license_files:
                archive.write(dist.locate_file(f), f'licenses/dependencies/{name}/{f.as_posix()}')
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    checksum = output.parent / 'SHA256SUMS.txt'
    if checksum.exists():
        raise SystemExit('SHA256SUMS.txt already exists')
    checksum.write_text(f'{digest}  {output.name}\n', encoding='ascii')
    print(f'Created {output} ({output.stat().st_size} bytes)')
    print(f'SHA-256: {digest}')


if __name__ == '__main__':
    main()
