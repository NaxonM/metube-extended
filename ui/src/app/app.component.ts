import { Component, ViewChild, ElementRef, AfterViewInit, OnInit, OnDestroy } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { faTrashAlt, faCheckCircle, faTimesCircle, IconDefinition } from '@fortawesome/free-regular-svg-icons';
import { faRedoAlt, faSun, faMoon, faCircleHalfStroke, faCheck, faExternalLinkAlt, faDownload, faFileImport, faFileExport, faCopy, faClock, faTachometerAlt, faPen, faCookieBite, faUserShield, faUserPlus, faUserSlash, faKey, faRightFromBracket, faPlay, faWindowMinimize, faWindowRestore, faArrowsLeftRight, faChevronDown, faChevronUp, faTriangleExclamation, faCircleInfo } from '@fortawesome/free-solid-svg-icons';
import { faGithub } from '@fortawesome/free-brands-svg-icons';
import { CookieService } from 'ngx-cookie-service';

import { Download, DownloadsService, Status, CurrentUser, ManagedUser, ProxySuggestion, ProxyProbeResponse, ProxyAddResponse, ProxySettings, SystemStats, CookieStatusResponse, GalleryDlPrompt, SupportedSitesResponse } from './downloads.service';
import { MasterCheckboxComponent } from './master-checkbox.component';
import { Formats, Format, Quality } from './formats';
import { Theme, Themes } from './theme';
import {KeyValue} from "@angular/common";

type AdminSection = 'proxy' | 'system' | 'users';

@Component({
    selector: 'app-root',
    templateUrl: './app.component.html',
    styleUrls: ['./app.component.sass'],
    standalone: false
})
export class AppComponent implements AfterViewInit, OnInit, OnDestroy {
  addUrl: string;
  formats: Format[] = Formats;
  qualities: Quality[];
  quality: string;
  format: string;
  folder = '';
  customNamePrefix: string;
  autoStart: boolean;
  playlistStrictMode: boolean = true;
  playlistItemLimit: number;
  addInProgress = false;
  themes: Theme[] = Themes;
  activeTheme: Theme;
  showBatchPanel: boolean = false; 
  batchImportModalOpen = false;
  batchImportText = '';
  batchImportStatus = '';
  importInProgress = false;
  cancelImportFlag = false;
  ytDlpOptionsUpdateTime: string | null = null;
  ytDlpVersion: string | null = null;
  metubeVersion: string | null = null;
  isAdvancedOpen = false;

  cookiesModalOpen = false;
  cookiesText = '';
  cookieStatus: CookieStatusResponse = { has_cookies: false, state: 'missing' };
  cookiesStatusMessage = '';
  cookiesInProgress = false;

  get cookiesConfigured(): boolean {
    return !!this.cookieStatus?.has_cookies;
  }

  currentUser: CurrentUser | null = null;
  isAdmin = false;
  adminToolsOpen = false;
  adminSectionState: Record<AdminSection, boolean> = {
    proxy: true,
    system: false,
    users: false
  };
  adminUsers: ManagedUser[] = [];
  adminLoading = false;
  adminError = '';

  proxySettingsLoading = false;
  proxySettingsSaving = false;
  proxySettingsError = '';
  proxyLimitEnabled = false;
  proxyLimitMb = 0;
  proxySettingsDirty = false;
  private proxySettingsSnapshot: ProxySettings | null = null;

  systemStats: SystemStats | null = null;
  systemStatsError = '';
  systemStatsLoading = false;
  systemStatsRates = {sentPerSec: 0, recvPerSec: 0};
  private systemStatsIntervalId: number | null = null;
  private previousSystemStats: SystemStats | null = null;
  systemStatsRequestActive = false;

  streamModalOpen = false;
  streamSource: string | null = null;
  streamMimeType = '';
  streamTitle = '';
  streamType: 'audio' | 'video' = 'video';
  streamMinimized = false;
  streamDockSide: 'left' | 'right' = 'right';

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

  galleryPromptOpen = false;
  galleryPromptData: GalleryDlPrompt | null = null;
  galleryPromptMessage = '';
  galleryConfirmInProgress = false;
  galleryRange = '';
  galleryWriteMetadata = false;
  galleryExtraArgs = '';

  supportedSitesModalOpen = false;
  supportedSitesLoading = false;
  supportedSitesError = '';
  supportedSites: { provider: string; sites: string[] }[] = [];
  supportedSitesFilter = '';

  // Download metrics
  activeDownloads = 0;
  queuedDownloads = 0;
  completedDownloads = 0;
  failedDownloads = 0;
  totalSpeed = 0;

  @ViewChild('queueMasterCheckbox') queueMasterCheckbox: MasterCheckboxComponent;
  @ViewChild('queueDelSelected') queueDelSelected: ElementRef;
  @ViewChild('queueDownloadSelected') queueDownloadSelected: ElementRef;
  @ViewChild('doneMasterCheckbox') doneMasterCheckbox: MasterCheckboxComponent;
  @ViewChild('doneDelSelected') doneDelSelected: ElementRef;
  @ViewChild('doneClearCompleted') doneClearCompleted: ElementRef;
  @ViewChild('doneClearFailed') doneClearFailed: ElementRef;
  @ViewChild('doneRetryFailed') doneRetryFailed: ElementRef;
  @ViewChild('doneDownloadSelected') doneDownloadSelected: ElementRef;
  @ViewChild('streamVideo') streamVideo?: ElementRef<HTMLVideoElement>;
  @ViewChild('streamAudio') streamAudio?: ElementRef<HTMLAudioElement>;

