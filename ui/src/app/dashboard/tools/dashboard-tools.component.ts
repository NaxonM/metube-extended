import { Component, ElementRef, EventEmitter, Input, OnInit, Output, ViewChild } from '@angular/core';
import { Router } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { IconDefinition } from '@fortawesome/fontawesome-svg-core';

import { faLink, faXmark, faDownload, faSliders, faChevronDown, faChevronUp, faCookieBite, faTriangleExclamation, faCircleInfo, faFileImport, faFileExport, faCopy, faKey, faLayerGroup, faTableColumns, faGrip, faCheckCircle, faMagnet, faCloudArrowUp } from '@fortawesome/free-solid-svg-icons';

import { CookieService } from 'ngx-cookie-service';

import { DownloadsService, Status, ProxySuggestion, ProxyProbeResponse, ProxyAddResponse, CookieStatusResponse, GalleryDlPrompt, BackendChoice, YtdlpCookieProfile, SaveCookieProfilePayload, SupportedSitesResponse, CurrentUser, SeedrStatusResponse, SeedrDeviceChallenge, SeedrAccountSummary } from '../../downloads.service';
import { Formats, Format, Quality } from '../../formats';

type PendingAddRequest = {
  url: string;
  quality: string;
  format: string;
  folder: string;
  customNamePrefix: string;
  playlistStrictMode: boolean;
  playlistItemLimit: number;
  autoStart: boolean;
};

@Component({
    selector: 'app-dashboard-tools',
    templateUrl: './dashboard-tools.component.html',
    styleUrls: ['./dashboard-tools.component.sass'],
    standalone: false
})
export class DashboardToolsComponent implements OnInit {
  @Input() isAdmin = false;
  @Output() versionInfoChange = new EventEmitter<{ ytdlp?: string | null; gallerydl?: string | null; metube?: string | null }>();
  @Output() optionsUpdateTimeChange = new EventEmitter<string | null>();
  @Output() userChange = new EventEmitter<CurrentUser | null>();

  faLink = faLink;
  faXmark = faXmark;
  faDownload = faDownload;
  faSliders = faSliders;
  faChevronDown = faChevronDown;
  faChevronUp = faChevronUp;
  faCookieBite = faCookieBite;
  faTriangleExclamation = faTriangleExclamation;
  faCircleInfo = faCircleInfo;
  faFileImport = faFileImport;
  faFileExport = faFileExport;
  faCopy = faCopy;
  faKey = faKey;
  faLayerGroup = faLayerGroup;
  faTableColumns = faTableColumns;
  faGrip = faGrip;
  faCheckCircle = faCheckCircle;
  faMagnet = faMagnet;
  faCloudArrowUp = faCloudArrowUp;

  addUrl = '';
  formats: Format[] = Formats;
  qualities: Quality[];
  quality = 'best';
  format = 'any';
  folder = '';
  customNamePrefix = '';
  autoStart = true;
  playlistStrictMode = true;
  playlistItemLimit: number;
  addInProgress = false;
  batchImportModalOpen = false;
  batchImportText = '';
  batchImportStatus = '';
  importInProgress = false;
  cancelImportFlag = false;
  ytDlpOptionsUpdateTime: string | null = null;
  ytDlpVersion: string | null = null;
  galleryDlVersion: string | null = null;
  metubeVersion: string | null = null;
  isAdvancedOpen = false;

  cookiesModalOpen = false;
  gallerySettingsModalOpen = false;
  cookieStatus: CookieStatusResponse = { has_cookies: false, state: 'missing' };
  cookieMessage = '';
  cookieError = '';
  cookiesWorking = false;
  cookieProfiles: YtdlpCookieProfile[] = [];
  cookieProfilesLoading = false;
  cookieProfilesError = '';
  cookieForm = {
    id: null as string | null,
    name: '',
    hosts: '',
    tags: '',
    cookies: '',
    default: false,
  };
  readonly defaultYoutubeHosts = ['youtube.com', 'youtu.be', 'music.youtube.com'];

  proxyPromptOpen = false;
  proxyPromptData: ProxySuggestion | null = null;
  proxyPromptMessage = '';
  proxyProbeLoading = false;
  proxyProbeError = '';
  proxyProbeResult: ProxyProbeResponse | null = null;
  proxySuggestedTitle: string | null = null;
  proxyOverrideEnabled = false;
  proxyOverrideMb: number | null = null;
  proxyConfirmInProgress = false;

  seedrStatus: SeedrStatusResponse | null = null;
  seedrStatusLoading = false;
  seedrStatusError = '';
  seedrDeviceChallenge: SeedrDeviceChallenge | null = null;
  seedrDeviceStartInProgress = false;
  seedrDeviceCompleteInProgress = false;
  seedrDeviceMessage = '';
  seedrDeviceError = '';
  seedrAccount: SeedrAccountSummary | null = null;
  seedrMagnetText = '';
  seedrFolder = '';
  seedrCustomPrefix = '';
  seedrAutoStart = true;
  seedrSubmitInProgress = false;
  seedrUploadInProgress = false;
  seedrSelectedTorrent: File | null = null;
  seedrActionMessage = '';
  seedrActionError = '';
  seedrPanelOpen = true;

  @ViewChild('seedrTorrentInput') seedrTorrentInput?: ElementRef<HTMLInputElement>;

  galleryPromptOpen = false;
  galleryPromptData: GalleryDlPrompt | null = null;
  galleryPromptMessage = '';
  galleryConfirmInProgress = false;
  galleryRange = '';
  galleryWriteMetadata = false;
  galleryExtraArgs = '';
  galleryAdvancedOpen = false;
  gallerySelectedCredential: string | null = null;
  gallerySelectedCookie: string | null = null;
  galleryProxy = '';
  galleryRetries: number | null = null;
  gallerySleepRequest = '';
  gallerySleep429 = '';
  galleryWriteInfoJson = false;
  galleryWriteTags = false;
  galleryDownloadArchive = false;
  galleryArchiveId = '';
  galleryCredentials: { id: string; name: string; username?: string | null }[] = [];
  galleryCookies: { name: string }[] = [];

  supportedSitesModalOpen = false;
  supportedSitesLoading = false;
  supportedSitesError = '';
  supportedSites: { provider: string; sites: string[] }[] = [];
  activeSupportedProviderIndex = 0;
  supportedSitesFilter = '';

  backendChoiceModalOpen = false;
  backendChoiceData: BackendChoice | null = null;
  backendChoiceSubmitting = false;

  pendingAddRequest: PendingAddRequest | null = null;

  constructor(
    public readonly downloads: DownloadsService,
    private readonly cookieService: CookieService,
    private readonly http: HttpClient,
    private readonly router: Router
  ) {
    this.format = this.cookieService.get('metube_format') || 'any';
    this.setQualities();
    this.quality = this.cookieService.get('metube_quality') || 'best';
    this.autoStart = this.cookieService.get('metube_auto_start') !== 'false';
  }

