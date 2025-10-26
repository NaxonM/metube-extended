import { Injectable } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Observable, of, Subject, BehaviorSubject } from 'rxjs';
import { catchError, map, tap } from 'rxjs/operators';
import { MeTubeSocket } from './metube-socket';
import { buildApiUrl } from './api-base.util';

export interface GalleryDlPrompt {
  url: string;
  title?: string;
  auto_start: boolean;
  options: string[];
  credential_id?: string | null;
  cookie_name?: string | null;
  proxy?: string | null;
  retries?: number | null;
  sleep_request?: string | null;
  sleep_429?: string | null;
  write_metadata?: boolean;
  write_info_json?: boolean;
  write_tags?: boolean;
  download_archive?: boolean;
  archive_id?: string | null;
}

export interface Status {
  status: string;
  msg?: string;
  proxy?: ProxySuggestion;
  gallerydl?: GalleryDlPrompt;
  backend_choice?: BackendChoice;
}

export interface BackendChoice {
  url: string;
  title?: string;
  gallerydl: GalleryDlPrompt;
  ytdlp: YtdlpChoice;
}

export interface YtdlpChoice {
  quality: string;
  format: string;
  folder: string;
  custom_name_prefix: string;
  playlist_strict_mode: boolean;
  playlist_item_limit: number;
  auto_start: boolean;
}

export interface ProxySuggestion {
  url: string;
  quality: string;
  format: string;
  folder: string;
  custom_name_prefix: string;
  playlist_strict_mode: boolean;
  playlist_item_limit: number;
  auto_start: boolean;
  size_limit_mb: number;
  limit_enabled: boolean;
}

export interface ProxyProbeResponse extends Status {
  filename?: string;
  size?: number;
  content_type?: string;
  disposition?: string;
  limit_exceeded?: boolean;
}

export interface ProxyAddRequest {
  url: string;
  title?: string;
  folder: string;
  custom_name_prefix: string;
  auto_start: boolean;
  size_limit_mb?: number | null;
}

export interface ProxyAddResponse extends Status {
  id?: string;
}

export interface ProxySettings {
  limit_enabled: boolean;
  limit_mb: number;
}

export interface SystemStats {
  cpu: {
    percent: number;
    cores: number;
    threads: number;
    limit_percent: number;
  };
  memory: {
    percent: number;
    used: number;
    available: number;
    total: number;
    limit_mb: number;
  };
  swap: {
    percent: number;
    used: number;
    total: number;
  };
  network: {
    bytes_sent: number;
    bytes_recv: number;
    limit_mb: number;
  };
  disk: {
    read_count: number;
    write_count: number;
    read_bytes: number;
    write_bytes: number;
    read_iops_limit: number;
    write_iops_limit: number;
  };
  uptime_seconds: number;
  timestamp: number;
}

export interface ResourceLimits {
  cpu_limit_percent: number;
  memory_limit_mb: number;
  disk_read_iops: number;
  disk_write_iops: number;
  network_bandwidth_mb: number;
  max_concurrent_downloads: number;
}

export type ProxySettingsResponse = ProxySettings & Partial<Status>;
export type SystemStatsResponse = SystemStats & Partial<Status>;
export type ResourceLimitsResponse = ResourceLimits & Partial<Status>;

export interface GalleryDlAddRequest {
  url: string;
  title?: string;
  auto_start: boolean;
  options: string[];
  credential_id?: string | null;
  cookie_name?: string | null;
  proxy?: string | null;
  retries?: number | null;
  sleep_request?: string | null;
  sleep_429?: string | null;
  write_metadata?: boolean;
  write_info_json?: boolean;
  write_tags?: boolean;
  download_archive?: boolean;
  archive_id?: string | null;
}

export interface SupportedSitesResponse extends Partial<Status> {
  providers?: Record<string, string[]>;
}

export interface SeedrAccountSummary {
  username?: string | null;
  user_id?: number | string | null;
  premium?: number | boolean | null;
  space_used?: number | null;
  space_max?: number | null;
  bandwidth_used?: number | null;
  bandwidth_max?: number | null;
  country?: string | null;
}

export interface SeedrDeviceChallenge {
  device_code: string;
  user_code: string;
  verification_url: string;
  interval: number;
  expires_in: number;
  expires_at?: number;
}

export interface SeedrStatusResponse extends Partial<Status> {
  connected: boolean;
  account?: SeedrAccountSummary | null;
  device_challenge?: SeedrDeviceChallenge | null;
  token_created_at?: number;
  token_updated_at?: number;
  jobs?: SeedrJobSnapshot;
}

export interface SeedrDeviceStartResponse extends Partial<Status> {
  challenge?: SeedrDeviceChallenge;
}

export interface SeedrDeviceCompleteResponse extends Partial<Status> {
  account?: SeedrAccountSummary | null;
}