  faTrashAlt = faTrashAlt;
  faCheckCircle = faCheckCircle;
  faTimesCircle = faTimesCircle;
  faRedoAlt = faRedoAlt;
  faSun = faSun;
  faMoon = faMoon;
  faCheck = faCheck;
  faCircleHalfStroke = faCircleHalfStroke;
  faDownload = faDownload;
  faChevronDown = faChevronDown;
  faChevronUp = faChevronUp;
  faExternalLinkAlt = faExternalLinkAlt;
  faFileImport = faFileImport;
  faFileExport = faFileExport;
  faCopy = faCopy;
  faGithub = faGithub;
  faClock = faClock;
  faTachometerAlt = faTachometerAlt;
  faPen = faPen;
  faCookieBite = faCookieBite;
  faTriangleExclamation = faTriangleExclamation;
  faUserShield = faUserShield;
  faUserPlus = faUserPlus;
  faUserSlash = faUserSlash;
  faKey = faKey;
  faRightFromBracket = faRightFromBracket;
  faPlay = faPlay;
  faWindowMinimize = faWindowMinimize;
  faWindowRestore = faWindowRestore;
  faArrowsLeftRight = faArrowsLeftRight;
  faCircleInfo = faCircleInfo;

  constructor(public downloads: DownloadsService, private cookieService: CookieService, private http: HttpClient) {
    this.format = cookieService.get('metube_format') || 'any';
    // Needs to be set or qualities won't automatically be set
    this.setQualities()
    this.quality = cookieService.get('metube_quality') || 'best';
    this.autoStart = cookieService.get('metube_auto_start') !== 'false';

    this.activeTheme = this.getPreferredTheme(cookieService);

    // Subscribe to download updates
    this.downloads.queueChanged.subscribe(() => {
      this.updateMetrics();
    });
    this.downloads.doneChanged.subscribe(() => {
      this.updateMetrics();
    });
    // Subscribe to real-time updates
    this.downloads.updated.subscribe(() => {
      this.updateMetrics();
    });
  }

