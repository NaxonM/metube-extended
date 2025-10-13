import { Component, OnInit } from '@angular/core';

import { DownloadsService, ProxySettings } from '../../downloads.service';

@Component({
  selector: 'app-admin-proxy',
  templateUrl: './admin-proxy.component.html',
  styleUrls: ['./admin-proxy.component.sass'],
  standalone: false
})
export class AdminProxyComponent implements OnInit {
  proxySettingsLoading = false;
  proxySettingsSaving = false;
  proxySettingsError = '';
  proxyLimitEnabled = false;
  proxyLimitMb = 0;
  proxySettingsDirty = false;
  private proxySettingsSnapshot: ProxySettings | null = null;

  constructor(private readonly downloads: DownloadsService) {}

  ngOnInit(): void {
    this.refreshProxySettings();
  }

  refreshProxySettings(): void {
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
    if (this.proxySettingsSaving || !this.proxySettingsDirty) {
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

  private normalizeProxyLimitMb(value: any): number {
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric < 0) {
      return 0;
    }
    return Math.floor(numeric);
  }
}
