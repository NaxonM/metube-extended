import { Component, OnDestroy, OnInit } from '@angular/core';
import { Subscription } from 'rxjs';
import { CookieService } from 'ngx-cookie-service';

import { faDownload, faClock, faCheck, faTimesCircle, faTachometerAlt, faSun, faMoon, faCircleHalfStroke, faRightFromBracket, faUserShield } from '@fortawesome/free-solid-svg-icons';

import { DownloadsService, CurrentUser, DownloadMetrics } from '../downloads.service';
import { Theme, Themes } from '../theme';

@Component({
    selector: 'app-dashboard',
    templateUrl: './dashboard.component.html',
    styleUrls: ['./dashboard.component.sass'],
    standalone: false
})
export class DashboardComponent implements OnInit, OnDestroy {
  readonly themes = Themes;

  activeTheme: Theme;
  currentUser: CurrentUser | null = null;
  isAdmin = false;

  ytDlpOptionsUpdateTime: string | null = null;
  ytDlpVersion: string | null = null;
  galleryDlVersion: string | null = null;
  metubeVersion: string | null = null;

  activeDownloads = 0;
  queuedDownloads = 0;
  completedDownloads = 0;
  failedDownloads = 0;
  totalSpeed = 0;

  faDownload = faDownload;
  faClock = faClock;
  faCheck = faCheck;
  faTimesCircle = faTimesCircle;
  faTachometerAlt = faTachometerAlt;
  faSun = faSun;
  faMoon = faMoon;
  faCircleHalfStroke = faCircleHalfStroke;
  faRightFromBracket = faRightFromBracket;
  faUserShield = faUserShield;

  private metricsSubscription?: Subscription;
  private themeMediaQuery?: MediaQueryList;

  constructor(public readonly downloads: DownloadsService, private readonly cookieService: CookieService) {
    this.activeTheme = this.getPreferredTheme();
  }

  ngOnInit(): void {
    this.setTheme(this.activeTheme);
    this.metricsSubscription = this.downloads.metrics$.subscribe(metrics => this.updateMetrics(metrics));
    this.themeMediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    this.themeMediaQuery.addEventListener('change', this.handleSystemThemeToggle);
  }

  ngOnDestroy(): void {
    this.metricsSubscription?.unsubscribe();
    this.themeMediaQuery?.removeEventListener('change', this.handleSystemThemeToggle);
  }

  onOptionsUpdateChange(value: string | null): void {
    this.ytDlpOptionsUpdateTime = value;
  }

  onVersionInfoChange(info: { ytdlp?: string | null; gallerydl?: string | null; metube?: string | null }): void {
    this.ytDlpVersion = info?.ytdlp ?? null;
    this.galleryDlVersion = info?.gallerydl ?? null;
    this.metubeVersion = info?.metube ?? null;
  }

  onUserChange(user: CurrentUser | null): void {
    this.currentUser = user;
    this.isAdmin = user?.role === 'admin';
  }

  onThemeSelected(theme: Theme): void {
    this.cookieService.set('metube_theme', theme.id, { expires: 3650 });
    this.setTheme(theme);
  }

  private updateMetrics(metrics: DownloadMetrics): void {
    this.activeDownloads = metrics.active;
    this.queuedDownloads = metrics.queued;
    this.completedDownloads = metrics.completed;
    this.failedDownloads = metrics.failed;
    this.totalSpeed = metrics.totalSpeed;
  }

  private getPreferredTheme(): Theme {
    const stored = this.cookieService.check('metube_theme') ? this.cookieService.get('metube_theme') : 'auto';
    return this.themes.find(t => t.id === stored) ?? this.themes.find(t => t.id === 'auto')!;
  }

  private setTheme(theme: Theme): void {
    this.activeTheme = theme;
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const value = theme.id === 'auto' ? (prefersDark ? 'dark' : 'light') : theme.id;
    document.documentElement.setAttribute('data-bs-theme', value);
  }

  private handleSystemThemeToggle = () => {
    if (this.activeTheme.id === 'auto') {
      this.setTheme(this.activeTheme);
    }
  };
}
