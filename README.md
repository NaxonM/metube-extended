# MeTubeEX

[![GitHub Repo](https://img.shields.io/badge/github-NaxonM%2Fmetube--extended-181717?logo=github)](https://github.com/NaxonM/metube-extended)

**MeTubeEX** is an extended edition of [alexta69/metube](https://github.com/alexta69/metube) that layers a multi-user experience, richer management tooling, and several quality-of-life upgrades on top of the yt-dlp web UI. If you enjoyed the original MeTube but needed team-ready access control, per-user isolation, inline file management, or cookie handling from the browser, this fork brings those enhancements without sacrificing the familiar workflow.

## What's new in the extended edition?

- Multi-user authentication and roles with a persistent user store, roles, session cookies, and Socket.IO segregation. Admins can manage accounts directly from the UI.
- Per-user download sandboxes so queues, history, and yt-dlp cookie files stay isolated per account.
- Inline file management to rename completed downloads from the dashboard with immediate updates across connected clients.
- Cookie upload console to paste, review, and clear Netscape-format cookies without touching the server.
- Modernized UX touches such as a refreshed login screen, contextual metrics, and ready-to-use dark/auto theming.

Everything the upstream project offered—robust yt-dlp integration, playlist support, browser helpers, and Docker friendliness—remains available here.

![Application screenshot](./screenshot.gif)

## Getting started

### Option 1: One-liner install (recommended)

```bash
bash <(curl -sSL https://raw.githubusercontent.com/NaxonM/metube-extended/master/install.sh) master
```

Run the script again at any time to update to the latest release. To remove the deployment, pass `uninstall`.

### Option 2: Docker Compose from source

```bash
git clone https://github.com/NaxonM/metube-extended.git
cd metube-extended
docker compose up -d --build
```

Stop the stack with `docker compose down`; follow the on-screen hints during `install.sh` runs for log and shutdown shortcuts.

### Option 3: Build locally

```bash
git clone https://github.com/NaxonM/metube-extended.git
cd metube-extended/ui
npm install
node_modules/.bin/ng build --configuration production
cd ..
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python app/main.py
```

## Configuration

All configuration knobs from upstream MeTube carry over. Set environment variables via `docker compose`, your orchestrator of choice, or the `.env` file consumed by `install.sh`.

### Download behaviour

- `DOWNLOAD_MODE`: `sequential`, `concurrent`, or `limited` (default).
- `MAX_CONCURRENT_DOWNLOADS`: queue cap when using `limited` mode (default `3`).
- `DELETE_FILE_ON_TRASHCAN`: if `true`, deletes media when clearing completed items.
- `DEFAULT_OPTION_PLAYLIST_STRICT_MODE`: enable strict playlist mode by default.
- `DEFAULT_OPTION_PLAYLIST_ITEM_LIMIT`: maximum playlist items to fetch (default `0`).

### Storage & directories

- `DOWNLOAD_DIR`: where finished downloads land (`/downloads` in the container).
- `AUDIO_DOWNLOAD_DIR`: override location for audio-only jobs (defaults to `DOWNLOAD_DIR`).
- `CUSTOM_DIRS`, `CREATE_CUSTOM_DIRS`, `CUSTOM_DIRS_EXCLUDE_REGEX`: control custom-target folders surfaced in the UI.
- `DOWNLOAD_DIRS_INDEXABLE`: expose download directories via HTTP listings.
- `STATE_DIR`: persistence path for queues and per-user metadata.
- `TEMP_DIR`: work directory for yt-dlp intermediates.

### Web server & HTTPS

- `URL_PREFIX`: base path when hosting behind a reverse proxy.
- `PUBLIC_HOST_URL` / `PUBLIC_HOST_AUDIO_URL`: override download links with external URLs.
- `HTTPS`, `CERTFILE`, `KEYFILE`: enable TLS directly in the service.
- `ROBOTS_TXT`: serve a custom `robots.txt`.

### Runtime defaults

- `UID`, `GID`, `UMASK`: container runtime user/group and umask (default `1000:1000`, `022`).
- `DEFAULT_THEME`: initial UI theme (`light`, `dark`, or `auto`).
- `LOGLEVEL`: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`, or `NONE`.
- `ENABLE_ACCESSLOG`: toggle aiohttp access logging.
- `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `SECRET_KEY`: bootstrap credentials; omitted values trigger secure defaults during first run.
- `LOGIN_RATELIMIT`: throttle login attempts (`10/minute` by default).

### yt-dlp tuning

- `OUTPUT_TEMPLATE`, `OUTPUT_TEMPLATE_CHAPTER`, `OUTPUT_TEMPLATE_PLAYLIST` customize filenames.
- `YTDL_OPTIONS`: JSON blob passed straight to yt-dlp.
- `YTDL_OPTIONS_FILE`: path to a JSON file watched for live updates.

## Multi-user administration

- Visit **Advanced > User Management** (visible to admins) to create accounts, toggle roles, disable access, or reset passwords.
- Each user can safely upload yt-dlp cookies; files are stored under `STATE_DIR/cookies/<user-id>/` with `0600` permissions.
- Download queues, history, and notifications are scoped per user; admins can still perform maintenance globally via the API or CLI.

## Differences vs. upstream

| Feature | MeTubeEX | MeTube |
|---------|----------|--------|
| Multi-user authentication | Yes (built-in) | No |
| Admin UI for account management | Yes | No |
| Per-user queue/state separation | Yes | No |
| Cookie upload/clear UI | Yes | Partial (manual) |
| Inline rename with live UI updates | Yes | Backend only |
| Updated login experience | Yes | No |

If you prefer the lean single-user experience, the original [alexta69/metube](https://github.com/alexta69/metube) remains an excellent choice.

## License & credits

- MeTubeEX inherits the original project license and builds directly atop the upstream codebase.
- Huge thanks to [@alexta69](https://github.com/alexta69) and all contributors whose work powers this extended edition.

Happy downloading!