export interface SeedrAddRequest {
  magnet?: string;
  magnet_link?: string;
  magnet_links?: string[];
  magnet_text?: string;
  torrent_file?: string;
  title?: string;
  folder?: string;
  custom_name_prefix?: string;
  folder_id?: string;
  auto_start?: boolean;
}

export interface SeedrAddResponse extends Partial<Status> {
  id?: string;
  results?: (Partial<Status> & { id?: string })[];
  count?: number;
}

export interface SeedrUploadResponse extends Partial<Status> {
  id?: string;
}

export interface SeedrJobEntry {
  id: string;
  title: string;
  stage: string;
  status: string;
  msg: string;
  percent: number | null;
  size?: number | null;
  created_at?: number;
  location: 'pending' | 'in_progress' | 'completed';
  provider?: string | null;
}

export interface SeedrJobSnapshot {
  pending?: SeedrJobEntry[];
  in_progress?: SeedrJobEntry[];
  completed?: SeedrJobEntry[];
  failed?: SeedrJobEntry[];
}

export interface SeedrClearResponse extends Partial<Status> {
  removed?: {
    torrents: number;
    folders: number;
    files: number;
  };
  errors?: string[];
}

export interface GalleryDlCredentialSummary {
  id: string;
  name: string;
  extractor?: string | null;
  username?: string | null;
  has_password?: boolean;
  created_at: number;
  updated_at: number;
}

export interface GalleryDlCredentialDetail extends GalleryDlCredentialSummary {
  values: {
    username?: string | null;
    twofactor?: string | null;
    extra_args?: string[];
  };
}

export interface GalleryDlCookieFile {
  name: string;
  size: number;
  updated_at: number;
  content?: string;
}

export interface GalleryDlCredentialPayload {
  name: string;
  extractor?: string | null;
  username?: string | null;
  password?: string | null;
  twofactor?: string | null;
  extra_args?: string[];
}

export interface GalleryDlCookiePayload {
  name: string;
  content: string;
}

export interface YtdlpCookieProfile {
  id: string;
  name: string;
  tags: string[];
  hosts: string[];
  default: boolean;
  created_at: number;
  updated_at: number;
  last_used_at?: number | null;
}

export interface SaveCookieProfilePayload {
  cookies?: string | null;
  name?: string;
  hosts?: string[];
  tags?: string[];
  default?: boolean;
  profile_id?: string;
}

export interface Download {
  id: string;
  title: string;
  url: string;
  storage_key?: string;
  quality: string;
  format: string;
  folder: string;
  custom_name_prefix: string;
  playlist_strict_mode: boolean;
  playlist_item_limit: number;
  status: string;
  msg: string;
  percent: number;
  speed: number;
  eta: number;
  filename: string;
  error?: string;
  size?: number;
  checked?: boolean;
  deleting?: boolean;
}

export interface CurrentUser {
  id: string;
  username: string;
  role: 'admin' | 'user';
}

export interface CookieStatusResponse {
  has_cookies: boolean;
  state: 'missing' | 'unknown' | 'valid' | 'invalid';
  message?: string;
  checked_at?: number;
  profile_count?: number;
  default_profile_id?: string;
}

export interface ManagedUser extends CurrentUser {
  disabled: boolean;
  created_at: number;
  updated_at: number;
  last_login_at?: number | null;
  password_updated?: boolean;
}

export interface DownloadMetrics {
  active: number;
  queued: number;
  completed: number;
  failed: number;
  totalSpeed: number;
  queueSize: number;
  doneSize: number;
}

export interface DownloadUpdateEvent {
  id: string;
  sourceUrl: string;
  location: 'queue' | 'done';
}

@Injectable({
  providedIn: 'root'
})
export class DownloadsService {
  loading = true;
  queue = new Map<string, Download>();
  done = new Map<string, Download>();
  queueChanged = new Subject<void>();
  doneChanged = new Subject<void>();
  customDirsChanged = new Subject<any>();
  ytdlOptionsChanged = new Subject<any>();
  configurationChanged = new Subject<any>();
  updated = new Subject<DownloadUpdateEvent>();

  private metricsState: DownloadMetrics = this.createEmptyMetrics();
  private metricsSubject = new BehaviorSubject<DownloadMetrics>(this.createEmptyMetrics());
  readonly metrics$ = this.metricsSubject.asObservable();
  private maxHistoryItems = 200;
  private currentUserCache: CurrentUser | null = null;
  private currentUserInitialized = false;

  configuration: any = {};
  customDirs = {};
  private adaptiveStreamingEnabled = true;
  private adaptiveStreamingStatus: string | null = null;
  private adaptiveStreamingMessage = '';

