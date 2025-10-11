# Gallery-DL Integration Plan

## Goals
- Invoke the official `gallery-dl` GitHub release (packaged under `gallery-dl-master`) without modifying its sources so upgrades remain a simple drop-in from upstream.
- Extend MetubeEX so URLs supported only by `gallery-dl` receive a tailored flow while reusing existing queueing, notifications, and download history features.

## Detection Flow
1. Teach `app/main.py` download intake to consult `gallery_dl.extractor.find(url)` (or a curated matcher) before delegating to yt-dlp.
2. When a match is found, respond with a dedicated status (e.g., `{'status': 'gallerydl', 'options': {...}}`) consumed by the UI instead of dropping into the proxy prompt.

## Frontend Updates
1. In `ui/src/app/app.component.ts`, intercept this new status in `addDownload` and open a modal specific to gallery-dl (no folder picker; show optional range/tags filters if desired).
2. Let the modal collect extractor options, then POST them to a new endpoint (e.g., `gallerydl/add`) and rely on existing socket events for progress.

## Backend Execution
1. Add a `GalleryDlJob` class alongside `ProxyDownloadJob` that wraps a `subprocess` call to the bundled gallery-dl executable (`python -m gallery_dl` or the release binary) so we rely entirely on the upstream release code.
2. Stream stdout via a queue translating gallery-dl progress into `DownloadInfo` updates so the notifier emits `added`, `updated`, and `completed` events identical to yt-dlp jobs.
3. Stage downloads under a per-job temp directory (e.g., `<TEMP_DIR>/gallerydl/<job id>`), zip its contents once the process finishes, then move the archive into `config.DOWNLOAD_DIR`.
4. After zipping, remove the temp directory, register the archive in the queue’s `done` store, and persist history just like other downloads.

## Storage & Delivery
- Reuse `PUBLIC_HOST_URL` for serving the final archive; filenames should include the gallery title and job id to avoid collisions.
- Store any gallery-dl configuration passed from the UI in the job metadata so replays or requeues can re-run with the same options.

## Administration & Updates
- Expose an admin-only control that hits GitHub’s release API (or downloads a chosen release asset) to refresh the `gallery-dl` bundle in place, followed by a restart, keeping integration code untouched.
- Add a dashboard button (e.g., near advanced options) that opens a modal listing supported sites aggregated from yt-dlp, gallery-dl, and any auxiliary providers so users can see coverage in one place.

## Testing & Validation
- Add unit tests/mocks for URL detection and status emission.
- Exercise end-to-end flows: submit a gallery URL, confirm modal opens, ensure progress events update the queue, verify the final archive is downloadable, and confirm temp files are purged.
- Regression-test yt-dlp and proxy flows to ensure the new detection branch doesn’t interfere.
