import { Component, ViewChild, ElementRef, AfterViewInit, OnInit, OnDestroy } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { faTrashAlt, faCheckCircle, faTimesCircle, IconDefinition } from '@fortawesome/free-regular-svg-icons';
import { faRedoAlt, faSun, faMoon, faCircleHalfStroke, faCheck, faExternalLinkAlt, faDownload, faFileImport, faFileExport, faCopy, faClock, faTachometerAlt, faPen, faCookieBite, faUserShield, faUserPlus, faUserSlash, faKey, faRightFromBracket, faPlay, faWindowMinimize, faWindowRestore, faArrowsLeftRight, faChevronDown, faChevronUp } from '@fortawesome/free-solid-svg-icons';
import { faGithub } from '@fortawesome/free-brands-svg-icons';
import { CookieService } from 'ngx-cookie-service';

import { Download, DownloadsService, Status, CurrentUser, ManagedUser, ProxySuggestion, ProxyProbeResponse, ProxyAddResponse, ProxySettings, SystemStats } from './downloads.service';
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
  cookiesConfigured = false;
  cookiesStatusMessage = '';
  cookiesInProgress = false;

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
  faUserShield = faUserShield;
  faUserPlus = faUserPlus;
  faUserSlash = faUserSlash;
  faKey = faKey;
  faRightFromBracket = faRightFromBracket;
  faPlay = faPlay;
  faWindowMinimize = faWindowMinimize;
  faWindowRestore = faWindowRestore;
  faArrowsLeftRight = faArrowsLeftRight;

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
    url = url ?? this.addUrl
    quality = quality ?? this.quality
    format = format ?? this.format
    folder = folder ?? this.folder
    customNamePrefix = customNamePrefix ?? this.customNamePrefix
    playlistStrictMode = playlistStrictMode ?? this.playlistStrictMode
    playlistItemLimit = playlistItemLimit ?? this.playlistItemLimit
    autoStart = autoStart ?? this.autoStart

    console.debug('Downloading: url='+url+' quality='+quality+' format='+format+' folder='+folder+' customNamePrefix='+customNamePrefix+' playlistStrictMode='+playlistStrictMode+' playlistItemLimit='+playlistItemLimit+' autoStart='+autoStart);
    this.addInProgress = true;
    this.downloads.add(url, quality, format, folder, customNamePrefix, playlistStrictMode, playlistItemLimit, autoStart).subscribe((status: Status) => {
      this.addInProgress = false;
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
      this.cookiesConfigured = data.has_cookies;
    });
  }

  saveCookies(): void {
    if (!this.cookiesText || !this.cookiesText.trim()) {
      alert('Please paste your cookies in the provided text area.');
      return;
    }

    this.cookiesInProgress = true;
    this.cookiesStatusMessage = '';

    this.downloads.setCookies(this.cookiesText).subscribe((status: Status) => {
      this.cookiesInProgress = false;
      if (status.status === 'error') {
        alert(`Error saving cookies: ${status.msg}`);
        return;
      }
      this.cookiesText = '';
      this.cookiesStatusMessage = 'Cookies saved successfully.';
      this.cookiesConfigured = true;
      this.refreshCookiesStatus();
    });
  }

  clearCookies(): void {
    if (!this.cookiesConfigured) {
      return;
    }

    this.cookiesInProgress = true;
    this.cookiesStatusMessage = '';

    this.downloads.clearCookies().subscribe((status: Status) => {
      this.cookiesInProgress = false;
      if (status.status === 'error') {
        alert(`Error clearing cookies: ${status.msg}`);
        return;
      }
      this.cookiesConfigured = false;
      this.cookiesStatusMessage = 'Cookies cleared.';
      this.refreshCookiesStatus();
    });
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