  ngOnInit(): void {
    this.getConfiguration();
    this.getYtdlOptionsUpdateTime();
    this.refreshCookiesStatus();
    this.fetchVersionInfo();
    this.loadCurrentUser();
    this.refreshSeedrStatus();
  }

  private setQualities(): void {
    const selected = this.formats.find(el => el.id === this.format);
    this.qualities = selected?.qualities ?? [];
    if (!this.qualities.some(el => el.id === this.quality)) {
      this.quality = 'best';
    }
  }

  private applyConfiguration(config: any): void {
    if (!config) {
      return;
    }
    this.playlistStrictMode = config['DEFAULT_OPTION_PLAYLIST_STRICT_MODE'];
    const playlistItemLimit = config['DEFAULT_OPTION_PLAYLIST_ITEM_LIMIT'];
    if (playlistItemLimit !== undefined && playlistItemLimit !== null && playlistItemLimit !== '' && playlistItemLimit !== '0') {
      this.playlistItemLimit = playlistItemLimit;
    }
  }

  private loadCurrentUser(): void {
    this.downloads.getCurrentUser().subscribe(user => {
      this.downloads.setCurrentUser(user);
      this.userChange.emit(user);
    });
  }

  private getConfiguration(): void {
    this.applyConfiguration(this.downloads.configuration);
    this.downloads.configurationChanged.subscribe(config => {
      this.applyConfiguration(config);
    });
  }

  private getYtdlOptionsUpdateTime(): void {
    this.downloads.ytdlOptionsChanged.subscribe(data => {
      if (data['success']) {
        const date = new Date(data['update_time'] * 1000);
        this.ytDlpOptionsUpdateTime = date.toLocaleString();
        this.optionsUpdateTimeChange.emit(this.ytDlpOptionsUpdateTime);
      }
    });
  }

  private fetchVersionInfo(): void {
    const baseUrl = `${window.location.origin}${window.location.pathname.replace(/\/[^\/]*$/, '/')}`;
    const versionUrl = `${baseUrl}version`;
    this.http.get<{ 'yt-dlp': string; 'gallery-dl'?: string | null; version: string }>(versionUrl).subscribe({
      next: data => {
        this.ytDlpVersion = data['yt-dlp'];
        this.galleryDlVersion = data['gallery-dl'] ?? null;
        this.metubeVersion = data.version;
        this.versionInfoChange.emit({
          ytdlp: this.ytDlpVersion,
          gallerydl: this.galleryDlVersion,
          metube: this.metubeVersion
        });
      },
      error: () => {
        this.ytDlpVersion = null;
        this.galleryDlVersion = null;
        this.metubeVersion = null;
        this.versionInfoChange.emit({ ytdlp: null, gallerydl: null, metube: null });
      }
    });
  }

  clearAddUrl(): void {
    if (this.addInProgress || this.downloads.loading) {
      return;
    }
    this.addUrl = '';
  }

  addDownload(url?: string, quality?: string, format?: string, folder?: string, customNamePrefix?: string, playlistStrictMode?: boolean, playlistItemLimit?: number, autoStart?: boolean, preferredBackend?: 'ytdlp' | 'gallerydl'): void {
    url = (url ?? this.addUrl)?.trim();
    if (!url) {
      alert('Please provide a URL to download.');
      return;
    }
    quality = quality ?? this.quality;
    format = format ?? this.format;
    folder = folder ?? this.folder;
    customNamePrefix = customNamePrefix ?? this.customNamePrefix;
    playlistStrictMode = playlistStrictMode ?? this.playlistStrictMode;
    playlistItemLimit = playlistItemLimit ?? this.playlistItemLimit;
    autoStart = autoStart ?? this.autoStart;

    if (this.isYoutubeUrl(url) && !this.areYoutubeCookiesReady()) {
      const wantsToUpdateCookies = confirm('YouTube downloads require valid cookies. Would you like to open the cookies manager now? Click Cancel to continue without cookies.');
      if (wantsToUpdateCookies) {
        this.openCookiesModal();
        return;
      }
    }

    this.addInProgress = true;
    this.pendingAddRequest = {
      url,
      quality,
      format,
      folder,
      customNamePrefix,
      playlistStrictMode,
      playlistItemLimit,
      autoStart
    };

    this.downloads.add(url, quality, format, folder, customNamePrefix, playlistStrictMode, playlistItemLimit, autoStart, preferredBackend).subscribe({
      next: (status: Status) => {
        this.addInProgress = false;
        if (status.status === 'choose-backend' && status.backend_choice) {
          this.openBackendChoiceModal(status.backend_choice);
          return;
        }
        if (status.status === 'gallerydl' && status.gallerydl) {
          this.pendingAddRequest = null;
          this.showGalleryPrompt(status.gallerydl);
          return;
        }
        if (status.status === 'unsupported') {
          this.pendingAddRequest = null;
          this.showProxyPrompt(status);
          return;
        }
        if (status.status === 'error') {
          this.pendingAddRequest = null;
          alert(`Error adding URL: ${status.msg}`);
        } else {
          this.pendingAddRequest = null;
          if (status.status === 'ok') {
            this.addUrl = '';
          }
        }
      },
      error: error => {
        this.addInProgress = false;
        this.pendingAddRequest = null;
        const message = error?.error && typeof error.error === 'string' ? error.error : 'Unable to add download.';
        alert(message);
      }
    });
  }

  qualityChanged(): void {
    this.cookieService.set('metube_quality', this.quality, { expires: 3650 });
  }

  formatChanged(): void {
    this.cookieService.set('metube_format', this.format, { expires: 3650 });
    this.setQualities();
  }

  autoStartChanged(): void {
    this.cookieService.set('metube_auto_start', this.autoStart ? 'true' : 'false', { expires: 3650 });
  }

  toggleAdvanced(): void {
    this.isAdvancedOpen = !this.isAdvancedOpen;
  }

  isNumber(event: KeyboardEvent): void {
    const charCode = event.which ? event.which : event.keyCode;
    if (charCode > 31 && (charCode < 48 || charCode > 57)) {
      event.preventDefault();
    }
  }

  openBatchImportModal(): void {
    this.batchImportModalOpen = true;
    this.batchImportText = '';
    this.batchImportStatus = '';
    this.importInProgress = false;
    this.cancelImportFlag = false;
  }

  closeBatchImportModal(): void {
    this.batchImportModalOpen = false;
  }

