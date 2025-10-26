# MeTubeEX

[![GitHub Repo](https://img.shields.io/badge/github-NaxonM%2Fmetube--extended-181717?logo=github)](https://github.com/NaxonM/metube-extended)

**MeTubeEX** is an extended edition of [alexta69/metube](https://github.com/alexta69/metube) that layers a multi-user experience, richer management tooling, and several quality-of-life upgrades on top of the yt-dlp web UI. If you enjoyed the original MeTube but needed team-ready access control, per-user isolation, inline file management, or cookie handling from the browser, this fork brings those enhancements without sacrificing the familiar workflow.

## What's new in the extended edition?

### Multi-User & Authentication
- **Secure Authentication**: Modern login UI with dark theme, session management, and rate limiting to prevent brute-force attacks.
- **Role-Based Access**: Support for admin and user roles with persistent user stores. Admins can create, manage, and disable accounts directly from the UI.
- **Per-User Isolation**: Queues, history, downloads, and cookies are fully sandboxed per user, ensuring privacy and security.

### Enhanced Downloading Capabilities
- **Yt-dlp Integration**: Advanced options for format and quality selection, playlist handling, custom output templates, and size limits with real-time progress tracking.
- **Gallery-dl Support**: Download from hundreds of supported sites with credential management, cookie stores, proxy support, retries, and archive features to prevent re-downloads.
- **Seedr Integration**: Add torrents via magnet links or files, monitor progress, and download via direct files or ZIP archives. Includes account management and automatic cleanup.
- **Proxy Downloads**: Direct file downloads for unsupported URLs with size limits, file type detection, and automatic naming.


### Streaming & Media Management
- **Adaptive HLS Streaming**: FFmpeg-powered transcoding for smooth video playback with CPU and memory limits. Falls back to byte-range streaming when needed. [WORK IN PROGRESS]
- **Inline File Management**: Rename, delete, and manage completed downloads directly from the dashboard with live updates across connected clients.
- **Custom Directories**: Support for custom download folders with validation and creation options.

### UI/UX Improvements
- **Modern Angular Frontend**: Responsive design with Bootstrap, dark/auto theming, and real-time updates via Socket.IO.
- **Dashboard Features**: Modular admin and user areas, lazy-loaded routes, bounded rendering for performance, and contextual metrics.
- **Cookie Management**: Upload, review, and clear yt-dlp cookies in Netscape format without server access. Support for multiple profiles and auto-matching.

### Admin & System Features
- **User Management**: Full admin interface for account creation, role assignment, password resets, and monitoring.
- **System Monitoring**: Real-time stats on CPU, memory, network, and uptime. Configurable proxy settings and size limits.
- **Security Enhancements**: Encrypted sessions with NaCl, bcrypt password hashing, and configurable login rate limiting.

Everything the upstream project offered—robust yt-dlp integration, playlist support, browser helpers, and Docker friendliness—remains available here, with these enhancements layered on top for a production-ready, multi-user experience.

![Application screenshot](./screenshot.gif)

## Getting started

### Option 1: One-liner install (recommended)

| Flow | Command |
|------|---------|
| **Use prebuilt images (recommended)** | `bash <(curl -fsSL https://raw.githubusercontent.com/NaxonM/metube-extended/master/install-prebuilt.sh)` |
| **Build locally** | `bash <(curl -fsSL https://raw.githubusercontent.com/NaxonM/metube-extended/master/install-local.sh)` |

- The prebuilt path pulls the latest CI image. To pin a tag, prefix the command, for example:

  ```bash
  METUBE_IMAGE=ghcr.io/naxonm/metube-extended:v2025.10.11 bash <(curl -fsSL https://raw.githubusercontent.com/NaxonM/metube-extended/master/install-prebuilt.sh)
  ```
- The local build path compiles Angular and the Docker image on the host—useful for air-gapped or customized setups.
- Both installers accept the same arguments as the core installer (e.g. `uninstall`).
- **Automatic Resource Detection**: The installer automatically detects your host's CPU and memory, then configures Docker and application limits to use only half of available resources for optimal performance.

### Option 2: Docker Compose from source

```bash
git clone https://github.com/NaxonM/metube-extended.git
cd metube-extended
docker compose up -d --build
```

Stop the stack with `docker compose down`; follow the on-screen hints during installer runs for log and shutdown shortcuts.

### Option 3: Build locally

```bash
git clone https://github.com/NaxonM/metube-extended.git
cd metube-extended/ui
npm install              # requires Node 22+
npm run lint             # optional, but recommended before building
npm run build -- --configuration production
cd ..
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python app/main.py
```

### Development quick start

- **Tooling versions:** Node 22.x LTS, npm 10+, Python 3.13. All backend modules and requirements have been updated to their latest versions for optimal performance and compatibility.
- **Key scripts:** `npm run lint`, `npm run build -- --configuration production`, `npm run test`.
- **Docker build:** `docker build -t metubeex:dev .` (uses the Angular bundle from the build stage).

### Uninstall

Run either installer with the `uninstall` argument to tear everything down:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/NaxonM/metube-extended/master/install-prebuilt.sh) uninstall
# or locally
./install-prebuilt.sh uninstall
```

## Prebuilt images & release artifacts

- **Docker images:** Every push to `master` (touching core build files) publishes fresh images to Docker Hub (`${DOCKERHUB_REPOSITORY}`) and GHCR (`ghcr.io/naxonm/metube-extended`). Pin a specific tag during install with:

  ```bash
  METUBE_PULL_IMAGES=1 METUBE_IMAGE=ghcr.io/naxonm/metube-extended:v2025.10.11 ./installer-core.sh
  ```

- **UI bundles:** Tagged releases include a prebuilt Angular bundle. Fetch it without running `npm` locally using the helper script:

  ```bash
  ./scripts/fetch-ui-bundle.sh                     # downloads latest bundle into ui/dist/metube
  ./scripts/fetch-ui-bundle.sh v2025.10.11 /tmp/ui # specific tag + custom output dir
  ```

- **Release workflow:** Create a Git tag (`git tag vYYYY.MM.DD && git push origin tag`) to trigger the full release pipeline—UI zip upload, multi-arch Docker publish, and GitHub Release creation.

## Configuration

All configuration knobs from upstream MeTube carry over. Set environment variables via `docker compose`, your orchestrator of choice, or the `.env` file consumed by the installer.

### Download behaviour

- `DOWNLOAD_MODE`: `sequential`, `concurrent`, or `limited` (default).
- `MAX_CONCURRENT_DOWNLOADS`: queue cap when using `limited` mode (default `3`).
- `DELETE_FILE_ON_TRASHCAN`: if `true`, deletes media when clearing completed items.

### Resource limits (Docker)

- `CPU_LIMIT`: Docker CPU limit (e.g., `2.0` for 2 cores).
- `MEMORY_LIMIT`: Docker memory limit (e.g., `2G` for 2GB).
- `CPU_RESERVATION`: Docker CPU reservation (e.g., `1.0`).
- `MEMORY_RESERVATION`: Docker memory reservation (e.g., `1G`).

### Resource limits (Application)

- `CPU_LIMIT_PERCENT`: Application CPU usage limit percentage (default `80`).
- `MEMORY_LIMIT_MB`: Application memory limit in MB (default `2048`).
- `DISK_READ_IOPS`: Disk read IOPS limit (default `1000`).
- `DISK_WRITE_IOPS`: Disk write IOPS limit (default `1000`).
- `NETWORK_BANDWIDTH_MB`: Network bandwidth limit in MB/s (default `62.5` for 500 Mb/s).

## Resource Limits

MeTube Extended automatically detects your host system specifications and configures resource limits to use only half of available resources for optimal performance.

### Automatic Configuration

The one-liner installer automatically:
1. Detects your host's CPU cores and memory
2. Sets Docker limits to half of available resources
3. Configures application limits (CPU 80%, memory, network 500 Mb/s, etc.)
4. Generates a `.env` file with optimized settings

### Manual Customization

If you need to adjust limits manually:
1. Edit the `.env` file generated by the installer
2. Or set environment variables in `docker-compose.yml`
3. Or use the admin panel at `/admin/system` after installation

### Troubleshooting

If the automatic resource detection fails during installation:

1. **Linux/Unix only**: The installer is optimized for Linux/Unix systems. On Windows, use WSL or Docker Desktop with Linux containers.
2. **Manual resource detection**: Run `./scripts/set-resource-limits.sh` to manually detect and update limits
3. **Use defaults**: The installer will fall back to safe defaults (2 CPU cores, 4GB RAM) if detection fails
4. **Check commands**: Ensure `nproc`, `free`, and `sysctl` are available on your system

### Available Limits

- **Docker CPU**: Half of host CPU cores (minimum 1)
- **Docker Memory**: Half of host RAM (minimum 1GB)
- **App CPU**: 80% usage limit
- **App Memory**: Half of host RAM in MB
- **Network**: 500 Mb/s bandwidth limit
- **Disk IOPS**: 1000 read/write operations
- **Concurrent Downloads**: 5 simultaneous downloads
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
- `MAX_HISTORY_ITEMS`: cap retained queue/history entries per user to keep storage usage predictable (default `200`).

### yt-dlp tuning

- `OUTPUT_TEMPLATE`, `OUTPUT_TEMPLATE_CHAPTER`, `OUTPUT_TEMPLATE_PLAYLIST` customize filenames.
- `YTDL_OPTIONS`: JSON blob passed straight to yt-dlp.
- `YTDL_OPTIONS_FILE`: path to a JSON file watched for live updates.

### Streaming

- `STREAM_TRANSCODE_ENABLED`: toggle adaptive HLS generation; when `false`, the player falls back to direct byte-range streaming.
- `STREAM_TRANSCODE_TTL_SECONDS`: duration playlists and segments stay warm on disk before being re-generated (default `1200`).
- `STREAM_TRANSCODE_FFMPEG`: path to the ffmpeg binary used for transcoding (default `ffmpeg` on `PATH`).

## Multi-user administration

- Visit **Advanced > User Management** (visible to admins) to create accounts, toggle roles, disable access, or reset passwords.
- Each user can safely upload yt-dlp cookies; files are stored under `STATE_DIR/cookies/<user-id>/` with `0600` permissions.
- Download queues, history, and notifications are scoped per user; admins can still perform maintenance globally via the API or CLI.

## Differences vs. upstream

| Feature | MeTubeEX | MeTube |
|---------|----------|--------|
| Multi-user authentication | Yes (built-in with roles) | No |
| Admin UI for account management | Yes | No |
| Per-user queue/state separation | Yes | No |
| Cookie upload/clear UI | Yes (with profiles) | Partial (manual) |
| Inline rename with live UI updates | Yes | Backend only |
| Updated login experience | Yes (modern dark UI) | No |
| Gallery-dl integration | Yes (hundreds of sites) | No |
| Seedr torrent support | Yes (magnets & files) | No |
| Proxy direct downloads | Yes | No |
| Adaptive HLS streaming | Yes (with FFmpeg) [WIP] | No |
| Real-time system monitoring | Yes | No |
| Configurable size limits | Yes | No |
| Advanced cookie management | Yes (multiple profiles) | Basic |

If you prefer the lean single-user experience, the original [alexta69/metube](https://github.com/alexta69/metube) remains an excellent choice.

## License & credits

- MeTubeEX inherits the original project license and builds directly atop the upstream codebase.
- Huge thanks to [@alexta69](https://github.com/alexta69) and all contributors whose work powers this extended edition.
- Special thanks to the following projects that enable additional functionalities:
  - [hemantapkh](https://github.com/hemantapkh/seedrcc) for Seedr integration.
  - [gallery-dl](https://github.com/mikf/gallery-dl) for gallery-dl integration.
  - [yt-dlp](https://github.com/yt-dlp/yt-dlp) for enhanced downloading capabilities.
  - [EchterAlsFake](https://github.com/EchterAlsFake) for additional website support.

Happy downloading!
