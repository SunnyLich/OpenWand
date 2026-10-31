"""Generate OpenWand's icon formats from its approved PNG master.

Run with --source path/to/logo.png to import a new approved master, or without
arguments to regenerate platform, overlay, website, and circular-avatar assets.
Only the outer corners are rounded; the approved artwork is preserved.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'assets'
MASTER = ASSETS / 'app.png'
ROUNDED = ASSETS / 'branding' / 'openwand-icon-rounded.png'
WEB = ROOT / 'OpenWand Website' / 'assets'
SIZES = (16, 24, 32, 48, 64, 128, 256)


def _round_icon_edges(icon: Image.Image) -> Image.Image:
    """Apply the approved corner mask without changing the artwork's RGB pixels."""
    if icon.width != icon.height:
        raise ValueError('The approved icon must have a square canvas.')
    scale = 8
    side = icon.width * scale
    mask = Image.new('L', (side, side), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, side - 1, side - 1),
        radius=round(icon.width * 10 / 65) * scale,
        fill=255,
    )
    mask = mask.resize(icon.size, Image.Resampling.LANCZOS)
    icon.putalpha(ImageChops.darker(icon.getchannel('A'), mask))
    return icon


def generate(source: Path | None = None) -> None:
    if source is not None and source.resolve() != MASTER.resolve():
        with Image.open(source) as supplied:
            if supplied.width != supplied.height:
                raise ValueError('The approved icon must have a square canvas.')
            supplied.verify()
        shutil.copyfile(source, MASTER)
    with Image.open(MASTER) as original:
        icon = _round_icon_edges(original.convert('RGBA'))
    icon.save(MASTER)
    ROUNDED.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(MASTER, ROUNDED)
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
    artwork = icon.convert('RGB').convert('RGBA')
    avatar = Image.new('RGBA', (1024, 1024), artwork.getpixel((0, 0)))
    avatar.alpha_composite(artwork.resize((840, 840), Image.Resampling.LANCZOS), (92, 92))
    avatar.convert('RGB').save(branding / 'avatar.png')

    generate_social_preview()
    generate_store_icons()
    print('Generated app, overlay/tray, website, social-preview, and circular-avatar assets.')


def generate_social_preview(source: Path = MASTER, output: Path | None = None) -> None:
    """Center the approved PNG on a matching 1280 x 640 canvas."""
    output = output or ASSETS / 'social-preview.png'
    with Image.open(source) as original:
        image = original.convert('RGB').convert('RGBA')
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


def generate_store_icons(source: Path = MASTER) -> None:
    """Export the approved square PNG for Microsoft Store listing fields."""
    destination = ROOT / 'packaging' / 'microsoft-store'
    destination.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as original:
        image = original.convert('RGB')
    if image.width != image.height:
        raise ValueError('The Store logo source must be square.')
    for size in (1080, 300):
        image.resize((size, size), Image.Resampling.LANCZOS).save(
            destination / f'openwand-store-logo-{size}.png'
        )
    print(f'Generated Microsoft Store icons: {destination}')



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--source', type=Path,
        help='Approved square PNG to import; only its outer corners are rounded.',
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--social-preview-only', action='store_true', help='Regenerate only the logo preview.')
    mode.add_argument('--store-icons-only', action='store_true', help='Regenerate only Microsoft Store logos.')
    parser.add_argument('--output', type=Path, help='Custom output path with --social-preview-only.')
    args = parser.parse_args()
    if args.social_preview_only:
        generate_social_preview(args.source or MASTER, args.output)
    elif args.store_icons_only:
        if args.output is not None:
            parser.error('--output requires --social-preview-only')
        generate_store_icons(args.source or MASTER)
    else:
        if args.output is not None:
            parser.error('--output requires --social-preview-only')
        generate(args.source)