  startBatchImport(): void {
    const urls = this.batchImportText
      .split(/\r?\n/)
      .map(value => value.trim())
      .filter(value => value.length > 0);
    if (!urls.length) {
      alert('No valid URLs found.');
      return;
    }

    this.importInProgress = true;
    this.cancelImportFlag = false;
    this.batchImportStatus = `Starting to import ${urls.length} URLs...`;

    let index = 0;
    const delayBetween = 1000;
    const processNext = () => {
      if (this.cancelImportFlag) {
        this.batchImportStatus = `Import cancelled after ${index} of ${urls.length} URLs.`;
        this.importInProgress = false;
        return;
      }
      if (index >= urls.length) {
        this.batchImportStatus = `Finished importing ${urls.length} URLs.`;
        this.importInProgress = false;
        return;
      }

      const url = urls[index];
      this.batchImportStatus = `Importing URL ${index + 1} of ${urls.length}: ${url}`;

      const attemptAdd = (backend?: 'ytdlp' | 'gallerydl') => {
        this.downloads.add(url, this.quality, this.format, this.folder, this.customNamePrefix, this.playlistStrictMode, this.playlistItemLimit, this.autoStart, backend).subscribe({
          next: (status: Status) => {
            if (status.status === 'choose-backend' && !backend && status.backend_choice) {
              attemptAdd('ytdlp');
              return;
            }
            if (status.status === 'gallerydl' && status.gallerydl) {
              alert(`Gallery-dl configuration is required for ${url}. Skipping this URL in batch mode.`);
              index++;
              setTimeout(processNext, delayBetween);
              return;
            }
            if (status.status === 'unsupported') {
              alert(`URL ${url} is not supported.`);
            } else if (status.status === 'error') {
              alert(`Error adding URL ${url}: ${status.msg}`);
            }
            if (status.status === 'ok') {
              this.batchImportStatus = `Queued URL ${index + 1} of ${urls.length}: ${url}`;
            }
            index++;
            setTimeout(processNext, delayBetween);
          },
          error: err => {
            console.error(`Error importing URL ${url}:`, err);
            index++;
            setTimeout(processNext, delayBetween);
          }
        });
      };

      attemptAdd();
    };

    processNext();
  }

  cancelBatchImport(): void {
    if (this.importInProgress) {
      this.cancelImportFlag = true;
      this.batchImportStatus += ' Cancelling...';
    }
  }

  exportBatchUrls(filter: 'pending' | 'completed' | 'failed' | 'all'): void {
    let urls: string[];
    if (filter === 'pending') {
      urls = Array.from(this.downloads.queue.values()).map(dl => dl.url);
    } else if (filter === 'completed') {
      urls = Array.from(this.downloads.done.values()).filter(dl => dl.status === 'finished').map(dl => dl.url);
    } else if (filter === 'failed') {
      urls = Array.from(this.downloads.done.values()).filter(dl => dl.status === 'error').map(dl => dl.url);
    } else {
      urls = [
        ...Array.from(this.downloads.queue.values()).map(dl => dl.url),
        ...Array.from(this.downloads.done.values()).map(dl => dl.url)
      ];
    }

    if (!urls.length) {
      alert('No URLs found for the selected filter.');
      return;
    }

    const content = urls.join('\n');
    const blob = new Blob([content], { type: 'text/plain' });
    const downloadUrl = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = downloadUrl;
    a.download = 'metube_urls.txt';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(downloadUrl);
  }

  copyBatchUrls(filter: 'pending' | 'completed' | 'failed' | 'all'): void {
    let urls: string[];
    if (filter === 'pending') {
      urls = Array.from(this.downloads.queue.values()).map(dl => dl.url);
    } else if (filter === 'completed') {
      urls = Array.from(this.downloads.done.values()).filter(dl => dl.status === 'finished').map(dl => dl.url);
    } else if (filter === 'failed') {
      urls = Array.from(this.downloads.done.values()).filter(dl => dl.status === 'error').map(dl => dl.url);
    } else {
      urls = [
        ...Array.from(this.downloads.queue.values()).map(dl => dl.url),
        ...Array.from(this.downloads.done.values()).map(dl => dl.url)
      ];
    }

    if (!urls.length) {
      alert('No URLs found for the selected filter.');
      return;
    }

    const content = urls.join('\n');
    navigator.clipboard.writeText(content)
      .then(() => alert('URLs copied to clipboard.'))
      .catch(() => alert('Failed to copy URLs.'));
  }

  openCookiesModal(): void {
    this.cookiesModalOpen = true;
    this.cookieMessage = '';
    this.cookieError = '';
    this.cookiesWorking = false;
    this.resetCookieForm(null);
    this.refreshCookiesStatus();
    this.loadCookieProfiles(true);
  }

  openGallerySettingsModal(): void {
    this.gallerySettingsModalOpen = true;
  }

  navigateToAdmin(): void {
    this.router.navigate(['/admin']);
  }

  closeCookiesModal(): void {
    this.cookiesModalOpen = false;
    this.cookiesWorking = false;
    this.cookieMessage = '';
    this.cookieError = '';
    this.cookieProfilesError = '';
  }

  closeGallerySettingsModal(): void {
    this.gallerySettingsModalOpen = false;
  }

  refreshCookiesStatus(): void {
    this.downloads.getCookiesStatus().subscribe(data => {
      this.cookieStatus = this.normalizeCookieStatus(data);
    });
  }

  refreshSeedrStatus(): void {
    this.seedrStatusLoading = true;
    this.seedrStatusError = '';
    this.downloads.seedrStatus().subscribe(response => {
      this.seedrStatusLoading = false;
      this.seedrStatus = response;
      this.seedrDeviceChallenge = response.device_challenge ?? null;
      this.seedrAccount = response.account ?? null;
      this.seedrActionMessage = '';
      this.seedrActionError = '';
      if (!response?.connected) {
        this.seedrPanelOpen = true;
      }
    }, error => {
      this.seedrStatusLoading = false;
      this.seedrStatusError = this.resolveError(error, 'Unable to load Seedr status.');
    });
  }

  startSeedrDeviceFlow(): void {
    if (this.seedrDeviceStartInProgress) {
      return;
    }
    this.seedrDeviceStartInProgress = true;
    this.seedrDeviceError = '';
    this.seedrDeviceMessage = '';
    this.downloads.seedrDeviceStart().subscribe(response => {
      this.seedrDeviceStartInProgress = false;
      if (response?.status === 'error') {
        this.seedrDeviceError = response.msg || 'Unable to start Seedr device authorization.';
        return;
      }
      this.seedrDeviceChallenge = response?.challenge ?? null;
      if (!this.seedrDeviceChallenge) {
        this.seedrDeviceError = 'Seedr did not return a device code. Please try again.';
      } else {
        this.seedrDeviceMessage = 'Enter the code below at Seedr to authorize this device.';
      }
    }, error => {
      this.seedrDeviceStartInProgress = false;
      this.seedrDeviceError = this.resolveError(error, 'Unable to start Seedr device authorization.');
    });
  }

  completeSeedrDeviceFlow(deviceCode?: string | null): void {
    if (this.seedrDeviceCompleteInProgress) {
      return;
    }
    const code = deviceCode || this.seedrDeviceChallenge?.device_code || null;
    this.seedrDeviceCompleteInProgress = true;
    this.seedrDeviceError = '';
    this.seedrDeviceMessage = '';
    this.downloads.seedrDeviceComplete(code).subscribe(response => {
      this.seedrDeviceCompleteInProgress = false;
      if (!response || response.status === 'error') {
        this.seedrDeviceError = response?.msg || 'Seedr has not authorized this device yet. Try again after approving the code.';
        return;
      }
      this.seedrDeviceMessage = 'Seedr account connected successfully.';
      this.seedrDeviceChallenge = null;
      this.refreshSeedrStatus();
    }, error => {
      this.seedrDeviceCompleteInProgress = false;
      this.seedrDeviceError = this.resolveError(error, 'Unable to finalize Seedr authorization.');
    });
  }

