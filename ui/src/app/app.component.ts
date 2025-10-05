import { Component, ViewChild, ElementRef, AfterViewInit, OnInit, ChangeDetectorRef } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { faTrashAlt, faCheckCircle, faTimesCircle, IconDefinition } from '@fortawesome/free-regular-svg-icons';
import { faRedoAlt, faSun, faMoon, faCircleHalfStroke, faCheck, faExternalLinkAlt, faDownload, faFileImport, faFileExport, faCopy, faClock, faTachometerAlt, faPen, faCookieBite, faUserShield, faUserPlus, faUserSlash, faKey, faRightFromBracket, faPlay } from '@fortawesome/free-solid-svg-icons';
import { faGithub } from '@fortawesome/free-brands-svg-icons';
import { CookieService } from 'ngx-cookie-service';

import { Download, DownloadsService, Status, CurrentUser, ManagedUser } from './downloads.service';
import { MasterCheckboxComponent } from './master-checkbox.component';
import { Formats, Format, Quality } from './formats';
import { Theme, Themes } from './theme';
import {KeyValue} from "@angular/common";

type QueueFilter = 'all' | 'active' | 'pending';
type CompletedFilter = 'all' | 'finished' | 'error';
type CompletedSort = 'recent' | 'largest' | 'status';

interface ToastMessage {
  id: number;
  type: 'success' | 'info' | 'warning' | 'danger';
  text: string;
}

@Component({
    selector: 'app-root',
    templateUrl: './app.component.html',
    styleUrls: ['./app.component.sass'],
    standalone: false
})
export class AppComponent implements AfterViewInit, OnInit {
  addUrl: string;
  formats: Format[] = Formats;
  qualities: Quality[];
  quality: string;
  format: string;
  customNamePrefix: string;
  autoStart: boolean;
  playlistStrictMode: boolean;
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
  adminUsers: ManagedUser[] = [];
  adminLoading = false;
  adminError = '';

  // Download metrics
  activeDownloads = 0;
  queuedDownloads = 0;
  completedDownloads = 0;
  failedDownloads = 0;
  totalSpeed = 0;

  @ViewChild('queueMasterCheckbox') queueMasterCheckbox: MasterCheckboxComponent;
  @ViewChild('doneMasterCheckbox') doneMasterCheckbox: MasterCheckboxComponent;
  @ViewChild('mediaPlayer') mediaPlayer?: ElementRef<HTMLMediaElement>;

  faTrashAlt = faTrashAlt;
  faCheckCircle = faCheckCircle;
  faTimesCircle = faTimesCircle;
  faRedoAlt = faRedoAlt;
  faSun = faSun;
  faMoon = faMoon;
  faCheck = faCheck;
  faCircleHalfStroke = faCircleHalfStroke;
  faDownload = faDownload;
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

  streamModalOpen = false;
  streamMode: 'video' | 'audio' = 'video';
  streamDownload: Download | null = null;
  streamUrl: string | null = null;

  private readonly streamableVideoExtensions = ['.mp4', '.webm'];
  private readonly streamableAudioExtensions = ['.mp3', '.ogg', '.wav'];

  queueFilter: QueueFilter = 'all';
  completedFilter: CompletedFilter = 'all';
  completedSort: CompletedSort = 'recent';
  queueSelectionCount = 0;
  doneSelectionCount = 0;
  hasCompletedDownloads = false;
  hasFailedDownloads = false;
  toasts: ToastMessage[] = [];
  readonly loadingPlaceholders = [0, 1, 2];
  filteredQueue: Array<{ key: string; value: Download }> = [];
  filteredCompleted: Array<{ key: string; value: Download }> = [];

  private toastCounter = 0;