  ngOnInit() {
    this.getConfiguration();
    this.getYtdlOptionsUpdateTime();
    this.setTheme(this.activeTheme);
    this.refreshCookiesStatus();
    this.loadCurrentUser();

    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      if (this.activeTheme.id === 'auto') {
         this.setTheme(this.activeTheme);
      }
    });
  }

  ngAfterViewInit() {
    this.downloads.queueChanged.subscribe(() => {
      this.queueMasterCheckbox.selectionChanged();
    });
    this.downloads.doneChanged.subscribe(() => {
      this.doneMasterCheckbox.selectionChanged();
      let completed: number = 0, failed: number = 0;
      this.downloads.done.forEach(dl => {
        if (dl.status === 'finished')
          completed++;
        else if (dl.status === 'error')
          failed++;
      });
      this.doneClearCompleted.nativeElement.disabled = completed === 0;
      this.doneClearFailed.nativeElement.disabled = failed === 0;
      this.doneRetryFailed.nativeElement.disabled = failed === 0;
    });
    this.fetchVersionInfo();
  }

  ngOnDestroy(): void {
    this.stopSystemStatsPolling();
    this.resetSystemStatsState();
  }

  // workaround to allow fetching of Map values in the order they were inserted
  //  https://github.com/angular/angular/issues/31420
  asIsOrder(a, b) {
    return 1;
  }

  qualityChanged() {
    this.cookieService.set('metube_quality', this.quality, { expires: 3650 });
  }

  getYtdlOptionsUpdateTime() {
    this.downloads.ytdlOptionsChanged.subscribe({
      next: (data) => {
        if (data['success']){
          const date = new Date(data['update_time'] * 1000);
          this.ytDlpOptionsUpdateTime=date.toLocaleString();
        }else{
          alert("Error reload yt-dlp options: "+data['msg']);
        }
      }
    });
  }
  getConfiguration() {
    this.downloads.configurationChanged.subscribe({
      next: (config) => {
        this.playlistStrictMode = config['DEFAULT_OPTION_PLAYLIST_STRICT_MODE'];
        const playlistItemLimit = config['DEFAULT_OPTION_PLAYLIST_ITEM_LIMIT'];
        if (playlistItemLimit !== '0') {
          this.playlistItemLimit = playlistItemLimit;
        }
      }
    });
  }

  getPreferredTheme(cookieService: CookieService) {
    let theme = 'auto';
    if (cookieService.check('metube_theme')) {
      theme = cookieService.get('metube_theme');
    }

    return this.themes.find(x => x.id === theme) ?? this.themes.find(x => x.id === 'auto');
  }

  themeChanged(theme: Theme) {
    this.cookieService.set('metube_theme', theme.id, { expires: 3650 });
    this.setTheme(theme);
  }

  setTheme(theme: Theme) {
    this.activeTheme = theme;
    if (theme.id === 'auto' && window.matchMedia('(prefers-color-scheme: dark)').matches) {
      document.documentElement.setAttribute('data-bs-theme', 'dark');
    } else {
      document.documentElement.setAttribute('data-bs-theme', theme.id);
    }
  }

  formatChanged() {
    this.cookieService.set('metube_format', this.format, { expires: 3650 });
    // Updates to use qualities available
    this.setQualities()
  }

  autoStartChanged() {
    this.cookieService.set('metube_auto_start', this.autoStart ? 'true' : 'false', { expires: 3650 });
  }

  toggleAdminTools(): void {
    this.adminToolsOpen = !this.adminToolsOpen;
    if (!this.isAdmin) {
      return;
    }
    if (this.adminToolsOpen) {
      if (this.isAdminSectionOpen('system')) {
        this.startSystemStatsPolling();
      }
    } else {
      this.stopSystemStatsPolling();
    }
  }

  isAdminSectionOpen(section: AdminSection): boolean {
    return !!this.adminSectionState[section];
  }

  toggleAdminSection(section: AdminSection): void {
    this.adminSectionState[section] = !this.adminSectionState[section];
    if (section === 'system') {
      if (this.isAdminSectionOpen('system') && this.adminToolsOpen) {
        this.startSystemStatsPolling();
      } else {
        this.stopSystemStatsPolling();
      }
    }
  }

  private resetAdminSectionState(): void {
    this.adminSectionState = {
      proxy: true,
      system: false,
      users: false
    };
  }

  queueSelectionChanged(checked: number) {
    this.queueDelSelected.nativeElement.disabled = checked == 0;
    this.queueDownloadSelected.nativeElement.disabled = checked == 0;
  }

  doneSelectionChanged(checked: number) {
    this.doneDelSelected.nativeElement.disabled = checked == 0;
    this.doneDownloadSelected.nativeElement.disabled = checked == 0;
  }

  setQualities() {
    // qualities for specific format
    this.qualities = this.formats.find(el => el.id == this.format).qualities
    const exists = this.qualities.find(el => el.id === this.quality)
    this.quality = exists ? this.quality : 'best'
  }

  addDownload(url?: string, quality?: string, format?: string, folder?: string, customNamePrefix?: string, playlistStrictMode?: boolean, playlistItemLimit?: number, autoStart?: boolean) {
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

    console.debug('Downloading:', { url, quality, format, folder, customNamePrefix, playlistStrictMode, playlistItemLimit, autoStart });
    this.addInProgress = true;
    this.downloads.add(url, quality, format, folder, customNamePrefix, playlistStrictMode, playlistItemLimit, autoStart).subscribe((status: Status) => {
      this.addInProgress = false;
      if (status.status === 'gallerydl' && status.gallerydl) {
        this.showGalleryPrompt(status.gallerydl);
        return;
      }
      if (status.status === 'unsupported') {
        this.showProxyPrompt(status);
        return;
      }
      if (status.status === 'error') {
        alert(`Error adding URL: ${status.msg}`);
      } else {
        this.addUrl = '';
      }
    });
  }

  downloadItemByKey(id: string) {
    this.downloads.startById([id]).subscribe();
  }

  retryDownload(key: string, download: Download) {
    this.addDownload(download.url, download.quality, download.format, download.folder, download.custom_name_prefix, download.playlist_strict_mode, download.playlist_item_limit, true);
    this.downloads.delById('done', [key]).subscribe();
  }

  delDownload(where: 'queue' | 'done', id: string) {
    this.downloads.delById(where, [id]).subscribe();
  }

  startSelectedDownloads(where: 'queue' | 'done'){
    this.downloads.startByFilter(where, dl => dl.checked).subscribe();
  }

  delSelectedDownloads(where: 'queue' | 'done') {
    this.downloads.delByFilter(where, dl => dl.checked).subscribe();
  }

  clearCompletedDownloads() {
    this.downloads.delByFilter('done', dl => dl.status === 'finished').subscribe();
  }

  clearFailedDownloads() {
    this.downloads.delByFilter('done', dl => dl.status === 'error').subscribe();
  }

  retryFailedDownloads() {
    this.downloads.done.forEach((dl, key) => {
      if (dl.status === 'error') {
        this.retryDownload(key, dl);
      }
    });
  }

  renameDownload(key: string, download: Download) {
    const currentName = download.filename;
    const newName = prompt('Enter new filename', currentName);
    if (!newName || newName === currentName) {
      return;
    }

    this.downloads.rename(key, newName).subscribe((status: Status) => {
      if (status.status === 'error') {
        alert(`Error renaming file: ${status.msg}`);
      }
    });
  }

  private showProxyPrompt(status: Status) {
    if (!status.proxy) {
      alert(status.msg || 'This URL is not supported by yt-dlp.');
      return;
    }

    this.proxyPromptData = {...status.proxy};
    this.proxyPromptMessage = status.msg || 'This URL is not supported by yt-dlp. Do you want to download it directly through the server?';
    this.proxyProbeResult = null;
    this.proxyProbeError = '';
    this.proxySuggestedTitle = null;
    this.proxyOverrideEnabled = false;
    this.proxyOverrideMb = status.proxy.limit_enabled ? status.proxy.size_limit_mb : null;
    this.proxyConfirmInProgress = false;
    this.proxyPromptOpen = true;
    this.proxyProbeLoading = true;

    this.downloads.proxyProbe(status.proxy.url).subscribe((result: ProxyProbeResponse) => {
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

  closeProxyPrompt() {
    this.proxyPromptOpen = false;
    this.proxyPromptData = null;
    this.proxyProbeResult = null;
    this.proxyProbeError = '';
    this.proxySuggestedTitle = null;
    this.proxyConfirmInProgress = false;
  }

  confirmProxyDownload() {
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
    this.downloads.proxyAdd(payload).subscribe((result: ProxyAddResponse) => {
      this.proxyConfirmInProgress = false;
      if (result.status === 'error') {
        this.proxyProbeError = result.msg || 'Unable to start the proxy download.';
        return;
      }
      this.closeProxyPrompt();
      this.addUrl = '';
    }, (error) => {
      this.proxyConfirmInProgress = false;
      this.proxyProbeError = (error?.error && typeof error.error === 'string') ? error.error : 'Unable to start the proxy download.';
    });
  }

  private showGalleryPrompt(data: GalleryDlPrompt) {
    this.galleryPromptData = {
      ...data,
      options: Array.isArray(data.options) ? [...data.options] : []
    };
    this.galleryPromptMessage = '';
    this.galleryConfirmInProgress = false;
    this.resetGalleryOptions(this.galleryPromptData);
    this.galleryPromptOpen = true;
  }

  closeGalleryPrompt() {
    this.galleryPromptOpen = false;
    this.galleryPromptData = null;
    this.galleryPromptMessage = '';
    this.galleryConfirmInProgress = false;
    this.galleryRange = '';
    this.galleryWriteMetadata = false;
    this.galleryExtraArgs = '';
  }

  confirmGalleryDownload() {
    if (!this.galleryPromptData || this.galleryConfirmInProgress) {
      return;
    }

    const options = this.buildGalleryOptions();

    const payload = {
      url: this.galleryPromptData.url,
      title: this.galleryPromptData.title || this.extractFileName(this.galleryPromptData.url),
      auto_start: this.galleryPromptData.auto_start !== false,
      options
    };

    this.galleryConfirmInProgress = true;
    this.downloads.gallerydlAdd(payload).subscribe((result: Status) => {
      this.galleryConfirmInProgress = false;
      if (result.status === 'error') {
        this.galleryPromptMessage = result.msg || 'Unable to start the gallery download.';
        return;
      }
      this.closeGalleryPrompt();
      this.addUrl = '';
    }, (error) => {
      this.galleryConfirmInProgress = false;
      const msg = (error?.error && typeof error.error === 'string') ? error.error : '';
      this.galleryPromptMessage = msg || 'Unable to start the gallery download.';
    });
  }

  private resetGalleryOptions(prompt: GalleryDlPrompt) {
    const baseOptions = Array.isArray(prompt.options) ? [...prompt.options] : [];
    this.galleryRange = '';
    this.galleryWriteMetadata = false;
    const extras: string[] = [];
    for (let i = 0; i < baseOptions.length; i++) {
      const option = baseOptions[i];
      if (option === '--range' && i + 1 < baseOptions.length) {
        this.galleryRange = baseOptions[i + 1];
        i++;
        continue;
      }
      if (option === '--write-metadata') {
        this.galleryWriteMetadata = true;
        continue;
      }
      extras.push(option);
    }
    this.galleryExtraArgs = extras.join('\n');
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

    if (this.galleryWriteMetadata) {
      args.push('--write-metadata');
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

  openSupportedSitesModal() {
    this.supportedSitesModalOpen = true;
    this.supportedSitesLoading = true;
    this.supportedSitesError = '';
    this.supportedSitesFilter = '';
    this.supportedSites = [];

    this.downloads.getSupportedSites().subscribe((response: SupportedSitesResponse) => {
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
    }, (error) => {
      this.supportedSitesLoading = false;
      const msg = (error?.error && typeof error.error === 'string') ? error.error : '';
      this.supportedSitesError = msg || 'Unable to load supported sites.';
    });
  }

  closeSupportedSitesModal() {
    this.supportedSitesModalOpen = false;
  }

  filteredSupportedSites(sites: string[]): string[] {
    if (!this.supportedSitesFilter) {
      return sites;
    }
    const needle = this.supportedSitesFilter.toLowerCase();
    return sites.filter(site => site.toLowerCase().includes(needle));
  }

  get supportedSitesFilteredEmpty(): boolean {
    if (!this.supportedSitesFilter) {
      return false;
    }
    return this.supportedSites.every(provider => this.filteredSupportedSites(provider.sites).length === 0);
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

  extractFileName(url: string): string {
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

  openStream(key: string, download: Download): void {
    if (!download || !download.filename) {
      alert('This file is not available for streaming.');
      return;
    }

    const mimeType = this.getMimeType(download.filename);
    this.streamTitle = download.title || download.filename;
    this.streamMimeType = mimeType;
    this.streamType = this.getStreamType(mimeType, download);
    this.streamSource = this.buildStreamLink(key);
    this.streamModalOpen = true;
    this.streamMinimized = false;
    this.streamDockSide = 'right';

    setTimeout(() => {
      if (this.streamType === 'audio') {
        this.streamAudio?.nativeElement?.load();
      } else {
        this.streamVideo?.nativeElement?.load();
      }
    }, 0);
  }

  closeStreamModal(): void {
    const videoEl = this.streamVideo?.nativeElement;
    const audioEl = this.streamAudio?.nativeElement;
    if (videoEl) {
      videoEl.pause();
      videoEl.currentTime = 0;
    }
    if (audioEl) {
      audioEl.pause();
      audioEl.currentTime = 0;
    }
    this.streamModalOpen = false;
    this.streamSource = null;
    this.streamTitle = '';
    this.streamMimeType = '';
    this.streamType = 'video';
    this.streamMinimized = false;
  }

  minimizeStream(side: 'left' | 'right' = this.streamDockSide): void {
    if (!this.streamModalOpen) {
      return;
    }
    this.streamDockSide = side;
    this.streamMinimized = true;
  }

  restoreStream(): void {
    if (!this.streamModalOpen) {
      return;
    }
    this.streamMinimized = false;
  }

  toggleStreamDock(): void {
    this.streamDockSide = this.streamDockSide === 'left' ? 'right' : 'left';
  }

  private getStreamType(mimeType: string, download: Download): 'audio' | 'video' {
    if (mimeType.startsWith('audio/')) {
      return 'audio';
    }
    if (mimeType.startsWith('video/')) {
      return 'video';
    }
    const filename = (download.filename || '').toLowerCase();
    const audioExtensions = ['.mp3', '.m4a', '.aac', '.opus', '.ogg', '.oga', '.wav', '.flac'];
    if (download.quality === 'audio' || audioExtensions.some(ext => filename.endsWith(ext))) {
      return 'audio';
    }
    return 'video';
  }

  private getMimeType(filename: string): string {
    const ext = (filename.split('.').pop() || '').toLowerCase();
    switch (ext) {
      case 'mp4':
      case 'm4v':
        return 'video/mp4';
      case 'webm':
        return 'video/webm';
      case 'mkv':
        return 'video/x-matroska';
      case 'mov':
        return 'video/quicktime';
      case 'avi':
        return 'video/x-msvideo';
      case 'flv':
        return 'video/x-flv';
      case 'mp3':
        return 'audio/mpeg';
      case 'm4a':
        return 'audio/mp4';
      case 'aac':
        return 'audio/aac';
      case 'ogg':
      case 'oga':
        return 'audio/ogg';
      case 'opus':
        return 'audio/ogg; codecs=opus';
      case 'wav':
        return 'audio/wav';
      case 'flac':
        return 'audio/flac';
      default:
        return '';
    }
  }

  private buildStreamLink(id: string): string {
    const encoded = encodeURIComponent(id);
    const relative = `stream?id=${encoded}`;
    try {
      return new URL(relative, window.location.href).toString();
    } catch {
      return relative;
    }
  }

  openCookiesModal(): void {
    this.cookiesModalOpen = true;
    this.cookiesText = '';
    this.cookiesStatusMessage = '';
    this.refreshCookiesStatus();
  }

  closeCookiesModal(): void {
    this.cookiesModalOpen = false;
    this.cookiesInProgress = false;
    this.cookiesText = '';
  }

  refreshCookiesStatus(): void {
    this.downloads.getCookiesStatus().subscribe(data => {
      this.cookieStatus = this.normalizeCookieStatus(data);
    });
  }

  saveCookies(): void {
    const text = this.cookiesText?.trim();
    if (!text) {
      alert('Please paste your cookies in the provided text area.');
      return;
    }
    this.persistCookies(text);
  }

  clearCookies(): void {
    if (!this.cookiesConfigured) {
      return;
    }

    this.cookiesInProgress = true;
    this.cookiesStatusMessage = '';

    this.downloads.clearCookies().subscribe((status: Status & {cookies?: CookieStatusResponse}) => {
      this.cookiesInProgress = false;
      if (status.status === 'error') {
        alert(`Error clearing cookies: ${status.msg}`);
        return;
      }
      const updated = this.normalizeCookieStatus(status.cookies ?? { has_cookies: false, state: 'missing' });
      this.cookieStatus = updated;
      this.cookiesStatusMessage = 'Cookies cleared.';
      this.refreshCookiesStatus();
    });
  }

  get cookieStatusSummary(): string {
    if (this.cookiesStatusMessage) {
      return this.cookiesStatusMessage;
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

  get cookieSmartButtonLabel(): string {
    if (this.cookiesInProgress) {
      return 'Working...';
    }
    return this.cookiesConfigured ? 'Paste or remove cookies' : 'Paste cookies from clipboard';
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

  async handleCookieSmartAction(): Promise<void> {
    if (this.cookiesInProgress) {
      return;
    }

    this.cookiesStatusMessage = '';

    const clipboardText = await this.readClipboardText();
    if (this.looksLikeCookies(clipboardText)) {
      this.cookiesText = clipboardText?.trim() || '';
      this.persistCookies(this.cookiesText);
      return;
    }

    const manual = this.cookiesText?.trim();
    if (manual) {
      this.persistCookies(manual);
      return;
    }

    if (this.cookiesConfigured) {
      const confirmClear = confirm('No cookies were detected in your clipboard. Would you like to remove the saved cookies instead?');
      if (confirmClear) {
        this.clearCookies();
      } else {
        this.cookiesStatusMessage = 'Copy your YouTube cookies to the clipboard, then click the button again.';
      }
    } else {
      this.cookiesStatusMessage = 'Copy your YouTube cookies to the clipboard, then click the button to paste them automatically.';
    }
  }

  private persistCookies(rawText: string): void {
    const text = rawText.trim();
    if (!text) {
      this.cookiesStatusMessage = 'Please paste your cookies in the provided text area.';
      return;
    }

    this.cookiesInProgress = true;
    this.cookiesStatusMessage = '';

    this.downloads.setCookies(text).subscribe((status: Status & {cookies?: CookieStatusResponse}) => {
      this.cookiesInProgress = false;
      if (status.status === 'error') {
        alert(`Error saving cookies: ${status.msg}`);
        return;
      }
      const updated = this.normalizeCookieStatus(status.cookies ?? { has_cookies: true, state: 'unknown' });
      this.cookieStatus = updated;
      this.cookiesText = '';
      this.cookiesStatusMessage = 'Cookies saved successfully.';
      this.refreshCookiesStatus();
    });
  }

  private async readClipboardText(): Promise<string | null> {
    if (typeof navigator === 'undefined' || !navigator.clipboard || !navigator.clipboard.readText) {
      return null;
    }
    try {
      return await navigator.clipboard.readText();
    } catch (error) {
      console.warn('Unable to read clipboard:', error);
      if (!this.cookiesStatusMessage) {
        this.cookiesStatusMessage = 'Unable to access clipboard. Paste your cookies manually.';
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

  loadCurrentUser(): void {
    this.downloads.getCurrentUser().subscribe(user => {
      this.currentUser = user;
      this.isAdmin = !!user && user.role === 'admin';
      if (this.isAdmin) {
        this.refreshUsers();
        this.refreshProxySettings();
        if (this.adminToolsOpen && this.isAdminSectionOpen('system')) {
          this.startSystemStatsPolling();
        } else {
          this.stopSystemStatsPolling();
        }
      } else {
        this.adminUsers = [];
        this.resetProxySettingsState();
        this.stopSystemStatsPolling();
        this.resetSystemStatsState();
        this.resetAdminSectionState();
      }
    });
  }

  refreshUsers(): void {
    if (!this.isAdmin) {
      return;
    }
    this.adminLoading = true;
    this.downloads.listUsers().subscribe(response => {
      this.adminUsers = (response?.users ?? []).slice().sort((a, b) => a.username.localeCompare(b.username));
      this.adminLoading = false;
    });
  }

  refreshProxySettings(): void {
    if (!this.isAdmin) {
      return;
    }
    this.proxySettingsLoading = true;
    this.proxySettingsError = '';
    this.downloads.getProxySettings().subscribe(result => {
      this.proxySettingsLoading = false;
      if ((result as any)?.status === 'error') {
        this.proxySettingsError = (result as any).msg || 'Unable to load proxy settings.';
        return;
      }
      const settings = result as ProxySettings;
      this.proxyLimitEnabled = !!settings.limit_enabled;
      this.proxyLimitMb = this.normalizeProxyLimitMb(settings.limit_mb);
      this.proxySettingsSnapshot = {
        limit_enabled: this.proxyLimitEnabled,
        limit_mb: this.proxyLimitMb
      };
      this.proxySettingsDirty = false;
    }, () => {
      this.proxySettingsLoading = false;
      this.proxySettingsError = 'Unable to load proxy settings.';
    });
  }

  saveProxySettings(): void {
    if (!this.isAdmin || this.proxySettingsSaving || !this.proxySettingsDirty) {
      return;
    }
    this.proxySettingsSaving = true;
    this.proxySettingsError = '';
    const payload: Partial<ProxySettings> = {
      limit_enabled: this.proxyLimitEnabled,
      limit_mb: this.normalizeProxyLimitMb(this.proxyLimitMb)
    };
    this.downloads.updateProxySettings(payload).subscribe(result => {
      this.proxySettingsSaving = false;
      if ((result as any)?.status === 'error') {
        this.proxySettingsError = (result as any).msg || 'Unable to save proxy settings.';
        return;
      }
      const settings = result as ProxySettings;
      this.proxyLimitEnabled = !!settings.limit_enabled;
      this.proxyLimitMb = this.normalizeProxyLimitMb(settings.limit_mb);
      this.proxySettingsSnapshot = {
        limit_enabled: this.proxyLimitEnabled,
        limit_mb: this.proxyLimitMb
      };
      this.proxySettingsDirty = false;
    }, () => {
      this.proxySettingsSaving = false;
      this.proxySettingsError = 'Unable to save proxy settings.';
    });
  }

  onProxyLimitToggle(enabled: boolean): void {
    this.proxyLimitEnabled = enabled;
    this.updateProxyDirtyState();
  }

  onProxyLimitMbChange(value: any): void {
    this.proxyLimitMb = this.normalizeProxyLimitMb(value);
    this.updateProxyDirtyState();
  }

  private updateProxyDirtyState(): void {
    if (!this.proxySettingsSnapshot) {
      this.proxySettingsDirty = true;
      return;
    }
    this.proxySettingsDirty = (
      this.proxyLimitEnabled !== this.proxySettingsSnapshot.limit_enabled ||
      this.normalizeProxyLimitMb(this.proxyLimitMb) !== this.proxySettingsSnapshot.limit_mb
    );
  }

  private resetProxySettingsState(): void {
    this.proxySettingsLoading = false;
    this.proxySettingsSaving = false;
    this.proxySettingsError = '';
    this.proxyLimitEnabled = false;
    this.proxyLimitMb = 0;
    this.proxySettingsDirty = false;
    this.proxySettingsSnapshot = null;
  }

  private normalizeProxyLimitMb(value: any): number {
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric < 0) {
      return 0;
    }
    return Math.floor(numeric);
  }

  startSystemStatsPolling(): void {
    if (!this.isAdmin || !this.adminToolsOpen || !this.isAdminSectionOpen('system')) {
      return;
    }
    this.stopSystemStatsPolling();
    this.fetchSystemStats();
    this.systemStatsIntervalId = window.setInterval(() => this.fetchSystemStats(), 5000);
  }

  stopSystemStatsPolling(): void {
    if (this.systemStatsIntervalId !== null) {
      window.clearInterval(this.systemStatsIntervalId);
      this.systemStatsIntervalId = null;
    }
    this.systemStatsRequestActive = false;
  }

  refreshSystemStats(): void {
    if (!this.isAdmin || !this.adminToolsOpen || !this.isAdminSectionOpen('system')) {
      return;
    }
    this.fetchSystemStats();
  }

  private fetchSystemStats(): void {
    if (!this.isAdmin || !this.adminToolsOpen || !this.isAdminSectionOpen('system') || this.systemStatsRequestActive) {
      return;
    }
    this.systemStatsRequestActive = true;
    if (!this.systemStats) {
      this.systemStatsLoading = true;
    }
    this.downloads.getSystemStats().subscribe(result => {
      this.systemStatsRequestActive = false;
      this.systemStatsLoading = false;
      if ((result as any)?.status === 'error') {
        this.systemStatsError = (result as any).msg || 'Unable to load system statistics.';
        return;
      }
      const data = result as SystemStats;
      this.systemStatsError = '';
      const previous = this.previousSystemStats;
      if (previous && data.timestamp > previous.timestamp) {
        const delta = data.timestamp - previous.timestamp;
        const sentDelta = data.network.bytes_sent - previous.network.bytes_sent;
        const recvDelta = data.network.bytes_recv - previous.network.bytes_recv;
        this.systemStatsRates = {
          sentPerSec: delta > 0 ? Math.max(sentDelta / delta, 0) : 0,
          recvPerSec: delta > 0 ? Math.max(recvDelta / delta, 0) : 0
        };
      } else {
        this.systemStatsRates = {sentPerSec: 0, recvPerSec: 0};
      }
      this.systemStats = data;
      this.previousSystemStats = data;
    }, () => {
      this.systemStatsRequestActive = false;
      this.systemStatsLoading = false;
      this.systemStatsError = 'Unable to load system statistics.';
    });
  }

  private resetSystemStatsState(): void {
    this.systemStats = null;
    this.previousSystemStats = null;
    this.systemStatsRates = {sentPerSec: 0, recvPerSec: 0};
    this.systemStatsError = '';
    this.systemStatsLoading = false;
    this.systemStatsRequestActive = false;
  }

  formatRate(value: number): string {
    if (!Number.isFinite(value) || value <= 0) {
      return '0 B/s';
    }
    return `${this.formatBytes(value)} /s`;
  }

  formatDuration(seconds: number | null | undefined): string {
    const total = Number(seconds);
    if (!Number.isFinite(total) || total <= 0) {
      return '—';
    }
    let remaining = Math.floor(total);
    const parts: string[] = [];
    const days = Math.floor(remaining / 86400);
    if (days) {
      parts.push(`${days}d`);
      remaining -= days * 86400;
    }
    const hours = Math.floor(remaining / 3600);
    if (hours || parts.length) {
      parts.push(`${hours}h`);
      remaining -= hours * 3600;
    }
    const minutes = Math.floor(remaining / 60);
    if (minutes || parts.length) {
      parts.push(`${minutes}m`);
      remaining -= minutes * 60;
    }
    if (!parts.length || parts.length < 3) {
      parts.push(`${remaining}s`);
    }
    return parts.slice(0, 3).join(' ');
  }

  formatTimestampLocal(epochSeconds: number | null | undefined): string {
    const value = Number(epochSeconds);
    if (!Number.isFinite(value)) {
      return '—';
    }
    const date = new Date(value * 1000);
    if (Number.isNaN(date.getTime())) {
      return '—';
    }
    return date.toLocaleTimeString();
  }

  promptCreateUser(): void {
    const username = (prompt('Enter a username for the new account') || '').trim();
    if (!username) {
      return;
    }
    const password = prompt(`Enter a password for ${username}`) || '';
    if (!password) {
      alert('Password is required.');
      return;
    }
    const makeAdmin = confirm('Should this user have administrator access?');
    this.downloads.createUser(username, password, makeAdmin ? 'admin' : 'user').subscribe(result => {
      if ((result as any)?.status === 'error') {
        alert((result as any).msg || 'Failed to create user.');
        return;
      }
      this.refreshUsers();
    });
  }

  toggleUserRole(user: ManagedUser): void {
    const nextRole = user.role === 'admin' ? 'user' : 'admin';
    if (!confirm(`Change role for ${user.username} to ${nextRole}?`)) {
      return;
    }
    this.downloads.updateUser(user.id, {role: nextRole}).subscribe(result => {
      if ((result as any)?.status === 'error') {
        alert((result as any).msg || 'Failed to update role.');
        return;
      }
      this.refreshUsers();
    });
  }

  toggleUserDisabled(user: ManagedUser): void {
    const nextState = !user.disabled;
    if (!confirm(`${nextState ? 'Disable' : 'Enable'} ${user.username}?`)) {
      return;
    }
    this.downloads.updateUser(user.id, {disabled: nextState}).subscribe(result => {
      if ((result as any)?.status === 'error') {
        alert((result as any).msg || 'Failed to update status.');
        return;
      }
      this.refreshUsers();
    });
  }

  resetUserPassword(user: ManagedUser): void {
    const password = prompt(`Enter a new password for ${user.username}`) || '';
    if (!password) {
      return;
    }
    this.downloads.updateUser(user.id, {password}).subscribe(result => {
      if ((result as any)?.status === 'error') {
        alert((result as any).msg || 'Failed to reset password.');
        return;
      }
      alert('Password updated successfully.');
    });
  }

  deleteUser(user: ManagedUser): void {
    if (!confirm(`Delete user ${user.username}? This action cannot be undone.`)) {
      return;
    }
    this.downloads.deleteUser(user.id).subscribe(result => {
      if ((result as any)?.status === 'error') {
        alert((result as any).msg || 'Failed to delete user.');
        return;
      }
      this.refreshUsers();
    });
  }

  isSelf(user: ManagedUser): boolean {
    return !!this.currentUser && this.currentUser.id === user.id;
  }

  formatTimestamp(value: number | null | undefined): string {
    if (!value) {
      return '—';
    }
    const date = new Date(value * 1000);
    if (Number.isNaN(date.getTime())) {
      return '—';
    }
    return date.toLocaleString();
  }

  activeAdminCount(): number {
    return this.adminUsers.filter(user => user.role === 'admin' && !user.disabled).length;
  }

  downloadSelectedFiles() {
    this.downloads.done.forEach((dl, key) => {
      if (dl.status === 'finished' && dl.checked) {
        const link = document.createElement('a');
        link.href = this.buildDownloadLink(dl);
        link.setAttribute('download', dl.filename);
        link.setAttribute('target', '_self');
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
      }
    });
  }

  buildDownloadLink(download: Download) {
    let baseDir = this.downloads.configuration["PUBLIC_HOST_URL"];
    if (download.quality == 'audio' || download.filename.endsWith('.mp3')) {
      baseDir = this.downloads.configuration["PUBLIC_HOST_AUDIO_URL"];
    }

    if (download.folder) {
      baseDir += download.folder + '/';
    }

    return baseDir + encodeURIComponent(download.filename);
  }

  identifyDownloadRow(index: number, row: KeyValue<string, Download>) {
    return row.key;
  }

  isNumber(event) {
    const charCode = (event.which) ? event.which : event.keyCode;
    if (charCode > 31 && (charCode < 48 || charCode > 57)) {
      event.preventDefault();
    }
  }

  // Toggle inline batch panel (if you want to use an inline panel for export; not used for import modal)
  toggleBatchPanel(): void {
    this.showBatchPanel = !this.showBatchPanel;
  }

  // Open the Batch Import modal
  openBatchImportModal(): void {
    this.batchImportModalOpen = true;
    this.batchImportText = '';
    this.batchImportStatus = '';
    this.importInProgress = false;
    this.cancelImportFlag = false;
  }

  // Close the Batch Import modal
  closeBatchImportModal(): void {
    this.batchImportModalOpen = false;
  }

  // Start importing URLs from the batch modal textarea
  startBatchImport(): void {
    const urls = this.batchImportText
      .split(/\r?\n/)
      .map(url => url.trim())
      .filter(url => url.length > 0);
    if (urls.length === 0) {
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
      // Now pass the selected quality, format, folder, etc. to the add() method
      this.downloads.add(url, this.quality, this.format, this.folder, this.customNamePrefix,
        this.playlistStrictMode, this.playlistItemLimit, this.autoStart)
        .subscribe({
          next: (status: Status) => {
            if (status.status === 'error') {
              alert(`Error adding URL ${url}: ${status.msg}`);
            }
            index++;
            setTimeout(processNext, delayBetween);
          },
          error: (err) => {
            console.error(`Error importing URL ${url}:`, err);
            index++;
            setTimeout(processNext, delayBetween);
          }
        });
    };
    processNext();
  }

  // Cancel the batch import process
  cancelBatchImport(): void {
    if (this.importInProgress) {
      this.cancelImportFlag = true;
      this.batchImportStatus += ' Cancelling...';
    }
  }

  // Export URLs based on filter: 'pending', 'completed', 'failed', or 'all'
  exportBatchUrls(filter: 'pending' | 'completed' | 'failed' | 'all'): void {
    let urls: string[];
    if (filter === 'pending') {
      urls = Array.from(this.downloads.queue.values()).map(dl => dl.url);
    } else if (filter === 'completed') {
      // Only finished downloads in the "done" Map
      urls = Array.from(this.downloads.done.values()).filter(dl => dl.status === 'finished').map(dl => dl.url);
    } else if (filter === 'failed') {
      // Only error downloads from the "done" Map
      urls = Array.from(this.downloads.done.values()).filter(dl => dl.status === 'error').map(dl => dl.url);
    } else {
      // All: pending + both finished and error in done
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

  // Copy URLs to clipboard based on filter: 'pending', 'completed', 'failed', or 'all'
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

  fetchVersionInfo(): void {
    const baseUrl = `${window.location.origin}${window.location.pathname.replace(/\/[^\/]*$/, '/')}`;
    const versionUrl = `${baseUrl}version`;
    this.http.get<{ 'yt-dlp': string, version: string }>(versionUrl)
      .subscribe({
        next: (data) => {
          this.ytDlpVersion = data['yt-dlp'];
          this.metubeVersion = data.version;
        },
        error: () => {
          this.ytDlpVersion = null;
          this.metubeVersion = null;
        }
      });
  }

  toggleAdvanced() {
    this.isAdvancedOpen = !this.isAdvancedOpen;
  }

  private updateMetrics() {
    this.activeDownloads = Array.from(this.downloads.queue.values()).filter(d => d.status === 'downloading' || d.status === 'preparing').length;
    this.queuedDownloads = Array.from(this.downloads.queue.values()).filter(d => d.status === 'pending').length;
    this.completedDownloads = Array.from(this.downloads.done.values()).filter(d => d.status === 'finished').length;
    this.failedDownloads = Array.from(this.downloads.done.values()).filter(d => d.status === 'error').length;
    
    // Calculate total speed from downloading items
    const downloadingItems = Array.from(this.downloads.queue.values())
      .filter(d => d.status === 'downloading');
    
    this.totalSpeed = downloadingItems.reduce((total, item) => total + (item.speed || 0), 0);
  }
}