  constructor(private http: HttpClient, private socket: MeTubeSocket) {
    socket.fromEvent('all').subscribe((strdata: string) => {
      this.loading = false;
      let data: [[[string, Download]], [[string, Download]]] = JSON.parse(strdata);
      this.queue.clear();
      this.done.clear();
      this.resetMetricsState();

      data[0].forEach(entry => {
        const raw = entry[1];
        if (!raw) {
          return;
        }
        const normalized = this.normalizeDownload(raw);
        const storageKey = normalized.storage_key;
        this.queue.set(storageKey, normalized);
        this.applyQueueMetrics(undefined, normalized);
      });

      data[1].forEach(entry => {
        const raw = entry[1];
        if (!raw) {
          return;
        }
        const normalized = this.normalizeDownload(raw);
        const storageKey = normalized.storage_key;
        this.done.set(storageKey, normalized);
        this.applyDoneMetrics(undefined, normalized);
      });

      this.trimDoneHistory();
      this.emitMetrics();
      this.queueChanged.next();
      this.doneChanged.next();
    });
    socket.fromEvent('added').subscribe((strdata: string) => {
      const parsed = JSON.parse(strdata);
      const storageKey = parsed.storage_key || parsed.url;
      const previous = this.queue.get(storageKey);
      const data = this.normalizeDownload(parsed, previous);
      this.queue.set(storageKey, data);
      this.applyQueueMetrics(previous, data);
      this.emitMetrics();
      this.queueChanged.next();
    });
    socket.fromEvent('updated').subscribe((strdata: string) => {
      const parsed = JSON.parse(strdata);
      const storageKey = parsed.storage_key || parsed.url;
      const existing = this.queue.get(storageKey);
      const data = this.normalizeDownload(parsed, existing);
      this.queue.set(storageKey, data);
      this.applyQueueMetrics(existing, data);
      this.emitMetrics();
      this.updated.next({ id: storageKey, sourceUrl: data.url, location: 'queue' });
    });
    socket.fromEvent('completed').subscribe((strdata: string) => {
      const parsed = JSON.parse(strdata);
      const storageKey = parsed.storage_key || parsed.url;
      const existing = this.queue.get(storageKey);
      const data = this.normalizeDownload(parsed, existing);
      if (existing) {
        this.queue.delete(storageKey);
        this.applyQueueMetrics(existing, undefined);
      }
      this.done.set(storageKey, data);
      this.applyDoneMetrics(undefined, data);
      this.trimDoneHistory();
      this.emitMetrics();
      this.queueChanged.next();
      this.doneChanged.next();
      this.updated.next({ id: storageKey, sourceUrl: data.url, location: 'done' });
    });
    socket.fromEvent('canceled').subscribe((strdata: string) => {
      let data: string = JSON.parse(strdata);
      const existing = this.queue.get(data);
      if (existing) {
        this.queue.delete(data);
        this.applyQueueMetrics(existing, undefined);
        this.emitMetrics();
        this.queueChanged.next();
      }
    });
    socket.fromEvent('cleared').subscribe((strdata: string) => {
      let data: string = JSON.parse(strdata);
      const existing = this.done.get(data);
      if (existing) {
        this.done.delete(data);
        this.applyDoneMetrics(existing, undefined);
        this.emitMetrics();
        this.doneChanged.next();
      }
    });
    socket.fromEvent('renamed').subscribe((strdata: string) => {
      const parsed = JSON.parse(strdata);
      const storageKey = parsed.storage_key || parsed.url;
      let existing: Download = this.done.get(storageKey);
      if (!existing) {
        return;
      }
      const updatedEntry = this.normalizeDownload(parsed, existing);
      if (!updatedEntry.filename && updatedEntry.title) {
        updatedEntry.filename = updatedEntry.title;
      }
      this.done.set(storageKey, updatedEntry);
      this.applyDoneMetrics(existing, updatedEntry);
      this.emitMetrics();
      this.doneChanged.next();
    });
    socket.fromEvent('configuration').subscribe((strdata: string) => {
      let data = JSON.parse(strdata);
      console.debug("got configuration:", data);
      this.configuration = data;
      this.updateAdaptiveStreamingFromConfig(data);
      this.configurationChanged.next(data);
      const configuredLimit = data?.MAX_HISTORY_ITEMS;
      if (configuredLimit !== undefined && configuredLimit !== null && configuredLimit !== '') {
        const rawLimit = Number(configuredLimit);
        if (!Number.isNaN(rawLimit)) {
          this.maxHistoryItems = Math.max(0, Math.floor(rawLimit));
          if (this.trimDoneHistory()) {
            this.emitMetrics();
            this.doneChanged.next();
          }
        }
      }
    });
    socket.fromEvent('custom_dirs').subscribe((strdata: string) => {
      let data = JSON.parse(strdata);
      console.debug("got custom_dirs:", data);
      this.customDirs = data;
      this.customDirsChanged.next(data);
    });
    socket.fromEvent('ytdl_options_changed').subscribe((strdata: string) => {
      let data = JSON.parse(strdata);
      this.ytdlOptionsChanged.next(data);
    });
  }

