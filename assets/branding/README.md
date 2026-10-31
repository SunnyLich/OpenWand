# OpenWand branding

`assets/app.png` is the approved 1024 x 1024 rounded OW icon master. Its RGB
artwork is unchanged from the user-approved 7.png; only the outer corners are
transparent. Preserve its lettering, overlap, star, background color, and colors.
An identical kept copy lives at `assets/branding/openwand-icon-rounded.png`.

The generator reapplies the approved corner radius (10/65 of the canvas width)
when importing or regenerating icons, so future builds retain this version.
It preserves existing transparency and never redraws or rescales the master.

Run `python scripts/generate_brand_assets.py` to regenerate ICO, ICNS, overlay/tray
state PNGs, website icons, and `avatar.png`. The avatar adds padding around the exact
artwork so a circular crop does not cut the star. It is optional for circular uses;
the app and website use the approved composition.

The social preview is the approved PNG centered on a matching dark 1280 x 640
canvas, without extra text or graphics. The generator refreshes both
`assets/social-preview.png` and its website copy. To regenerate only this preview,
run `python scripts/generate_brand_assets.py --social-preview-only`.

Upload `assets/social-preview.png` under GitHub repository Settings > Social preview.
