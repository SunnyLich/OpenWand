"""Generate OpenWand's icon formats from its approved PNG master.

Run with --source path/to/logo.png to import a new approved master, or without
arguments to regenerate platform, overlay, website, and circular-avatar assets.
"""
from __future__ import annotations

import argparse
import base64
import re
import shutil
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'assets'
MASTER = ASSETS / 'app.png'
WEB = ROOT / 'OpenWand Website' / 'assets'
SIZES = (16, 24, 32, 48, 64, 128, 256)


def generate(source: Path | None = None) -> None:
    if source is not None and source.resolve() != MASTER.resolve():
        with Image.open(source) as supplied:
            if supplied.width != supplied.height:
                raise ValueError('The approved icon must have a square canvas.')
            supplied.verify()
        shutil.copyfile(source, MASTER)
    with Image.open(MASTER) as original:
        icon = original.convert('RGBA')
    icon.save(ASSETS / 'app.ico', format='ICO', sizes=[(n, n) for n in SIZES])
    icon.save(ASSETS / 'app.icns', format='ICNS')
    for state in ('idle', 'listening', 'thinking', 'speaking'):
        shutil.copyfile(MASTER, ASSETS / 'doll' / f'{state}.png')
    WEB.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(MASTER, WEB / 'openwand-logo.png')
    shutil.copyfile(ASSETS / 'app.ico', WEB / 'favicon.ico')
    icon.resize((180, 180), Image.Resampling.LANCZOS).save(WEB / 'apple-touch-icon.png')

    branding = ASSETS / 'branding'
    branding.mkdir(exist_ok=True)
    avatar = Image.new('RGBA', (1024, 1024), icon.getpixel((0, 0)))
    avatar.alpha_composite(icon.resize((840, 840), Image.Resampling.LANCZOS), (92, 92))
    avatar.convert('RGB').save(branding / 'avatar.png')

    # Keep the existing social-card layout, embedding the exact PNG artwork.
    preview = ASSETS / 'social-preview.svg'
    svg = preview.read_text(encoding='utf-8')
    data = base64.b64encode(MASTER.read_bytes()).decode('ascii')
    mark = f'<image id="openwand-brand-mark" width="54" height="54" href="data:image/png;base64,{data}"/>'
    existing = r'<image id="openwand-brand-mark"[^>]*/>'
    if re.search(existing, svg):
        svg = re.sub(existing, lambda _: mark, svg, count=1)
    else:
        svg, count = re.subn(r'<g filter="url\(#icon-shadow\)">.*?</g>', lambda _: mark, svg, count=1, flags=re.S)
        if count != 1:
            raise ValueError('Could not find the social preview brand mark.')
    svg = svg.replace('All artwork is native SVG: no linked files, generated imagery, or web fonts.',
                      'The approved assets/app.png artwork is embedded; the card layout remains SVG.')
    preview.write_text(svg, encoding='utf-8', newline='\n')
    print('Generated app, overlay/tray, website, social-card source, and circular-avatar assets.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, help='Approved square PNG to copy as the master.')
    generate(parser.parse_args().source)