  private normalizeDownload(raw: any, existing?: Download | null): Download {
    const base: Partial<Download> = existing ? { ...existing } : {};
    const draft: any = raw && typeof raw === 'object' ? { ...raw } : {};
    const storageKey = draft.storage_key ?? base.storage_key ?? draft.url ?? base.url ?? draft.id ?? base.id ?? '';

    const pick = (source: any, key: string) =>
      source && Object.prototype.hasOwnProperty.call(source, key) ? source[key] : undefined;

    const resolve = <T>(key: keyof Download, fallback: T): T => {
      const draftValue = pick(draft, key as string);
      if (draftValue !== undefined) {
        return draftValue as T;
      }
      const baseValue = pick(base, key as string);
      if (baseValue !== undefined) {
        return baseValue as T;
      }
      return fallback;
    };

    const normalized: Download = {
      ...base,
      ...draft,
      id: resolve('id', ''),
      title: resolve('title', ''),
      url: resolve('url', ''),
      storage_key: storageKey,
      quality: resolve('quality', ''),
      format: resolve('format', ''),
      folder: resolve('folder', ''),
      custom_name_prefix: resolve('custom_name_prefix', ''),
      playlist_strict_mode: resolve('playlist_strict_mode', false),
      playlist_item_limit: resolve('playlist_item_limit', 0),
      status: resolve('status', 'pending'),
      msg: resolve('msg', ''),
      percent: resolve('percent', 0),
      speed: resolve('speed', 0),
      eta: resolve('eta', 0),
      filename: resolve('filename', ''),
      error: resolve('error', undefined as string | undefined),
      size: resolve('size', undefined as number | undefined),
      checked: resolve('checked', false),
      deleting: resolve('deleting', false),
    };

    const originalUrl = pick(draft, 'original_url');
    const baseOriginalUrl = pick(base, 'original_url');
    if (originalUrl !== undefined || baseOriginalUrl !== undefined) {
      (normalized as any).original_url = originalUrl !== undefined ? originalUrl : baseOriginalUrl;
    }

    return normalized;
  }

  private createEmptyMetrics(): DownloadMetrics {
    return {
      active: 0,
      queued: 0,
      completed: 0,
      failed: 0,
      totalSpeed: 0,
      queueSize: 0,
      doneSize: 0
    };
  }

  private resetMetricsState(): void {
    this.metricsState = this.createEmptyMetrics();
  }

  private emitMetrics(): void {
    this.metricsSubject.next({ ...this.metricsState });
  }

  private applyQueueMetrics(oldEntry?: Download, newEntry?: Download): void {
    if (oldEntry) {
      this.decrementQueueSizeIfRemoved(oldEntry, newEntry);
      this.adjustQueueCounters(oldEntry, -1);
    }
    if (newEntry) {
      this.incrementQueueSizeIfAdded(oldEntry, newEntry);
      this.adjustQueueCounters(newEntry, 1);
    }
  }

  private applyDoneMetrics(oldEntry?: Download, newEntry?: Download): void {
    if (oldEntry) {
      this.decrementDoneSizeIfRemoved(oldEntry, newEntry);
      this.adjustDoneCounters(oldEntry, -1);
    }
    if (newEntry) {
      this.incrementDoneSizeIfAdded(oldEntry, newEntry);
      this.adjustDoneCounters(newEntry, 1);
    }
  }

  private decrementQueueSizeIfRemoved(oldEntry: Download, newEntry?: Download): void {
    if (!newEntry) {
      this.metricsState.queueSize = Math.max(0, this.metricsState.queueSize - 1);
    }
  }

  private incrementQueueSizeIfAdded(oldEntry: Download | undefined, newEntry: Download): void {
    if (!oldEntry) {
      this.metricsState.queueSize += 1;
    }
  }

  private decrementDoneSizeIfRemoved(oldEntry: Download, newEntry?: Download): void {
    if (!newEntry) {
      this.metricsState.doneSize = Math.max(0, this.metricsState.doneSize - 1);
    }
  }

  private incrementDoneSizeIfAdded(oldEntry: Download | undefined, newEntry: Download): void {
    if (!oldEntry) {
      this.metricsState.doneSize += 1;
    }
  }

