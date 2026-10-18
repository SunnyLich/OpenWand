# OpenWand branding

`assets/app.png` is the approved 1024 x 1024 PNG master, imported unchanged from the
user-approved 7.png. Preserve its lettering, overlap, star, background, and colors.

Run `python scripts/generate_brand_assets.py` to regenerate ICO, ICNS, overlay/tray
state PNGs, website icons, and `avatar.png`. The avatar adds padding around the exact
artwork so a circular crop does not cut the star. It is optional for circular uses;
the app and website use the approved composition.

The existing social card embeds the PNG master in `assets/social-preview.svg`.
After regenerating assets, run `powershell -ExecutionPolicy Bypass -File
scripts/render_social_preview.ps1` to refresh its PNG and website copy. Upload
`assets/social-preview.png` under GitHub repository Settings > Social preview.