  constructor(public downloads: DownloadsService, private cookieService: CookieService, private http: HttpClient, private cdr: ChangeDetectorRef) {
    this.format = cookieService.get('metube_format') || 'any';
    // Needs to be set or qualities won't automatically be set
    this.setQualities()
    this.quality = cookieService.get('metube_quality') || 'best';
    this.autoStart = cookieService.get('metube_auto_start') !== 'false';

    this.activeTheme = this.getPreferredTheme(cookieService);

    // Subscribe to download updates
    this.downloads.queueChanged.subscribe(() => {
      this.updateMetrics();
      if (this.queueMasterCheckbox) {
        this.queueMasterCheckbox.selectionChanged();
      }
      this.queueSelectionCount = 0;
      this.cdr.detectChanges();
    });
    this.downloads.doneChanged.subscribe(() => {
      this.updateMetrics();
      if (this.doneMasterCheckbox) {
        this.doneMasterCheckbox.selectionChanged();
      }
      this.doneSelectionCount = 0;
      this.cdr.detectChanges();
    });
    // Subscribe to real-time updates
    this.downloads.updated.subscribe(() => {
      this.updateMetrics();
      this.cdr.detectChanges();
    });
    this.refreshQueueEntries();
    this.refreshCompletedEntries();
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
    this.fetchVersionInfo();
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
          this.showToast('danger', `Error reloading yt-dlp options: ${data['msg']}`);
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

  queueSelectionChanged(checked: number) {
    this.queueSelectionCount = checked;
  }

  doneSelectionChanged(checked: number) {
    this.doneSelectionCount = checked;
  }

  setQualities() {
    // qualities for specific format
    this.qualities = this.formats.find(el => el.id == this.format).qualities
    const exists = this.qualities.find(el => el.id === this.quality)
    this.quality = exists ? this.quality : 'best'
  }

  setQueueFilter(filter: QueueFilter) {
    this.queueFilter = filter;
    this.refreshQueueEntries();
  }

  setCompletedFilter(filter: CompletedFilter) {
    this.completedFilter = filter;
    this.refreshCompletedEntries();
  }

  getFilteredQueue(): Array<{ key: string; value: Download }> {
    return this.filteredQueue;
  }

  setCompletedSort(sort: CompletedSort) {
    this.completedSort = sort;
    this.refreshCompletedEntries();
  }

  getFilteredCompleted(): Array<{ key: string; value: Download }> {
    return this.filteredCompleted;
  }

  trackDownloadEntry(index: number, entry: { key: string; value: Download }) {
    return entry.value.id;
  }

  addDownload(url?: string, quality?: string, format?: string, folder?: string, customNamePrefix?: string, playlistStrictMode?: boolean, playlistItemLimit?: number, autoStart?: boolean) {
    url = (url ?? this.addUrl ?? '').trim();
    if (!url) {
      return;
    }
    if (!this.cookiesConfigured && this.isYoutubeUrl(url)) {
      this.showToast('warning', 'Downloading from YouTube requires cookies. Please configure your YouTube cookies before trying again.');
      return;
    }

    quality = quality ?? this.quality
    format = format ?? this.format
    folder = folder ?? ''
    customNamePrefix = customNamePrefix ?? this.customNamePrefix
    playlistStrictMode = playlistStrictMode ?? this.playlistStrictMode
    playlistItemLimit = playlistItemLimit ?? this.playlistItemLimit
    autoStart = autoStart ?? this.autoStart

    console.debug('Downloading: url='+url+' quality='+quality+' format='+format+' folder='+folder+' customNamePrefix='+customNamePrefix+' playlistStrictMode='+playlistStrictMode+' playlistItemLimit='+playlistItemLimit+' autoStart='+autoStart);
    this.addInProgress = true;
    this.downloads.add(url, quality, format, folder, customNamePrefix, playlistStrictMode, playlistItemLimit, autoStart).subscribe((status: Status) => {
      if (status.status === 'error') {
        this.showToast('danger', `Error adding URL: ${status.msg}`);
      } else {
        this.addUrl = '';
        this.showToast('success', 'Download queued successfully.');
      }
      this.addInProgress = false;
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

  canStream(download: Download): boolean {
    if (!download || !download.filename || download.status !== 'finished') {
      return false;
    }
    const lower = download.filename.toLowerCase();
    return this.streamableVideoExtensions.some(ext => lower.endsWith(ext)) || this.streamableAudioExtensions.some(ext => lower.endsWith(ext));
  }

  openStream(download: Download) {
    if (!this.canStream(download)) {
      return;
    }
    const mode = this.getStreamMode(download.filename);
    if (!mode) {
      return;
    }
    this.streamMode = mode;
    this.streamDownload = download;
    this.streamUrl = this.buildDownloadLink(download);
    this.streamModalOpen = true;
    setTimeout(() => {
      const player = this.mediaPlayer?.nativeElement;
      if (player) {
        player.load();
      }
    });
  }

  closeStream() {
    const player = this.mediaPlayer?.nativeElement;
    if (player) {
      player.pause();
      player.removeAttribute('src');
      player.load();
    }
    this.streamModalOpen = false;
    this.streamDownload = null;
    this.streamUrl = null;
  }

  private getStreamMode(filename: string | null | undefined): 'video' | 'audio' | null {
    if (!filename) {
      return null;
    }
    const lower = filename.toLowerCase();
    if (this.streamableVideoExtensions.some(ext => lower.endsWith(ext))) {
      return 'video';
    }
    if (this.streamableAudioExtensions.some(ext => lower.endsWith(ext))) {
      return 'audio';
    }
    return null;
  }

  showToast(type: ToastMessage['type'], text: string, duration = 4000) {
    const id = ++this.toastCounter;
    this.toasts = [...this.toasts, { id, type, text }];
    if (duration > 0) {
      setTimeout(() => this.dismissToast(id), duration);
    }
  }

  dismissToast(id: number) {
    this.toasts = this.toasts.filter(toast => toast.id !== id);
  }

  private isYoutubeUrl(url: string): boolean {
    const lower = url.toLowerCase();
    return lower.includes('youtube.com') || lower.includes('youtu.be');
  }

  renameDownload(key: string, download: Download) {
    const currentName = download.filename;
    const newName = prompt('Enter new filename', currentName);
    if (!newName || newName === currentName) {
      return;
    }

    this.downloads.rename(key, newName).subscribe((status: Status) => {
      if (status.status === 'error') {
        this.showToast('danger', `Error renaming file: ${status.msg}`);
      }
    });
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
      this.showToast('warning', 'Please paste your cookies in the provided text area.');
      return;
    }

    this.cookiesInProgress = true;
    this.cookiesStatusMessage = '';

    this.downloads.setCookies(this.cookiesText).subscribe((status: Status) => {
      this.cookiesInProgress = false;
      if (status.status === 'error') {
        this.showToast('danger', `Error saving cookies: ${status.msg}`);
        return;
      }
      this.cookiesText = '';
      this.cookiesStatusMessage = 'Cookies saved successfully.';
      this.cookiesConfigured = true;
      this.showToast('success', 'Cookies saved successfully.');
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
        this.showToast('danger', `Error clearing cookies: ${status.msg}`);
        return;
      }
      this.cookiesConfigured = false;
      this.cookiesStatusMessage = 'Cookies cleared.';
      this.showToast('info', 'Cookies cleared.');
      this.refreshCookiesStatus();
    });
  }

  loadCurrentUser(): void {
    this.downloads.getCurrentUser().subscribe(user => {
      this.currentUser = user;
      this.isAdmin = !!user && user.role === 'admin';
      if (this.isAdmin) {
        this.refreshUsers();
      } else {
        this.adminUsers = [];
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

  promptCreateUser(): void {
    const username = (prompt('Enter a username for the new account') || '').trim();
    if (!username) {
      return;
    }
    const password = prompt(`Enter a password for ${username}`) || '';
    if (!password) {
      this.showToast('warning', 'Password is required.');
      return;
    }
    const makeAdmin = confirm('Should this user have administrator access?');
    this.downloads.createUser(username, password, makeAdmin ? 'admin' : 'user').subscribe(result => {
      if ((result as any)?.status === 'error') {
        this.showToast('danger', (result as any).msg || 'Failed to create user.');
        return;
      }
      this.showToast('success', 'User created successfully.');
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
        this.showToast('danger', (result as any).msg || 'Failed to update role.');
        return;
      }
      this.showToast('success', 'User role updated.');
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
        this.showToast('danger', (result as any).msg || 'Failed to update status.');
        return;
      }
      this.showToast('success', `User ${nextState ? 'disabled' : 'enabled'} successfully.`);
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
        this.showToast('danger', (result as any).msg || 'Failed to reset password.');
        return;
      }
      this.showToast('success', 'Password updated successfully.');
    });
  }

  deleteUser(user: ManagedUser): void {
    if (!confirm(`Delete user ${user.username}? This action cannot be undone.`)) {
      return;
    }
    this.downloads.deleteUser(user.id).subscribe(result => {
      if ((result as any)?.status === 'error') {
        this.showToast('danger', (result as any).msg || 'Failed to delete user.');
        return;
      }
      this.showToast('success', 'User deleted successfully.');
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
      this.showToast('warning', 'No valid URLs found.');
      return;
    }
    if (!this.cookiesConfigured && urls.some(url => this.isYoutubeUrl(url))) {
      this.batchImportStatus = 'YouTube downloads require cookies. Please configure your YouTube cookies before importing.';
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
        this.showToast('info', `Import cancelled after ${index} URL${index === 1 ? '' : 's'}.`);
        return;
      }
      if (index >= urls.length) {
        this.batchImportStatus = `Finished importing ${urls.length} URLs.`;
        this.importInProgress = false;
        this.showToast('success', `Finished importing ${urls.length} URL${urls.length === 1 ? '' : 's'}.`);
        return;
      }
      const url = urls[index];
      this.batchImportStatus = `Importing URL ${index + 1} of ${urls.length}: ${url}`;
      // Pass the selected options through to the add() method
      this.downloads.add(url, this.quality, this.format, '', this.customNamePrefix,
        this.playlistStrictMode, this.playlistItemLimit, this.autoStart)
        .subscribe({
          next: (status: Status) => {
            if (status.status === 'error') {
              this.showToast('danger', `Error adding URL ${url}: ${status.msg}`);
            }
            index++;
            setTimeout(processNext, delayBetween);
          },
          error: (err) => {
            console.error(`Error importing URL ${url}:`, err);
            this.showToast('danger', `Error importing URL ${url}. Check logs for details.`);
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
      this.showToast('info', 'No URLs found for the selected filter.');
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
      this.showToast('info', 'No URLs found for the selected filter.');
      return;
    }
    const content = urls.join('\n');
    navigator.clipboard.writeText(content)
      .then(() => this.showToast('success', 'URLs copied to clipboard.'))
      .catch(() => this.showToast('danger', 'Failed to copy URLs.'));
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

  getProgressValue(download: Download | undefined): number {
    if (!download) {
      return 0;
    }
    if (download.status === 'preparing') {
      return 100;
    }
    const percent = download.percent;
    if (typeof percent !== 'number' || !isFinite(percent)) {
      return 0;
    }
    return Math.max(0, Math.min(100, Math.round(percent)));
  }

  getDownloadTitle(download: Download | undefined): string {
    if (!download) {
      return 'Unknown download';
    }
    const title = (download.title || '').trim();
    if (title) {
      return title;
    }
    const filename = (download.filename || '').trim();
    if (filename) {
      return filename;
    }
    return download.url || download.id || 'Unknown download';
  }

  private updateMetrics() {
    this.activeDownloads = Array.from(this.downloads.queue.values()).filter(d => d.status === 'downloading' || d.status === 'preparing').length;
    this.queuedDownloads = Array.from(this.downloads.queue.values()).filter(d => d.status === 'pending').length;
    this.completedDownloads = Array.from(this.downloads.done.values()).filter(d => d.status === 'finished').length;
    this.failedDownloads = Array.from(this.downloads.done.values()).filter(d => d.status === 'error').length;
    this.hasCompletedDownloads = this.completedDownloads > 0;
    this.hasFailedDownloads = this.failedDownloads > 0;

    // Calculate total speed from downloading items
    const downloadingItems = Array.from(this.downloads.queue.values())
      .filter(d => d.status === 'downloading');

    this.totalSpeed = downloadingItems.reduce((total, item) => total + (item.speed || 0), 0);
    this.refreshQueueEntries();
    this.refreshCompletedEntries();
  }

  private refreshQueueEntries() {
    const entries = Array.from(this.downloads.queue.entries()).filter(([, download]) => !!download);
    let filtered = entries;
    if (this.queueFilter === 'active') {
      filtered = entries.filter(([, download]) => download.status === 'downloading' || download.status === 'preparing');
    } else if (this.queueFilter === 'pending') {
      filtered = entries.filter(([, download]) => download.status === 'pending');
    }
    this.filteredQueue = filtered.map(([key, value]) => ({ key, value }));
  }

  private refreshCompletedEntries() {
    const entries = Array.from(this.downloads.done.entries()).filter(([, download]) => !!download);
    let filtered = entries;
    if (this.completedFilter === 'finished') {
      filtered = entries.filter(([, download]) => download.status === 'finished');
    } else if (this.completedFilter === 'error') {
      filtered = entries.filter(([, download]) => download.status === 'error');
    }

    const mapped = filtered.map(([key, value]) => ({ key, value }));

    if (this.completedSort === 'largest') {
      this.filteredCompleted = mapped
        .slice()
        .sort((a, b) => {
          const sizeA = a.value.size ?? -1;
          const sizeB = b.value.size ?? -1;
          return sizeB - sizeA;
        });
      return;
    }

    if (this.completedSort === 'status') {
      const rank = (download: Download) => {
        if (download.status === 'error') {
          return 0;
        }
        if (download.status === 'finished') {
          return 1;
        }
        return 2;
      };
      this.filteredCompleted = mapped
        .slice()
        .sort((a, b) => {
          const diff = rank(a.value) - rank(b.value);
          if (diff !== 0) {
            return diff;
          }
          return (b.value.size ?? 0) - (a.value.size ?? 0);
        });
      return;
    }

    this.filteredCompleted = mapped
      .slice()
      .sort((a, b) => {
        const timestampA = typeof a.value.timestamp === 'number' ? a.value.timestamp : 0;
        const timestampB = typeof b.value.timestamp === 'number' ? b.value.timestamp : 0;
        if (timestampA === timestampB) {
          return (b.value.size ?? 0) - (a.value.size ?? 0);
        }
        return timestampB - timestampA;
      });
  }
}