  private adjustQueueCounters(entry: Download, delta: number): void {
    if (this.isActiveQueueStatus(entry.status)) {
      this.metricsState.active = this.clampNonNegative(this.metricsState.active + delta);
      const speedContribution = entry.status === 'downloading' ? (entry.speed || 0) : 0;
      if (speedContribution !== 0) {
        this.metricsState.totalSpeed += delta * speedContribution;
        if (this.metricsState.totalSpeed < 0) {
          this.metricsState.totalSpeed = 0;
        }
      }
    } else if (entry.status === 'pending') {
      this.metricsState.queued = this.clampNonNegative(this.metricsState.queued + delta);
    }
  }

  private adjustDoneCounters(entry: Download, delta: number): void {
    if (entry.status === 'finished') {
      this.metricsState.completed = this.clampNonNegative(this.metricsState.completed + delta);
    } else if (entry.status === 'error') {
      this.metricsState.failed = this.clampNonNegative(this.metricsState.failed + delta);
    }
  }

  private trimDoneHistory(): boolean {
    const limit = Number.isFinite(this.maxHistoryItems) ? this.maxHistoryItems : 200;
    let changed = false;
    if (limit <= 0) {
      if (this.done.size > 0) {
        for (const entry of this.done.values()) {
          this.applyDoneMetrics(entry, undefined);
        }
        this.done.clear();
        changed = true;
      }
      return changed;
    }

    while (this.done.size > limit) {
      const iterator = this.done.keys().next();
      if (iterator.done) {
        break;
      }
      const key = iterator.value as string;
      const entry = this.done.get(key);
      this.done.delete(key);
      if (entry) {
        this.applyDoneMetrics(entry, undefined);
      }
      changed = true;
    }
    return changed;
  }

  private isActiveQueueStatus(status: string | undefined): boolean {
    return status === 'downloading' || status === 'preparing';
  }

  private clampNonNegative(value: number): number {
    return value < 0 ? 0 : value;
  }

  handleHTTPError(error: HttpErrorResponse) {
    var msg = error.error instanceof ErrorEvent ? error.error.message : error.error;
    return of({status: 'error', msg: msg})
  }

  public buildApiUrl(path: string): string {
    return buildApiUrl(path);
  }

  private updateAdaptiveStreamingFromConfig(config: any): void {
    const availableRaw = config?.STREAM_TRANSCODE_AVAILABLE;
    const statusRaw = config?.STREAM_TRANSCODE_STATUS ?? null;
    const messageRaw = config?.STREAM_TRANSCODE_MESSAGE ?? '';
    const available = availableRaw === undefined ? true : Boolean(availableRaw);
    this.adaptiveStreamingEnabled = available;
    this.adaptiveStreamingStatus = available ? (statusRaw ?? 'available') : (statusRaw ?? 'unavailable');
    this.adaptiveStreamingMessage = available
      ? ''
      : (typeof messageRaw === 'string' && messageRaw.trim().length > 0
        ? messageRaw.trim()
        : 'Adaptive streaming is not available on this server.');
    if (config && typeof config === 'object') {
      config.STREAM_TRANSCODE_AVAILABLE = this.adaptiveStreamingEnabled;
      config.STREAM_TRANSCODE_STATUS = this.adaptiveStreamingStatus;
      config.STREAM_TRANSCODE_MESSAGE = this.adaptiveStreamingMessage;
    }
  }

  public isAdaptiveStreamingEnabled(): boolean {
    return this.adaptiveStreamingEnabled;
  }

  public getAdaptiveStreamingStatus(): string | null {
    return this.adaptiveStreamingStatus;
  }

  public getAdaptiveStreamingMessage(): string {
    return this.adaptiveStreamingMessage;
  }

  public markAdaptiveStreamingUnavailable(message?: string | null): void {
    const normalized = typeof message === 'string' ? message.trim() : '';
    const finalMessage = normalized.length > 0 ? normalized : (this.adaptiveStreamingMessage || 'Adaptive streaming is not available on this server.');
    const status = this.adaptiveStreamingStatus && this.adaptiveStreamingStatus !== 'available' ? this.adaptiveStreamingStatus : 'unavailable';
    if (!this.adaptiveStreamingEnabled && this.adaptiveStreamingMessage === finalMessage) {
      return;
    }
    this.adaptiveStreamingEnabled = false;
    this.adaptiveStreamingStatus = status;
    this.adaptiveStreamingMessage = finalMessage;
    this.configuration = {
      ...this.configuration,
      STREAM_TRANSCODE_AVAILABLE: false,
      STREAM_TRANSCODE_STATUS: status,
      STREAM_TRANSCODE_MESSAGE: finalMessage,
    };
    this.configurationChanged.next(this.configuration);
  }

