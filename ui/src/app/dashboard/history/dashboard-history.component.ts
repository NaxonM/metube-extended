import { Component, Input, OnInit, OnDestroy, AfterViewInit, ViewChild, ElementRef } from '@angular/core';
import { Subscription } from 'rxjs';

import { faCheckCircle, faTimesCircle, faRedoAlt, faPen, faDownload, faExternalLinkAlt, faTrashAlt, faPlay, faWindowMinimize, faWindowRestore, faArrowsLeftRight } from '@fortawesome/free-solid-svg-icons';

import { DownloadsService, Download, Status } from '../../downloads.service';
import { MasterCheckboxComponent } from '../../master-checkbox.component';
import { DashboardToolsComponent } from '../tools/dashboard-tools.component';

type HlsModule = typeof import('hls.js');
type HlsInstance = import('hls.js').default;

@Component({
    selector: 'app-dashboard-history',
    templateUrl: './dashboard-history.component.html',
    styleUrls: ['./dashboard-history.component.sass'],
    standalone: false
})
export class DashboardHistoryComponent implements OnInit, AfterViewInit, OnDestroy {
  @Input() tools?: DashboardToolsComponent;

  readonly doneDisplayLimit = 50;

  doneExpanded = false;
  visibleDoneKeys: string[] = [];
  hiddenDoneCount = 0;

  renameModalOpen = false;
  renameFormValue = '';
  renameSaving = false;
  renameError = '';
  renameTargetTitle = '';
  private renameTargetKey: string | null = null;
  private renameOriginalName = '';

  deleteModalOpen = false;
  deleteWorking = false;
  deleteError = '';
  deleteTargetTitle = '';
  deleteTargetFilename = '';
  deleteTargetSize: number | null = null;
  private deleteTargetKey: string | null = null;

  streamModalOpen = false;
  streamSource: string | null = null;
  streamFallbackSource: string | null = null;
  streamHlsSource: string | null = null;
  streamMimeType = '';
  streamTitle = '';
  streamType: 'audio' | 'video' = 'video';
  streamFilename = '';
  streamFilesize: number | null = null;
  streamLoading = false;
  streamError = '';
  streamMinimized = false;
  streamDockSide: 'left' | 'right' = 'right';

  faCheckCircle = faCheckCircle;
  faTimesCircle = faTimesCircle;
  faRedoAlt = faRedoAlt;
  faPen = faPen;
  faDownload = faDownload;
  faExternalLinkAlt = faExternalLinkAlt;
  faTrashAlt = faTrashAlt;
  faPlay = faPlay;
  faWindowMinimize = faWindowMinimize;
  faWindowRestore = faWindowRestore;
  faArrowsLeftRight = faArrowsLeftRight;

  @ViewChild('doneMasterCheckbox') doneMasterCheckbox!: MasterCheckboxComponent;
  @ViewChild('doneDelSelected') doneDelSelected!: ElementRef<HTMLButtonElement>;
  @ViewChild('doneClearCompleted') doneClearCompleted!: ElementRef<HTMLButtonElement>;
  @ViewChild('doneClearFailed') doneClearFailed!: ElementRef<HTMLButtonElement>;
  @ViewChild('doneRetryFailed') doneRetryFailed!: ElementRef<HTMLButtonElement>;
  @ViewChild('doneDownloadSelected') doneDownloadSelected!: ElementRef<HTMLButtonElement>;
  @ViewChild('renameInput') renameInput?: ElementRef<HTMLInputElement>;
  @ViewChild('streamVideo') streamVideo?: ElementRef<HTMLVideoElement>;
  @ViewChild('streamAudio') streamAudio?: ElementRef<HTMLAudioElement>;

  private doneSubscription?: Subscription;
  private hlsModule?: HlsModule;
  private hlsInstance: HlsInstance | null = null;

  constructor(public readonly downloads: DownloadsService) {}

  ngOnInit(): void {
    this.refreshDoneView();
    this.doneSubscription = this.downloads.doneChanged.subscribe(() => {
      this.refreshDoneView();
      if (this.doneMasterCheckbox) {
        this.doneMasterCheckbox.selectionChanged();
      }
      this.updateBulkButtons();
    });
  }

  ngAfterViewInit(): void {
    this.updateBulkButtons();
  }

  ngOnDestroy(): void {
    this.doneSubscription?.unsubscribe();
    this.destroyHlsInstance();
  }

  trackByKey(index: number, key: string): string {
    return key;
  }

  doneSelectionChanged(checked: number): void {
    if (this.doneDelSelected) {
      this.doneDelSelected.nativeElement.disabled = checked === 0;
    }
    if (this.doneDownloadSelected) {
      this.doneDownloadSelected.nativeElement.disabled = checked === 0;
    }
  }

