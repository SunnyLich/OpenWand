# Microsoft Store listing icons

These files use the approved rounded OW `assets/app.png`, scaled without changing
its lettering, overlap, star, colors, or square composition.

- `openwand-store-logo-1080.png`: 1:1 box art for the OpenWand EXE Store listing.
- `openwand-store-logo-300.png`: 1:1 app tile icon when Partner Center offers that field.

Upload the matching file under **Store listing > Store logos** for each listing
language. The approved 1024 x 1024 rounded master remains at `assets/app.png`.
Store listing PNGs keep the original opaque dark background.

Regenerate with `python scripts/generate_brand_assets.py --store-icons-only`.

Microsoft guidance:
https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msi/screenshots-and-images
https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/screenshots-and-images

## Installer download

Store listing: [OpenWand by SunnyLich](https://apps.microsoft.com/detail/XP99WCK9Q8WTG1).
The public Store product ID is `XP99WCK9Q8WTG1`.

Partner Center requires a direct HTTPS URL without redirects. GitHub Release URLs
redirect, so the Pages deployment stages the exact signed release installer using
`downloads.json`, checking its pinned SHA256 and size before deploying.

Current Store package URL:
`https://sunnylich.github.io/OpenWand/downloads/v0.12.2/OpenWand-v0.12.2-windows-x64-setup.exe`

Keep submitted version entries and their bytes unchanged while Store submissions
use them. A new installer requires a new versioned path. Pages has a 1 GB site
limit; move retained installers to a dedicated CDN before exceeding that limit.