  public add(url: string, quality: string, format: string, folder: string, customNamePrefix: string, playlistStrictMode: boolean, playlistItemLimit: number, autoStart: boolean, preferredBackend?: 'ytdlp' | 'gallerydl') {
    const payload: any = {
      url: url,
      quality: quality,
      format: format,
      folder: folder,
      custom_name_prefix: customNamePrefix,
      playlist_strict_mode: playlistStrictMode,
      playlist_item_limit: playlistItemLimit,
      auto_start: autoStart
    };
    if (preferredBackend) {
      payload.preferred_backend = preferredBackend;
    }
    return this.http.post<Status>('add', payload).pipe(
      catchError(this.handleHTTPError)
    );
  }

  public proxyProbe(url: string) {
    return this.http.post<ProxyProbeResponse>('proxy/probe', {url}).pipe(
      catchError((error: HttpErrorResponse) => this.handleTypedError<ProxyProbeResponse>(error))
    );
  }

  public proxyAdd(request: ProxyAddRequest) {
    return this.http.post<ProxyAddResponse>('proxy/add', request).pipe(
      catchError((error: HttpErrorResponse) => this.handleTypedError<ProxyAddResponse>(error))
    );
  }

  public seedrStatus() {
    return this.http.get<SeedrStatusResponse>('seedr/status').pipe(
      catchError((error: HttpErrorResponse) => this.handleTypedError<SeedrStatusResponse>(error))
    );
  }

  public seedrDeviceStart() {
    return this.http.post<SeedrDeviceStartResponse>('seedr/device/start', {}).pipe(
      catchError((error: HttpErrorResponse) => this.handleTypedError<SeedrDeviceStartResponse>(error))
    );
  }

  public seedrDeviceComplete(deviceCode?: string | null) {
    const payload = deviceCode ? { device_code: deviceCode } : {};
    return this.http.post<SeedrDeviceCompleteResponse>('seedr/device/complete', payload).pipe(
      catchError((error: HttpErrorResponse) => this.handleTypedError<SeedrDeviceCompleteResponse>(error))
    );
  }

  public seedrLogout() {
    return this.http.post<Status>('seedr/logout', {}).pipe(
      catchError((error: HttpErrorResponse) => this.handleTypedError<Status>(error))
    );
  }

  public seedrClearStorage() {
    return this.http.post<SeedrClearResponse>('seedr/clear', {}).pipe(
      catchError((error: HttpErrorResponse) => this.handleTypedError<SeedrClearResponse>(error))
    );
  }

  public seedrAdd(request: SeedrAddRequest) {
    return this.http.post<SeedrAddResponse>('seedr/add', request).pipe(
      catchError((error: HttpErrorResponse) => this.handleTypedError<SeedrAddResponse>(error))
    );
  }

  public seedrUpload(form: FormData) {
    return this.http.post<SeedrUploadResponse>('seedr/upload', form).pipe(
      catchError((error: HttpErrorResponse) => this.handleTypedError<SeedrUploadResponse>(error))
    );
  }

  public gallerydlAdd(request: GalleryDlAddRequest) {
    return this.http.post<Status>('gallerydl/add', request).pipe(
      catchError(this.handleHTTPError)
    );
  }

  public getGallerydlCredentials() {
    return this.http.get<{status: string; credentials: GalleryDlCredentialSummary[]}>('gallerydl/credentials').pipe(
      catchError((error: HttpErrorResponse) => this.handleTypedError<{status: string; credentials: GalleryDlCredentialSummary[]}>(error))
    );
  }

  public getGallerydlCredential(id: string) {
    return this.http.get<{status: string; credential: GalleryDlCredentialDetail}>('gallerydl/credentials/' + encodeURIComponent(id)).pipe(
      catchError((error: HttpErrorResponse) => this.handleTypedError<{status: string; credential: GalleryDlCredentialDetail}>(error))
    );
  }

  public createGallerydlCredential(payload: GalleryDlCredentialPayload) {
    return this.http.post<{status: string; credential: GalleryDlCredentialSummary}>('gallerydl/credentials', payload).pipe(
      catchError((error: HttpErrorResponse) => this.handleTypedError<{status: string; credential: GalleryDlCredentialSummary}>(error))
    );
  }

  public updateGallerydlCredential(id: string, payload: Partial<GalleryDlCredentialPayload>) {
    return this.http.patch<{status: string; credential: GalleryDlCredentialSummary}>('gallerydl/credentials/' + encodeURIComponent(id), payload).pipe(
      catchError((error: HttpErrorResponse) => this.handleTypedError<{status: string; credential: GalleryDlCredentialSummary}>(error))
    );
  }

  public deleteGallerydlCredential(id: string) {
    return this.http.delete<{status: string}>('gallerydl/credentials/' + encodeURIComponent(id)).pipe(
      catchError((error: HttpErrorResponse) => this.handleTypedError<{status: string}>(error))
    );
  }

  public listGallerydlCookies() {
    return this.http.get<{status: string; cookies: GalleryDlCookieFile[]}>('gallerydl/cookies').pipe(
      catchError((error: HttpErrorResponse) => this.handleTypedError<{status: string; cookies: GalleryDlCookieFile[]}>(error))
    );
  }