  showAllDone(): void {
    if (this.doneExpanded) {
      return;
    }
    this.doneExpanded = true;
    this.refreshDoneView();
  }

  showLessDone(): void {
    if (!this.doneExpanded) {
      return;
    }
    this.doneExpanded = false;
    this.refreshDoneView();
  }

  openDeleteModal(id: string, download: Download): void {
    this.deleteTargetKey = id;
    this.deleteTargetTitle = download.title || download.filename || 'Selected download';
    this.deleteTargetFilename = download.filename || '';
    this.deleteTargetSize = typeof download.size === 'number' ? download.size : null;
    this.deleteError = '';
    this.deleteWorking = false;
    this.deleteModalOpen = true;
  }

  closeDeleteModal(): void {
    if (this.deleteWorking) {
      return;
    }
    this.deleteModalOpen = false;
    this.deleteError = '';
    this.deleteTargetKey = null;
    this.deleteTargetFilename = '';
    this.deleteTargetTitle = '';
    this.deleteTargetSize = null;
  }

  confirmDelete(): void {
    if (!this.deleteTargetKey || this.deleteWorking) {
      return;
    }
    this.deleteWorking = true;
    this.deleteError = '';
    this.downloads.delById('done', [this.deleteTargetKey]).subscribe({
      next: () => {
        this.deleteWorking = false;
        this.closeDeleteModal();
      },
      error: (error: unknown) => {
        this.deleteWorking = false;
        if (error && typeof error === 'object' && 'error' in error) {
          const payload = (error as { error?: { msg?: string } }).error;
          this.deleteError = payload?.msg || 'Unable to delete download. Please try again.';
        } else {
          this.deleteError = 'Unable to delete download. Please try again.';
        }
      },
    });
  }

  clearCompletedDownloads(): void {
    this.downloads.delByFilter('done', dl => dl.status === 'finished').subscribe();
  }

  clearFailedDownloads(): void {
    this.downloads.delByFilter('done', dl => dl.status === 'error').subscribe();
  }

  retryFailedDownloads(): void {
    this.downloads.done.forEach((dl, key) => {
      if (dl.status === 'error') {
        this.retryDownload(key, dl);
      }
    });
  }

  downloadSelectedFiles(): void {
    this.downloads.done.forEach((dl, key) => {
      if (dl.status === 'finished' && dl.checked) {
        const link = document.createElement('a');
        const href = this.buildDownloadLink(dl);
        if (!href) {
          return;
        }
        link.href = href;
        link.setAttribute('download', dl.filename || dl.title || 'download');
        link.setAttribute('target', '_self');
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
      }
    });
  }

  clearSelectedDownloads(): void {
    this.downloads.delByFilter('done', dl => dl.checked).subscribe();
  }

  retryDownload(key: string, download: Download): void {
    this.tools?.addDownload(download.url, download.quality, download.format, download.folder, download.custom_name_prefix, download.playlist_strict_mode, download.playlist_item_limit, true);
    this.downloads.delById('done', [key]).subscribe();
  }

  renameDownload(key: string, download: Download): void {
    this.renameTargetKey = key;
    this.renameOriginalName = download.filename || '';
    this.renameFormValue = download.filename || download.title || '';
    this.renameTargetTitle = download.title || download.filename || '';
    this.renameError = '';
    this.renameSaving = false;
    this.renameModalOpen = true;

    setTimeout(() => {
      const input = this.renameInput?.nativeElement;
      if (input) {
        input.focus();
        input.select();
      }
    }, 10);
  }

  submitRename(event?: Event): void {
    event?.preventDefault();
    if (!this.renameTargetKey) {
      this.closeRenameModal();
      return;
    }

    const trimmed = (this.renameFormValue || '').trim();
    if (!trimmed || trimmed === this.renameOriginalName) {
      this.closeRenameModal();
      return;
    }

    this.renameSaving = true;
    this.renameError = '';

    this.downloads.rename(this.renameTargetKey, trimmed).subscribe({
      next: (status: Status) => {
        if (status.status === 'error') {
          this.renameError = status.msg || 'Unable to rename file.';
          this.renameSaving = false;
          return;
        }
        this.closeRenameModal();
      },
      error: () => {
        this.renameError = 'Unable to rename file.';
        this.renameSaving = false;
      }
    });
  }

  closeRenameModal(): void {
    this.renameModalOpen = false;
    this.renameSaving = false;
    this.renameError = '';
    this.renameFormValue = '';
    this.renameTargetTitle = '';
    this.renameTargetKey = null;
    this.renameOriginalName = '';
  }