  disconnectSeedr(): void {
    this.downloads.seedrLogout().subscribe(response => {
      if (response?.status === 'error') {
        this.seedrActionError = response.msg || 'Unable to disconnect Seedr right now.';
        return;
      }
      this.seedrStatus = null;
      this.seedrAccount = null;
      this.seedrDeviceChallenge = null;
      this.seedrActionMessage = 'Seedr account disconnected.';
      this.seedrPanelOpen = true;
      this.refreshSeedrStatus();
    }, error => {
      this.seedrActionError = this.resolveError(error, 'Failed to disconnect Seedr.');
    });
  }

  submitSeedrMagnets(): void {
    const text = (this.seedrMagnetText || '').trim();
    if (!text) {
      this.seedrActionError = 'Enter at least one magnet link.';
      return;
    }
    this.seedrSubmitInProgress = true;
    this.seedrActionMessage = '';
    this.seedrActionError = '';
    const request = {
      magnet_text: text,
      folder: this.seedrFolder,
      custom_name_prefix: this.seedrCustomPrefix,
      auto_start: this.seedrAutoStart,
    } as any;
    this.downloads.seedrAdd(request).subscribe(response => {
      this.seedrSubmitInProgress = false;
      if (!response || response.status === 'error') {
        this.seedrActionError = response?.msg || 'Failed to queue Seedr magnets.';
        return;
      }
      const count = (response.count ?? (response.results?.length ?? (response.id ? 1 : 0))) || 0;
      this.seedrActionMessage = count > 1 ? `Queued ${count} magnet links in Seedr.` : 'Magnet link queued in Seedr.';
      this.seedrMagnetText = '';
    }, error => {
      this.seedrSubmitInProgress = false;
      this.seedrActionError = this.resolveError(error, 'Unable to queue Seedr magnets.');
    });
  }

  onSeedrTorrentSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (!input?.files?.length) {
      this.seedrSelectedTorrent = null;
      return;
    }
    this.seedrSelectedTorrent = input.files[0];
  }

  uploadSeedrTorrent(): void {
    if (!this.seedrSelectedTorrent || this.seedrUploadInProgress) {
      return;
    }
    const file = this.seedrSelectedTorrent;
    const form = new FormData();
    form.append('file', file, file.name);
    form.append('folder', this.seedrFolder || '');
    form.append('custom_name_prefix', this.seedrCustomPrefix || '');
    form.append('auto_start', this.seedrAutoStart ? 'true' : 'false');
    this.seedrUploadInProgress = true;
    this.seedrActionError = '';
    this.seedrActionMessage = '';
    this.downloads.seedrUpload(form).subscribe(response => {
      this.seedrUploadInProgress = false;
      if (!response || response.status === 'error') {
        this.seedrActionError = response?.msg || 'Failed to upload torrent to Seedr.';
        return;
      }
      this.seedrActionMessage = 'Torrent queued in Seedr.';
      this.seedrSelectedTorrent = null;
      if (this.seedrTorrentInput?.nativeElement) {
        this.seedrTorrentInput.nativeElement.value = '';
      }
    }, error => {
      this.seedrUploadInProgress = false;
      this.seedrActionError = this.resolveError(error, 'Unable to upload torrent to Seedr.');
    });
  }

  get seedrIsConnected(): boolean {
    return !!this.seedrStatus?.connected;
  }

  get seedrChallengeExpiresIn(): number | null {
    if (!this.seedrDeviceChallenge?.expires_at) {
      return null;
    }
    const remaining = Math.max(0, Math.floor(this.seedrDeviceChallenge.expires_at - Date.now() / 1000));
    return remaining;
  }

  get seedrChallengeExpireLabel(): string | null {
    const remaining = this.seedrChallengeExpiresIn;
    if (remaining === null) {
      return null;
    }
    const minutes = Math.floor(remaining / 60);
    const seconds = remaining % 60;
    if (minutes <= 0 && seconds <= 0) {
      return 'Expired';
    }
    if (minutes <= 0) {
      return `${seconds}s remaining`;
    }
    return `${minutes}m ${seconds.toString().padStart(2, '0')}s remaining`;
  }

  get seedrStorageUsagePercent(): number | null {
    if (!this.seedrAccount) {
      return null;
    }
    const used = Number(this.seedrAccount.space_used || 0);
    const max = Number(this.seedrAccount.space_max || 0);
    if (!max || isNaN(used) || isNaN(max) || max <= 0) {
      return null;
    }
    return Math.min(100, Math.max(0, (used / max) * 100));
  }

  get seedrConnectionStatus(): 'connected' | 'disconnected' {
    return this.seedrIsConnected ? 'connected' : 'disconnected';
  }

  toggleSeedrPanel(): void {
    this.seedrPanelOpen = !this.seedrPanelOpen;
  }

  private resolveError(error: any, fallback: string): string {
    if (!error) {
      return fallback;
    }
    if (typeof error === 'string') {
      return error;
    }
    if (error.error) {
      if (typeof error.error === 'string') {
        return error.error;
      }
      if (typeof error.error?.msg === 'string') {
        return error.error.msg;
      }
    }
    if (typeof error.message === 'string') {
      return error.message;
    }
    return fallback;
  }

  private loadCookieProfiles(selectDefault = false, focusProfileId?: string | null): void {
    this.cookieProfilesLoading = true;
    this.cookieProfilesError = '';
    this.downloads.listYtdlpCookieProfiles().subscribe(profiles => {
      this.cookieProfiles = profiles;
      this.cookieProfilesLoading = false;
      if (focusProfileId) {
        const focused = profiles.find(profile => profile.id === focusProfileId);
        if (focused) {
          this.resetCookieForm(focused);
          return;
        }
      }
      if (selectDefault) {
        const preferred = profiles.find(profile => profile.default) || profiles[0];
        if (preferred) {
          this.resetCookieForm(preferred);
        }
      }
    }, error => {
      console.error('Unable to load cookie profiles', error);
      this.cookieProfilesLoading = false;
      this.cookieProfilesError = 'Unable to load cookie profiles. Please try again later.';
    });
  }

  private resetCookieForm(profile: YtdlpCookieProfile | null): void {
    if (profile) {
      this.cookieForm = {
        id: profile.id,
        name: profile.name,
        hosts: (profile.hosts || []).join(', '),
        tags: (profile.tags || []).join(', '),
        cookies: '',
        default: !!profile.default,
      };
    } else {
      this.cookieForm = {
        id: null,
        name: '',
        hosts: '',
        tags: '',
        cookies: '',
        default: this.cookieProfiles.length === 0,
      };
    }
  }

  startNewCookieProfile(): void {
    this.resetCookieForm(null);
    this.cookieMessage = '';
    this.cookieError = '';
  }

  editCookieProfile(profile: YtdlpCookieProfile): void {
    this.resetCookieForm(profile);
    this.cookieMessage = '';
    this.cookieError = '';
  }

  private parseCsvList(input: string): string[] {
    return input.split(',').map(value => value.trim()).filter(value => value.length > 0);
  }

  async handleCookieSmartAction(): Promise<void> {
    if (this.cookiesWorking) {
      return;
    }

    this.cookieError = '';

    const clipboardText = await this.readClipboardText();
    if (this.looksLikeCookies(clipboardText)) {
      this.cookieForm.cookies = clipboardText?.trim() || '';
      this.cookieMessage = 'Copied cookies from clipboard.';
      return;
    }

    if (clipboardText) {
      this.cookieError = 'Clipboard does not appear to contain Netscape-format cookies.';
    } else {
      this.cookieError = 'Unable to read cookies from clipboard. Paste them manually instead.';
    }
  }

  prefillYoutubeProfile(): void {
    this.cookieForm = {
      id: null,
      name: 'YouTube',
      hosts: this.defaultYoutubeHosts.join(', '),
      tags: 'youtube',
      cookies: '',
      default: !this.cookieProfiles.some(profile => profile.default),
    };
    this.cookieMessage = '';
    this.cookieError = '';
  }

  saveCookieProfile(): void {
    const form = this.cookieForm;
    const name = form.name.trim();
    if (!name) {
      alert('Please provide a profile name.');
      return;
    }

    const hosts = this.parseCsvList(form.hosts);
    const tags = this.parseCsvList(form.tags).map(tag => tag.toLowerCase());
    const body: SaveCookieProfilePayload = {
      profile_id: form.id ?? undefined,
      name,
      hosts,
      tags,
      default: form.default,
    };

    const trimmedCookies = form.cookies.trim();
    if (trimmedCookies) {
      body.cookies = trimmedCookies;
    } else if (!form.id) {
      alert('Please paste cookie data for a new profile.');
      return;
    } else {
      body.cookies = null;
    }

    this.cookiesWorking = true;
    this.cookieMessage = '';
    this.cookieError = '';

    this.downloads.saveCookieProfile(body).subscribe(status => {
      this.cookiesWorking = false;
      if (!status || typeof (status as any).status !== 'string') {
        console.warn('Unexpected response when saving cookie profile', status);
        return;
      }
      const payload = status as Status & { cookies?: CookieStatusResponse; profile?: YtdlpCookieProfile };
      if (payload.status === 'error') {
        alert(payload.msg || 'Unable to save cookie profile.');
        return;
      }
      if (payload.cookies) {
        this.cookieStatus = this.normalizeCookieStatus(payload.cookies);
      }
      const wasUpdate = !!form.id;
      const savedProfile = payload.profile || null;
      this.cookieMessage = wasUpdate ? 'Cookie profile updated.' : 'Cookie profile created.';
      if (savedProfile) {
        this.resetCookieForm(savedProfile);
      } else {
        this.resetCookieForm(null);
      }
      this.refreshCookiesStatus();
      const focusId = savedProfile?.id ?? form.id ?? null;
      this.loadCookieProfiles(!focusId, focusId);
    }, error => {
      this.cookiesWorking = false;
      console.error('Failed to save cookie profile', error);
      alert('Failed to save cookie profile.');
    });
  }

  deleteCookieProfile(profile: YtdlpCookieProfile): void {
    if (!confirm(`Remove cookie profile "${profile.name}"?`)) {
      return;
    }

    this.cookiesWorking = true;
    this.cookieMessage = '';
    this.cookieError = '';

    this.downloads.clearCookies(profile.id).subscribe(status => {
      this.cookiesWorking = false;
      if (!status || typeof (status as any).status !== 'string') {
        console.warn('Unexpected response when deleting cookie profile', status);
        return;
      }
      const payload = status as Status & { cookies?: CookieStatusResponse };
      if (payload.status === 'error') {
        alert(payload.msg || 'Unable to remove cookie profile.');
        return;
      }
      if (payload.cookies) {
        this.cookieStatus = this.normalizeCookieStatus(payload.cookies);
      }
      this.cookieMessage = 'Cookie profile removed.';
      this.resetCookieForm(null);
      this.refreshCookiesStatus();
      this.loadCookieProfiles(true);
    }, error => {
      this.cookiesWorking = false;
      console.error('Failed to delete cookie profile', error);
      alert('Failed to remove cookie profile.');
    });
  }

  makeCookieProfileDefault(profile: YtdlpCookieProfile): void {
    if (profile.default) {
      return;
    }

    this.cookiesWorking = true;
    this.cookieMessage = '';
    this.cookieError = '';

    this.downloads.saveCookieProfile({
      profile_id: profile.id,
      name: profile.name,
      hosts: profile.hosts || [],
      tags: profile.tags || [],
      default: true,
      cookies: null,
    }).subscribe(status => {
      this.cookiesWorking = false;
      if (!status || typeof (status as any).status !== 'string') {
        console.warn('Unexpected response when updating default profile', status);
        return;
      }
      const payload = status as Status & { cookies?: CookieStatusResponse };
      if (payload.status === 'error') {
        alert(payload.msg || 'Unable to set default profile.');
        return;
      }
      if (payload.cookies) {
        this.cookieStatus = this.normalizeCookieStatus(payload.cookies);
      }
      this.cookieMessage = 'Default profile updated.';
      this.refreshCookiesStatus();
      this.loadCookieProfiles(true, profile.id);
    }, error => {
      this.cookiesWorking = false;
      console.error('Failed to set default cookie profile', error);
      alert('Failed to set profile as default.');
    });
  }

  get cookieStatusSummary(): string {
    if (this.cookieMessage) {
      return this.cookieMessage;
    }
    if (this.cookieError) {
      return this.cookieError;
    }
    const status = this.cookieStatus;
    if (!status || !status.has_cookies) {
      return 'No cookies are configured.';
    }
    switch (status.state) {
      case 'valid':
        return `Cookies were last confirmed working on ${this.formatCookieTimestamp(status.checked_at)}.`;
      case 'invalid': {
        const reason = status.message || 'The saved cookies appear to be invalid or expired.';
        return `${reason}${status.checked_at ? ` (Last checked ${this.formatCookieTimestamp(status.checked_at)}.)` : ''}`;
      }
      case 'unknown':
      default:
        return 'Cookies are saved but have not been verified yet. Paste a fresh set if downloads fail.';
    }
  }

  get cookieStatusTooltip(): string {
    const status = this.cookieStatus;
    if (!status || !status.has_cookies) {
      return 'No YouTube cookies are configured. Click to add them now.';
    }
    switch (status.state) {
      case 'valid':
        return `YouTube cookies look good (last checked ${this.formatCookieTimestamp(status.checked_at)}). Click to manage.`;
      case 'invalid': {
        const reason = status.message || 'The saved cookies appear to be invalid or expired.';
        return `${reason} Click to update cookies.`;
      }
      case 'unknown':
      default:
        return 'Cookies are saved but have not been verified yet. Click to replace or remove them.';
    }
  }

  get cookieStatusIcon(): IconDefinition {
    const state = this.cookieStatus?.state;
    if (state === 'valid') {
      return this.faCheckCircle;
    }
    if (state === 'invalid') {
      return this.faTriangleExclamation;
    }
    return this.faCookieBite;
  }

  get cookieStatusVariantClass(): string {
    const state = this.cookieStatus?.state;
    if (!this.cookieStatus?.has_cookies) {
      return 'text-warning opacity-75';
    }
    switch (state) {
      case 'valid':
        return 'text-success';
      case 'invalid':
        return 'text-danger';
      default:
        return 'text-warning';
    }
  }

  get shouldShowCookieIndicator(): boolean {
    return this.isYoutubeUrl(this.addUrl);
  }

  private async readClipboardText(): Promise<string | null> {
    if (typeof navigator === 'undefined' || !navigator.clipboard || !navigator.clipboard.readText) {
      return null;
    }
    try {
      return await navigator.clipboard.readText();
    } catch (error) {
      console.warn('Unable to read clipboard:', error);
      if (!this.cookieError) {
        this.cookieError = 'Unable to access clipboard. Paste your cookies manually.';
      }
      return null;
    }
  }

  private looksLikeCookies(text: string | null | undefined): boolean {
    if (!text) {
      return false;
    }
    const trimmed = text.trim();
    if (!trimmed) {
      return false;
    }
    const lines = trimmed.split(/\r?\n/).filter(line => !!line && !line.startsWith('#'));
    if (!lines.length) {
      return trimmed.includes('youtube.com');
    }
    return lines.some(line => line.split('\t').length >= 7 || line.includes('youtube.com'));
  }

  private normalizeCookieStatus(data?: CookieStatusResponse | null): CookieStatusResponse {
    if (!data) {
      return { has_cookies: false, state: 'missing' };
    }
    const hasCookies = !!data.has_cookies;
    const state = data.state ?? (hasCookies ? 'unknown' : 'missing');
    const checkedAt = typeof data.checked_at === 'number' ? data.checked_at : undefined;
    const message = data.message ?? (state === 'invalid' ? 'The saved cookies appear to be invalid or expired.' : undefined);
    return {
      has_cookies: hasCookies,
      state,
      message,
      checked_at: checkedAt,
      profile_count: typeof data.profile_count === 'number' ? data.profile_count : undefined,
      default_profile_id: typeof data.default_profile_id === 'string' ? data.default_profile_id : undefined,
    };
  }

  private formatCookieTimestamp(timestamp?: number): string {
    if (!timestamp || Number.isNaN(timestamp)) {
      return 'recently';
    }
    try {
      const millis = timestamp > 1e12 ? timestamp : timestamp * 1000;
      return new Date(millis).toLocaleString();
    } catch {
      return 'recently';
    }
  }

  private isYoutubeUrl(url?: string | null): boolean {
    if (!url) {
      return false;
    }
    const trimmed = url.trim();
    if (!trimmed) {
      return false;
    }
    try {
      const parsed = trimmed.startsWith('http') ? new URL(trimmed) : new URL(`https://${trimmed}`);
      const hostname = parsed.hostname.toLowerCase();
      return hostname === 'youtu.be' || hostname.endsWith('.youtu.be') || hostname.endsWith('youtube.com');
    } catch {
      return /^(https?:\/\/)?(www\.|m\.)?(youtube\.com|youtu\.be)/i.test(trimmed);
    }
  }

  private areYoutubeCookiesReady(): boolean {
    const status = this.cookieStatus;
    if (!status || !status.has_cookies) {
      return false;
    }
    if (status.state === 'invalid' || status.state === 'missing') {
      return false;
    }
    return true;
  }

  private showProxyPrompt(status: Status): void {
    if (!status.proxy) {
      alert(status.msg || 'This URL is not supported by yt-dlp.');
      return;
    }

    this.proxyPromptData = { ...status.proxy };
    this.proxyPromptMessage = status.msg || 'This URL is not supported by yt-dlp. Do you want to download it directly through the server?';
    this.proxyProbeResult = null;
    this.proxyProbeError = '';
    this.proxySuggestedTitle = null;
    this.proxyOverrideEnabled = false;
    this.proxyOverrideMb = status.proxy.limit_enabled ? status.proxy.size_limit_mb : null;
    this.proxyConfirmInProgress = false;
    this.proxyPromptOpen = true;
    this.proxyProbeLoading = true;

    this.downloads.proxyProbe(status.proxy.url).subscribe(result => {
      this.proxyProbeLoading = false;
      if (result.status === 'error') {
        this.proxyProbeError = result.msg || 'Unable to inspect the remote file. You can still proceed, but size checks may not be available.';
        this.proxySuggestedTitle = this.extractFileName(status.proxy.url);
        return;
      }

      this.proxyProbeResult = result;
      this.proxySuggestedTitle = result.filename || this.extractFileName(status.proxy.url);
      if (result.limit_exceeded && status.proxy.limit_enabled) {
        const sizeMb = result.size ? Math.ceil(result.size / (1024 * 1024)) : status.proxy.size_limit_mb;
        this.proxyOverrideMb = sizeMb;
        this.proxyOverrideEnabled = false;
      }
    }, () => {
      this.proxyProbeLoading = false;
      this.proxyProbeError = 'Unable to inspect the remote file. You can still proceed, but size checks may not be available.';
      this.proxySuggestedTitle = this.extractFileName(status.proxy.url);
    });
  }

  closeProxyPrompt(): void {
    this.proxyPromptOpen = false;
    this.proxyPromptData = null;
    this.proxyProbeResult = null;
    this.proxyProbeError = '';
    this.proxySuggestedTitle = null;
    this.proxyConfirmInProgress = false;
  }

  confirmProxyDownload(): void {
    if (!this.proxyPromptData || this.proxyConfirmInProgress) {
      return;
    }

    const overrideMb = this.proxyOverrideEnabled ? Math.max(Number(this.proxyOverrideMb ?? 0), 0) : null;
    const payload = {
      url: this.proxyPromptData.url,
      title: this.proxySuggestedTitle || this.extractFileName(this.proxyPromptData.url),
      folder: this.proxyPromptData.folder || '',
      custom_name_prefix: this.proxyPromptData.custom_name_prefix || '',
      auto_start: this.proxyPromptData.auto_start,
      size_limit_mb: overrideMb
    };

    this.proxyConfirmInProgress = true;
    this.downloads.proxyAdd(payload).subscribe(result => {
      this.proxyConfirmInProgress = false;
      if (result.status === 'error') {
        this.proxyProbeError = result.msg || 'Unable to start the proxy download.';
        return;
      }
      this.closeProxyPrompt();
      this.addUrl = '';
    }, error => {
      this.proxyConfirmInProgress = false;
      this.proxyProbeError = (error?.error && typeof error.error === 'string') ? error.error : 'Unable to start the proxy download.';
    });
  }

  get proxyDownloadDisabled(): boolean {
    if (!this.proxyPromptData || this.proxyProbeLoading || this.proxyConfirmInProgress) {
      return true;
    }
    if (!this.proxyPromptData.limit_enabled) {
      return false;
    }
    if (!this.proxyProbeResult) {
      return false;
    }
    if (this.proxyProbeResult.status !== 'ok') {
      return false;
    }
    return !!this.proxyProbeResult.limit_exceeded && !this.proxyOverrideEnabled;
  }

  formatBytes(value?: number | null): string {
    if (value === undefined || value === null || isNaN(value)) {
      return 'Unknown';
    }
    if (value === 0) {
      return '0 B';
    }
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let size = value;
    let index = 0;
    while (size >= 1024 && index < units.length - 1) {
      size /= 1024;
      index++;
    }
    const precision = size >= 10 || index === 0 ? 0 : 1;
    return `${size.toFixed(precision)} ${units[index]}`;
  }

  private extractFileName(url: string): string {
    try {
      const parsed = new URL(url);
      const segments = parsed.pathname.split('/').filter(Boolean);
      if (segments.length) {
        return decodeURIComponent(segments[segments.length - 1]);
      }
    } catch (e) {
      const parts = url.split('/');
      if (parts.length) {
        return parts[parts.length - 1];
      }
    }
    return url;
  }

  private showGalleryPrompt(data: GalleryDlPrompt): void {
    this.galleryPromptData = {
      ...data,
      options: Array.isArray(data.options) ? [...data.options] : []
    };
    this.galleryPromptMessage = '';
    this.galleryConfirmInProgress = false;
    this.resetGalleryOptions(this.galleryPromptData);
    this.galleryPromptOpen = true;
  }

  closeGalleryPrompt(): void {
    this.galleryPromptOpen = false;
    this.galleryPromptData = null;
    this.galleryPromptMessage = '';
    this.galleryConfirmInProgress = false;
    this.galleryRange = '';
    this.galleryWriteMetadata = false;
    this.galleryExtraArgs = '';
    this.galleryAdvancedOpen = false;
    this.gallerySelectedCredential = null;
    this.gallerySelectedCookie = null;
    this.galleryProxy = '';
    this.galleryRetries = null;
    this.gallerySleepRequest = '';
    this.gallerySleep429 = '';
    this.galleryWriteInfoJson = false;
    this.galleryWriteTags = false;
    this.galleryDownloadArchive = false;
    this.galleryArchiveId = '';
  }

  confirmGalleryDownload(): void {
    if (!this.galleryPromptData || this.galleryConfirmInProgress) {
      return;
    }

    const options = this.buildGalleryOptions();
    const proxy = this.galleryProxy.trim();
    const retriesRaw = this.galleryRetries;
    let retries: number | null = null;
    if (retriesRaw !== null && retriesRaw !== undefined) {
      const parsed = Number(retriesRaw);
      if (!isNaN(parsed) && parsed >= 0) {
        retries = Math.min(Math.floor(parsed), 20);
      }
    }
    const sleepRequest = this.gallerySleepRequest.trim();
    const sleep429 = this.gallerySleep429.trim();
    const archiveId = this.galleryArchiveId.trim();

    const payload = {
      url: this.galleryPromptData.url,
      title: this.galleryPromptData.title || this.extractFileName(this.galleryPromptData.url),
      auto_start: this.galleryPromptData.auto_start !== false,
      options,
      credential_id: this.gallerySelectedCredential || null,
      cookie_name: this.gallerySelectedCookie || null,
      proxy: proxy || null,
      retries,
      sleep_request: sleepRequest || null,
      sleep_429: sleep429 || null,
      write_metadata: this.galleryWriteMetadata,
      write_info_json: this.galleryWriteInfoJson,
      write_tags: this.galleryWriteTags,
      download_archive: this.galleryDownloadArchive,
      archive_id: this.galleryDownloadArchive ? (archiveId || null) : null
    };

    this.galleryConfirmInProgress = true;
    this.downloads.gallerydlAdd(payload).subscribe(result => {
      this.galleryConfirmInProgress = false;
      if (result.status === 'error') {
        this.galleryPromptMessage = result.msg || 'Unable to start the gallery download.';
        return;
      }
      this.closeGalleryPrompt();
      this.addUrl = '';
    }, error => {
      this.galleryConfirmInProgress = false;
      const msg = (error?.error && typeof error.error === 'string') ? error.error : '';
      this.galleryPromptMessage = msg || 'Unable to start the gallery download.';
    });
  }

  private resetGalleryOptions(prompt: GalleryDlPrompt): void {
    const baseOptions = Array.isArray(prompt.options) ? [...prompt.options] : [];
    this.galleryRange = '';
    const metadataSpecified = typeof prompt.write_metadata === 'boolean';
    const promptAny = prompt as any;
    this.galleryCredentials = Array.isArray(promptAny?.credentials)
      ? promptAny.credentials.filter(entry => !!entry && typeof entry.id === 'string' && typeof entry.name === 'string')
      : [];
    this.galleryCookies = Array.isArray(promptAny?.cookies)
      ? promptAny.cookies.filter(entry => !!entry && typeof entry.name === 'string')
      : [];
    this.galleryWriteMetadata = !!prompt.write_metadata;
    this.galleryWriteInfoJson = !!prompt.write_info_json;
    this.galleryWriteTags = !!prompt.write_tags;
    this.galleryDownloadArchive = !!prompt.download_archive;
    this.galleryArchiveId = prompt.archive_id || '';
    this.gallerySelectedCredential = prompt.credential_id || null;
    this.gallerySelectedCookie = prompt.cookie_name || null;
    this.galleryProxy = prompt.proxy || '';
    this.galleryRetries = prompt.retries !== undefined && prompt.retries !== null ? Number(prompt.retries) : null;
    if (this.galleryRetries !== null && (isNaN(this.galleryRetries) || this.galleryRetries < 0)) {
      this.galleryRetries = null;
    }
    this.gallerySleepRequest = prompt.sleep_request || '';
    this.gallerySleep429 = prompt.sleep_429 || '';
    const extras: string[] = [];
    for (let i = 0; i < baseOptions.length; i++) {
      const option = baseOptions[i];
      if (option === '--range' && i + 1 < baseOptions.length) {
        this.galleryRange = baseOptions[i + 1];
        i++;
        continue;
      }
      if (option === '--write-metadata' && !metadataSpecified) {
        this.galleryWriteMetadata = true;
        continue;
      }
      extras.push(option);
    }
    this.galleryExtraArgs = extras.join('\n');
    const advancedActive = !!(
      this.gallerySelectedCredential ||
      this.gallerySelectedCookie ||
      this.galleryProxy.trim() ||
      (this.galleryRetries !== null && this.galleryRetries !== undefined) ||
      this.gallerySleepRequest.trim() ||
      this.gallerySleep429.trim() ||
      this.galleryWriteMetadata ||
      this.galleryWriteInfoJson ||
      this.galleryWriteTags ||
      this.galleryDownloadArchive ||
      this.galleryArchiveId.trim() ||
      this.galleryExtraArgs.trim()
    );
    this.galleryAdvancedOpen = advancedActive;
  }

  private buildGalleryOptions(): string[] {
    const args: string[] = [];
    if (this.galleryExtraArgs) {
      this.galleryExtraArgs.split(/\r?\n/).forEach(line => {
        const trimmed = line.trim();
        if (!trimmed) {
          return;
        }
        this.parseGalleryOptionLine(trimmed).forEach(token => {
          const value = token.trim();
          if (value) {
            args.push(value);
          }
        });
      });
    }

    const rangeValue = this.galleryRange.trim();
    if (rangeValue) {
      args.push('--range', rangeValue);
    }

    return args.slice(0, 64);
  }

  private parseGalleryOptionLine(line: string): string[] {
    if (!line) {
      return [];
    }
    const tokens: string[] = [];
    const regex = /"([^"]*)"|'([^']*)'|(\S+)/g;
    let match: RegExpExecArray | null;
    while ((match = regex.exec(line)) !== null) {
      const value = match[1] ?? match[2] ?? match[3];
      if (value !== undefined) {
        tokens.push(value);
      }
    }
    return tokens;
  }

  openBackendChoiceModal(choice: BackendChoice): void {
    this.backendChoiceData = choice;
    this.backendChoiceModalOpen = true;
    this.backendChoiceSubmitting = false;
  }

  closeBackendChoiceModal(resetPending = false): void {
    this.backendChoiceModalOpen = false;
    this.backendChoiceData = null;
    this.backendChoiceSubmitting = false;
    if (resetPending) {
      this.pendingAddRequest = null;
    }
  }

  chooseBackendOption(backend: 'ytdlp' | 'gallerydl'): void {
    if (!this.backendChoiceData) {
      return;
    }
    if (backend === 'gallerydl') {
      const prompt = this.backendChoiceData.gallerydl;
      this.closeBackendChoiceModal();
      this.pendingAddRequest = null;
      this.showGalleryPrompt(prompt);
      return;
    }
    this.resubmitAddWithBackend(backend);
  }

  private resubmitAddWithBackend(backend: 'ytdlp' | 'gallerydl'): void {
    const request = this.pendingAddRequest ?? {
      url: this.addUrl?.trim() || '',
      quality: this.quality,
      format: this.format,
      folder: this.folder,
      customNamePrefix: this.customNamePrefix,
      playlistStrictMode: this.playlistStrictMode,
      playlistItemLimit: this.playlistItemLimit,
      autoStart: this.autoStart
    };

    if (!request.url) {
      this.closeBackendChoiceModal(true);
      alert('Unable to determine the original URL for this request. Please try again.');
      return;
    }

    this.addInProgress = true;
    this.backendChoiceSubmitting = true;

    this.downloads.add(
      request.url,
      request.quality,
      request.format,
      request.folder,
      request.customNamePrefix,
      request.playlistStrictMode,
      request.playlistItemLimit,
      request.autoStart,
      backend
    ).subscribe({
      next: (status: Status) => {
        this.addInProgress = false;
        this.backendChoiceSubmitting = false;
        this.backendChoiceModalOpen = false;
        this.backendChoiceData = null;

        if (status.status === 'choose-backend' && status.backend_choice) {
          this.openBackendChoiceModal(status.backend_choice);
          return;
        }

        if (status.status === 'gallerydl' && status.gallerydl) {
          this.pendingAddRequest = null;
          this.showGalleryPrompt(status.gallerydl);
          return;
        }

        if (status.status === 'unsupported') {
          this.pendingAddRequest = null;
          this.showProxyPrompt(status);
          return;
        }

        if (status.status === 'error') {
          this.pendingAddRequest = null;
          alert(`Error adding URL: ${status.msg}`);
        } else {
          this.pendingAddRequest = null;
          if (status.status === 'ok') {
            this.addUrl = '';
          }
        }
      },
      error: error => {
        this.addInProgress = false;
        this.backendChoiceSubmitting = false;
        this.backendChoiceModalOpen = false;
        this.backendChoiceData = null;
        this.pendingAddRequest = null;
        const message = error?.error && typeof error.error === 'string' ? error.error : 'Unable to add download.';
        alert(message);
      }
    });
  }

  openSupportedSitesModal(): void {
    this.supportedSitesModalOpen = true;
    this.supportedSitesLoading = true;
    this.supportedSitesError = '';
    this.supportedSitesFilter = '';
    this.supportedSites = [];
    this.activeSupportedProviderIndex = 0;

    this.downloads.getSupportedSites().subscribe(response => {
      this.supportedSitesLoading = false;
      if (response.status === 'error') {
        this.supportedSitesError = response.msg || 'Unable to load supported sites.';
        return;
      }
      const providers = response.providers || {};
      this.supportedSites = Object.entries(providers).map(([provider, sites]) => ({
        provider,
        sites: (sites || []).slice().sort((a, b) => a.localeCompare(b))
      })).sort((a, b) => a.provider.localeCompare(b.provider));
    }, error => {
      this.supportedSitesLoading = false;
      const msg = (error?.error && typeof error.error === 'string') ? error.error : '';
      this.supportedSitesError = msg || 'Unable to load supported sites.';
    });
  }

  closeSupportedSitesModal(): void {
    this.supportedSitesModalOpen = false;
  }

  setActiveSupportedProvider(index: number): void {
    this.activeSupportedProviderIndex = index;
  }

  filteredSupportedSites(sites: string[]): string[] {
    if (!this.supportedSitesFilter) {
      return sites;
    }
    const needle = this.supportedSitesFilter.toLowerCase();
    return sites.filter(site => site.toLowerCase().includes(needle));
  }

  get activeSupportedProvider(): { provider: string; sites: string[] } | null {
    return this.supportedSites[this.activeSupportedProviderIndex] || null;
  }

  get activeSupportedSites(): string[] {
    const provider = this.activeSupportedProvider;
    if (!provider) {
      return [];
    }
    return this.filteredSupportedSites(provider.sites);
  }

  get supportedProviderMatches(): { provider: string; count: number; index: number }[] {
    const matches: { provider: string; count: number; index: number }[] = [];
    this.supportedSites.forEach((item, index) => {
      const count = this.filteredSupportedSites(item.sites).length;
      if (count > 0) {
        matches.push({ provider: item.provider, count, index });
      }
    });
    return matches;
  }

  get supportedSitesFilteredEmpty(): boolean {
    if (!this.supportedSitesFilter) {
      return false;
    }
    return this.supportedProviderMatches.length === 0;
  }
}