  public saveGallerydlCookie(payload: GalleryDlCookiePayload) {
    return this.http.post<{status: string; cookie: GalleryDlCookieFile}>('gallerydl/cookies', payload).pipe(
      catchError((error: HttpErrorResponse) => this.handleTypedError<{status: string; cookie: GalleryDlCookieFile}>(error))
    );
  }

  public getGallerydlCookie(name: string) {
    return this.http.get<{status: string; name: string; content: string}>('gallerydl/cookies/' + encodeURIComponent(name)).pipe(
      catchError((error: HttpErrorResponse) => this.handleTypedError<{status: string; name: string; content: string}>(error))
    );
  }

  public deleteGallerydlCookie(name: string) {
    return this.http.delete<{status: string}>('gallerydl/cookies/' + encodeURIComponent(name)).pipe(
      catchError((error: HttpErrorResponse) => this.handleTypedError<{status: string}>(error))
    );
  }

  public getSupportedSites() {
    return this.http.get<SupportedSitesResponse>('supported-sites').pipe(
      catchError((error: HttpErrorResponse) => this.handleTypedError<SupportedSitesResponse>(error))
    );
  }

  public startById(ids: string[]) {
    return this.http.post('start', {ids: ids});
  }

  public delById(where: 'queue' | 'done', ids: string[]) {
    ids.forEach(id => {
      const entry = (this as any)[where]?.get(id);
      if (entry) {
        entry.deleting = true;
      }
    });

    return this.http.post<any>('delete', {where: where, ids: ids}).pipe(
      tap(result => {
        if (!result || result.status === 'error') {
          ids.forEach(id => {
            const entry = (this as any)[where]?.get(id);
            if (entry) {
              entry.deleting = false;
            }
          });
        }

        if (where !== 'done' || !result) {
          return;
        }

        if (result.status === 'ok') {
          const deleted: string[] = result.deleted || [];
          const missing: string[] = result.missing || [];
          let messageParts: string[] = [];
          if (deleted.length) {
            messageParts.push('Removed from disk:\n' + deleted.map(name => `• ${name}`).join('\n'));
          }
          if (missing.length) {
            messageParts.push('Already missing on disk:\n' + missing.map(name => `• ${name}`).join('\n'));
          }
          if (!messageParts.length) {
            messageParts.push('Selected downloads removed.');
          }
          alert(messageParts.join('\n\n'));
        } else {
          const errors = result.errors ? Object.values(result.errors).join('\n') : (result.msg || 'Unknown error.');
          alert('Unable to remove one or more files:\n' + errors);
        }
      }),
      catchError(error => {
        ids.forEach(id => {
          const entry = (this as any)[where]?.get(id);
          if (entry) {
            entry.deleting = false;
          }
        });
        if (where === 'done') {
          const message = error.error instanceof ErrorEvent ? error.error.message : (error.error || error.message || 'Request failed');
          alert('Unable to remove files:\n' + message);
        }
        return this.handleHTTPError(error);
      })
    );
  }

  public startByFilter(where: 'queue' | 'done', filter: (dl: Download) => boolean) {
    let ids: string[] = [];
    this[where].forEach((dl: Download, key: string) => {
      if (filter(dl)) {
        ids.push(key);
      }
    });
    return this.startById(ids);
  }

  public delByFilter(where: 'queue' | 'done', filter: (dl: Download) => boolean) {
    let ids: string[] = [];
    this[where].forEach((dl: Download, key: string) => {
      if (filter(dl)) {
        ids.push(key);
      }
    });
    return this.delById(where, ids);
  }
  public addDownloadByUrl(url: string): Promise<any> {
    const defaultQuality = 'best';
    const defaultFormat = 'mp4';
    const defaultFolder = ''; 
    const defaultCustomNamePrefix = '';
    const defaultPlaylistStrictMode = false;
    const defaultPlaylistItemLimit = 0;
    const defaultAutoStart = true;
    
    return new Promise((resolve, reject) => {
      this.add(url, defaultQuality, defaultFormat, defaultFolder, defaultCustomNamePrefix, defaultPlaylistStrictMode, defaultPlaylistItemLimit, defaultAutoStart)
        .subscribe(
          response => resolve(response),
          error => reject(error)
        );
    });
  }
  public exportQueueUrls(): string[] {
    return Array.from(this.queue.values()).map(download => download.url);
  }
  
  public rename(id: string, newName: string) {
    return this.http.post<Status>('rename', {id: id, new_name: newName}).pipe(
      catchError(this.handleHTTPError)
    );
  }