  buildDownloadTooltip(download: Download): string {
    const segments: string[] = [];
    if (download.msg) {
      segments.push(download.msg);
    }
    if (download.error) {
      segments.push(`Error: ${download.error}`);
    }
    return segments.join(' • ');
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
    this.streamFilename = download.filename || '';
    this.streamFilesize = typeof download.size === 'number' ? download.size : null;
    this.streamFallbackSource = this.buildStreamFallbackLink(key);
    this.streamHlsSource = this.buildHlsLink(key);
    this.streamSource = null;
    this.streamLoading = true;
    this.streamError = '';
    this.streamModalOpen = true;
    this.streamMinimized = false;
    this.streamDockSide = 'right';

    setTimeout(() => {
      if (this.streamType === 'audio') {
        this.initializeAudioStream();
      } else {
        this.initializeVideoStream();
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
    this.destroyHlsInstance();
    this.streamModalOpen = false;
    this.streamSource = null;
    this.streamFallbackSource = null;
    this.streamHlsSource = null;
    this.streamTitle = '';
    this.streamMimeType = '';
    this.streamType = 'video';
    this.streamMinimized = false;
    this.streamFilename = '';
    this.streamFilesize = null;
    this.streamLoading = false;
    this.streamError = '';
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

  buildDownloadLink(download: Download): string {
    const filename = download.filename || '';
    if (!filename) {
      return '';
    }

    let baseDir = this.downloads.configuration['PUBLIC_HOST_URL'] || '';
    if (download.quality === 'audio' || filename.toLowerCase().endsWith('.mp3')) {
      baseDir = this.downloads.configuration['PUBLIC_HOST_AUDIO_URL'] || baseDir;
    }

    if (download.folder) {
      baseDir += `${download.folder}/`;
    }

    return baseDir + encodeURIComponent(filename);
  }

  private refreshDoneView(): void {
    const keys = Array.from(this.downloads.done.keys()).reverse();
    this.visibleDoneKeys = this.doneExpanded ? keys : keys.slice(0, this.doneDisplayLimit);
    this.hiddenDoneCount = Math.max(keys.length - this.visibleDoneKeys.length, 0);
  }

  private updateBulkButtons(): void {
    if (!this.doneDelSelected || !this.doneClearCompleted || !this.doneClearFailed || !this.doneRetryFailed || !this.doneDownloadSelected) {
      return;
    }
    let completed = 0;
    let failed = 0;
    let selected = 0;
    this.downloads.done.forEach(dl => {
      if (dl.status === 'finished') {
        completed++;
      } else if (dl.status === 'error') {
        failed++;
      }
      if (dl.checked) {
        selected++;
      }
    });

    this.doneClearCompleted.nativeElement.disabled = completed === 0;
    this.doneClearFailed.nativeElement.disabled = failed === 0;
    this.doneRetryFailed.nativeElement.disabled = failed === 0;
    this.doneSelectionChanged(selected);
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
    return this.buildStreamFallbackLink(id);
  }

  private buildStreamFallbackLink(id: string): string {
    const encoded = encodeURIComponent(id);
    const relative = `stream?id=${encoded}`;
    return this.downloads.buildApiUrl(relative);
  }

  private buildHlsLink(id: string): string {
    const token = this.encodeStreamToken(id);
    const relative = `stream/hls/${token}/index.m3u8`;
    return this.downloads.buildApiUrl(relative);
  }

  private encodeStreamToken(value: string): string {
    const utf8 = encodeURIComponent(value).replace(/%([0-9A-F]{2})/g, (_, hex) => String.fromCharCode(parseInt(hex, 16)));
    return btoa(utf8)
      .replace(/=+$/, '')
      .replace(/\+/g, '-')
      .replace(/\//g, '_');
  }

  private async initializeVideoStream(): Promise<void> {
    const videoEl = this.streamVideo?.nativeElement;
    if (!videoEl) {
      this.streamLoading = false;
      return;
    }

    const hlsSource = this.streamHlsSource;
    const fallbackSource = this.streamFallbackSource;

    if (!hlsSource || !fallbackSource) {
      this.streamLoading = false;
      return;
    }

    this.destroyHlsInstance();
    this.streamSource = null;

    if (!this.downloads.isAdaptiveStreamingEnabled()) {
      const message = this.downloads.getAdaptiveStreamingMessage();
      if (message) {
        this.downloads.markAdaptiveStreamingUnavailable(message);
      } else {
        this.downloads.markAdaptiveStreamingUnavailable();
      }
      this.streamError = message ? `${message} Playing original file.` : 'Adaptive streaming is unavailable. Playing original file.';
      this.startFallbackVideoPlayback(videoEl, fallbackSource);
      return;
    }

    if (videoEl.canPlayType('application/vnd.apple.mpegurl')) {
      this.streamSource = hlsSource;
      this.attachVideoListeners(videoEl, fallbackSource);
      videoEl.src = hlsSource;
      videoEl.load();
      return;
    }

    try {
      const module = await this.loadHlsModule();
      if (!module) {
        throw new Error('Unable to load hls.js');
      }
      const { default: Hls } = module;
      if (!Hls.isSupported()) {
        throw new Error('hls.js is not supported in this browser');
      }

      const instance = new Hls({ enableWorker: true });
      this.hlsInstance = instance;
      this.attachVideoListeners(videoEl, fallbackSource);

      instance.attachMedia(videoEl);
      instance.on(Hls.Events.MEDIA_ATTACHED, () => {
        instance.loadSource(hlsSource);
      });
      instance.on(Hls.Events.MANIFEST_PARSED, () => {
        this.streamLoading = false;
        videoEl.play().catch(() => undefined);
      });
      instance.on(Hls.Events.ERROR, (_event: unknown, data: any) => {
        if (!data?.fatal) {
          return;
        }
        const status = typeof data?.response?.code === 'number' ? data.response.code : undefined;
        const text = typeof data?.response?.text === 'string' ? data.response.text : undefined;
        this.streamError = this.buildAdaptiveError(status, text, true);
        this.startFallbackVideoPlayback(videoEl, fallbackSource);
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : undefined;
      this.streamError = this.buildAdaptiveError(undefined, message, true);
      this.startFallbackVideoPlayback(videoEl, fallbackSource);
    }
  }

  private initializeAudioStream(): void {
    const audioEl = this.streamAudio?.nativeElement;
    const fallbackSource = this.streamFallbackSource;
    if (!audioEl || !fallbackSource) {
      this.streamLoading = false;
      return;
    }
    const onReady = () => {
      this.streamLoading = false;
      audioEl.play().catch(() => undefined);
    };
    const onError = () => {
      this.streamLoading = false;
      if (!this.streamError) {
        this.streamError = this.buildAdaptiveError(undefined, 'Unable to load audio stream. Please download the file instead.');
      }
    };
    audioEl.addEventListener('canplay', onReady, { once: true });
    audioEl.addEventListener('error', onError, { once: true });
    this.streamSource = fallbackSource;
    audioEl.src = fallbackSource;
    audioEl.load();
  }

  private attachVideoListeners(videoEl: HTMLVideoElement, fallbackSource: string): void {
    const onLoaded = () => {
      this.streamLoading = false;
      videoEl.play().catch(() => undefined);
    };
    const onError = () => {
      if (!this.streamError) {
        const mediaMessage = videoEl.error?.message || undefined;
        this.streamError = this.buildAdaptiveError(undefined, mediaMessage, true);
      }
      this.startFallbackVideoPlayback(videoEl, fallbackSource);
    };

    videoEl.addEventListener('loadedmetadata', onLoaded, { once: true });
    videoEl.addEventListener('error', onError, { once: true });
  }

  private startFallbackVideoPlayback(videoEl: HTMLVideoElement, fallback: string): void {
    this.destroyHlsInstance();
    this.streamSource = fallback;
    this.streamLoading = false;
    videoEl.src = fallback;
    videoEl.load();
    videoEl.play().catch(() => undefined);
  }

  private async loadHlsModule(): Promise<HlsModule | null> {
    if (this.hlsModule) {
      return this.hlsModule;
    }
    try {
      const module = await import('hls.js');
      this.hlsModule = module;
      return module;
    } catch {
      return null;
    }
  }

  private destroyHlsInstance(): void {
    if (!this.hlsInstance) {
      return;
    }
    try {
      this.hlsInstance.destroy();
    } catch {
      this.hlsInstance = null;
      return;
    }
    this.hlsInstance = null;
  }

  private buildAdaptiveError(status?: number, text?: string, includeFallbackNote: boolean = false): string {
    const message = this.formatAdaptiveError(status, text);
    const normalized = message.toLowerCase();
    if (status === 404 || normalized.includes('adaptive streaming is')) {
      this.downloads.markAdaptiveStreamingUnavailable(message);
    }
    return includeFallbackNote ? `${message} Falling back to original file.` : message;
  }

  private formatAdaptiveError(status?: number, text?: string): string {
    const trimmed = text?.toString().trim();
    if (trimmed) {
      return trimmed;
    }
    if (status) {
      return `Adaptive streaming failed (HTTP ${status}).`;
    }
    return 'Adaptive streaming is unavailable.';
  }

}
