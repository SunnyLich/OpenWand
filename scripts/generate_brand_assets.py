"""Generate OpenWand's icon formats from its approved PNG master.

Run with --source path/to/logo.png to import a new approved master, or without
arguments to regenerate platform, overlay, website, and circular-avatar assets.
"""
from __future__ import annotations

import argparse
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

    generate_social_preview()
    print('Generated app, overlay/tray, website, social-preview, and circular-avatar assets.')


def generate_social_preview(source: Path = MASTER, output: Path | None = None) -> None:
    """Center the approved PNG on a matching 1280 x 640 canvas."""
    output = output or ASSETS / 'social-preview.png'
    with Image.open(source) as original:
        image = original.convert('RGBA')
    background = image.getpixel((0, 0))[:3] + (255,)
    preview = Image.new('RGBA', (1280, 640), background)
    image.thumbnail((640, 640), Image.Resampling.LANCZOS)
    preview.alpha_composite(image, ((1280 - image.width) // 2, (640 - image.height) // 2))
    output.parent.mkdir(parents=True, exist_ok=True)
    preview.convert('RGB').save(output)
    if output.resolve() == (ASSETS / 'social-preview.png').resolve():
        WEB.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(output, WEB / 'social-preview.png')
    print(f'Generated logo-only preview: {output}')



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, help='Approved square PNG to copy as the master.')
    parser.add_argument('--social-preview-only', action='store_true', help='Regenerate only the logo preview.')
    parser.add_argument('--output', type=Path, help='Custom output path with --social-preview-only.')
    args = parser.parse_args()
    if args.social_preview_only:
        generate_social_preview(args.source or MASTER, args.output)
    else:
        if args.output is not None:
            parser.error('--output requires --social-preview-only')
        generate(args.source)