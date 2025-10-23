## Seedr Integration Roadmap

### 1. Objectives
- Provide full Seedr torrent management inside Metubex, including single/batch magnet intake, torrent uploads, progress tracking, and storage cleanup.
- Seamlessly move completed Seedr downloads to the Metubex filesystem while respecting Seedr quota limits.
- Surface Seedr account insights (quota, devices, settings) and provide controls where sensible.

### 2. Backend Workstreams
1. **Dependency & Environment Setup**
   - Add `seedrcc`, `httpx`, and `anyio` to backend dependencies.
   - Ensure version pinning aligns with Python 3.13 compatibility.

2. **Credential & Token Storage**
   - Create encrypted per-user Seedr credential store (mirroring gallery credentials) supporting:
     - Device-code flow (primary default).
     - Username/password fallback.
     - Secure refresh-token persistence.
   - Add admin utilities to revoke stored Seedr sessions.

3. **SeedrDownloadManager**
   - Implement an async manager using `AsyncSeedr` with per-user instance cache.
   - Responsibilities:
     1. Queue intake of magnet URIs, torrent files, batch lists.
     2. Submit to Seedr (`add_torrent`) and poll torrent progress via `list_contents`/torrent metadata.
     3. Upon completion, fetch payloads:
        - Single file: `fetch_file` for direct link.
        - Multi-file: `create_archive` then download archive.
     4. Stream/download to Metubex temp dir, verify size limits, then move into standard download directory and emit notifier events.
     5. Delete Seedr resources (`delete_torrent`, `delete_file`/`delete_folder`) to free storage.
     6. Handle failures with retries/backoff and clear messaging.
   - Integrate with existing notifier/socket pipeline to broadcast `added`, `updated`, `completed`, etc.
   - Provide REST endpoints mirroring `proxy`/`gallerydl` patterns for add/probe/cancel/clear/status.

4. **Batch Orchestration**
   - Accept multiline magnet submissions; split into per-item jobs, enqueue sequentially.
   - Enforce queue policy: run one Seedr job at a time per user (configurable) to avoid quota conflicts.
   - After each job finishes and cleanup succeeds, automatically start the next.
   - Provide batch metadata (total, current index, remaining) to UI.

5. **Account & Quota Insights**
   - Schedule periodic fetch of `get_memory_bandwidth`, `get_settings`, `get_devices`.
   - Cache results to present quota usage, premium status, device list.
   - Expose endpoints for manual refresh and for updating account name/password if desired.

6. **File Transfer & Storage**
   - Reuse existing download directory resolution logic.
   - Ensure temp directories are sanitized before each transfer.
   - Respect size limits (configurable per user) before starting a Seedr download transfer.

### 3. UI Enhancements
1. **Seedr Dashboard Section**
   - New tab/panel under dashboard tools dedicated to Seedr.
   - Components:
     - Credential area (connect via device code, show status, revoke).
     - Single magnet/torrent form and batch textarea with validation.
     - Upload control for `.torrent` files.
     - Batch queue table showing order, status, remaining quota.
     - Active/Completed list mirroring existing downloads with provider tag `seedr`.

2. **Account Overview Widget**
   - Display space/bandwidth usage, account tier, device list.
   - Optional controls for renaming account or managing devices.

3. **Actions & Feedback**
   - Buttons for cancel/clear per job, retry failed jobs, toggle auto-start.
   - Notifications for quota exceedance, authentication expiry, or Seedr-side errors.

4. **UX Considerations**
   - Provide instructions on Seedr limitations, including free-tier quotas.
   - Indicate when the queue is waiting for cleanup before starting next batch item.
   - Handle arcs where Seedr archive preparation may take time (show spinner / status text).

### 4. API Adjustments
- Extend backend routes (`/seedr/*`) for:
  1. Credential exchange (device start/poll, password login, logout).
  2. Job management (`add`, `batch-add`, `cancel`, `clear`, `start`).
  3. Job status summary (queue + done + batch metadata).
  4. Account info (`/seedr/account`).
- Update websocket event payloads to include provider-specific metadata (Seedr IDs, batch progress).

### 5. Migration & Configuration
- Add new environment/config keys:
  - `SEEDR_ENABLED`, `SEEDR_BATCH_CONCURRENCY`, `SEEDR_TEMP_DIR`, `SEEDR_SIZE_LIMIT_MB`.
- Update startup scripts to initialize Seedr credential store directories.
- Provide CLI for admins to purge all Seedr tokens if needed.

### 6. Testing Strategy
- Unit tests for SeedrDownloadManager logic (queueing, polling, cleanup loops) with mocked Seedr API.
- Integration tests covering credential flow, single magnet, batch execution, failure scenarios.
- Frontend tests for new components (form validation, state transitions).

### 7. Rollout Plan
1. Ship backend foundation behind `SEEDR_ENABLED` flag.
2. Add minimal UI for credential setup and single magnet.
3. Expand to batch processing and account panels.
4. Gather feedback, then enable by default once stable.