  public saveCookieProfile(payload: SaveCookieProfilePayload) {
    const body: any = {};
    if (payload.cookies !== undefined) {
      body.cookies = payload.cookies;
    }
    if (payload.name !== undefined) {
      body.name = payload.name;
    }
    if (payload.hosts !== undefined) {
      body.hosts = payload.hosts;
    }
    if (payload.tags !== undefined) {
      body.tags = payload.tags;
    }
    if (payload.default !== undefined) {
      body.default = payload.default;
    }
    if (payload.profile_id !== undefined) {
      body.profile_id = payload.profile_id;
    }
    return this.http.post<Status & {cookies?: CookieStatusResponse; profile?: YtdlpCookieProfile}>('cookies', body).pipe(
      catchError(this.handleHTTPError)
    );
  }

  public clearCookies(profileId?: string) {
    const options: any = { observe: 'body' as const };
    if (profileId) {
      options.params = { profile_id: profileId };
    }
    return this.http.delete<Status & {cookies?: CookieStatusResponse}>('cookies', options).pipe(
      catchError(this.handleHTTPError)
    );
  }

  public getCookiesStatus() {
    return this.http.get<CookieStatusResponse>('cookies').pipe(
      catchError(() => of({has_cookies: false, state: 'missing'} as CookieStatusResponse))
    );
  }

  public listYtdlpCookieProfiles() {
    return this.http.get<{status?: string; profiles?: YtdlpCookieProfile[]}>('ytdlp/cookies').pipe(
      map(response => response?.profiles ?? []),
      catchError(() => of([] as YtdlpCookieProfile[]))
    );
  }

  public getCurrentUser(forceRefresh = false) {
    if (!forceRefresh && this.currentUserInitialized) {
      return of(this.currentUserCache);
    }

    return this.http.get<CurrentUser>('me').pipe(
      tap(user => {
        this.currentUserCache = user;
        this.currentUserInitialized = true;
      }),
      map(user => user ?? null),
      catchError(() => {
        this.currentUserCache = null;
        this.currentUserInitialized = true;
        return of(null as CurrentUser | null);
      })
    );
  }

  public setCurrentUser(user: CurrentUser | null): void {
    this.currentUserCache = user;
    this.currentUserInitialized = true;
  }

  public listUsers() {
    return this.http.get<{users: ManagedUser[]} & Partial<Status>>('admin/users').pipe(
      catchError((error: HttpErrorResponse) => this.handleTypedError<{users: ManagedUser[]} & Partial<Status>>(error))
    );
  }

  public createUser(username: string, password: string, role: 'admin' | 'user') {
    return this.http.post<ManagedUser>('admin/users', {username, password, role}).pipe(
      catchError(this.handleHTTPError)
    );
  }

  public updateUser(userId: string, payload: Partial<{password: string; role: 'admin' | 'user'; disabled: boolean; username: string;}>) {
    return this.http.patch<ManagedUser>(`admin/users/${userId}`, payload).pipe(
      catchError(this.handleHTTPError)
    );
  }

  public deleteUser(userId: string) {
    return this.http.delete('admin/users/' + userId).pipe(
      catchError(this.handleHTTPError)
    );
  }

  public getProxySettings() {
    return this.http.get<ProxySettingsResponse>('admin/proxy-settings').pipe(
      catchError((error: HttpErrorResponse) => this.handleTypedError<ProxySettingsResponse>(error))
    );
  }

  public updateProxySettings(settings: Partial<ProxySettings>) {
    return this.http.post<ProxySettingsResponse>('admin/proxy-settings', settings).pipe(
      catchError((error: HttpErrorResponse) => this.handleTypedError<ProxySettingsResponse>(error))
    );
  }

  public getSystemStats() {
    return this.http.get<SystemStatsResponse>('admin/system-stats').pipe(
      catchError((error: HttpErrorResponse) => this.handleTypedError<SystemStatsResponse>(error))
    );
  }

  public getResourceLimits() {
    return this.http.get<ResourceLimitsResponse>('admin/resource-limits').pipe(
      catchError((error: HttpErrorResponse) => this.handleTypedError<ResourceLimitsResponse>(error))
    );
  }

  public updateResourceLimits(limits: Partial<ResourceLimits>) {
    return this.http.post<ResourceLimitsResponse>('admin/resource-limits', limits).pipe(
      catchError((error: HttpErrorResponse) => this.handleTypedError<ResourceLimitsResponse>(error))
    );
  }

  public restartSystem() {
    return this.http.post<{status: string; msg?: string}>('admin/restart', {}).pipe(
      catchError((error: HttpErrorResponse) => this.handleTypedError<{status: string; msg?: string}>(error))
    );
  }

  private handleTypedError<T extends Partial<Status>>(error: HttpErrorResponse) {
    const msg = error.error instanceof ErrorEvent ? error.error.message : error.error;
    return of({status: 'error', msg} as T);
  }
  
}
