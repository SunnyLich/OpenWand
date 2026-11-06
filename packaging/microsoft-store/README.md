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

## Preparing the next submission

The Windows artifact workflow generates a `microsoft-store-submission` artifact
after signing and installer validation. It contains `submission.json` with the
versioned Pages URL, silent installation parameters, actual installer SHA256 and
size, and five localized release notes from `docs/releases/<version>-store.json`.
Its `downloads.json` preserves existing entries and adds the new exact bytes.
These files are preparation material; generating them does not publish or submit.

After review, publish the matching GitHub release, copy that release build's
`downloads.json` to `packaging/microsoft-store/downloads.json`, and deploy Pages.
Do not use a development build's hash for a separately rebuilt release installer.
Confirm the public versioned URL returns HTTP 200 without redirects and matches
the final installer before submitting it in Partner Center. Only then replace
the Store package URL and add the localized notes. Store publication remains a
separate certification step; GitHub and the Store need not update simultaneously.
Existing users of either EXE distribution use OpenWand's in-app updater.
