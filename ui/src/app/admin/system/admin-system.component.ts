import { Component, OnDestroy, OnInit } from '@angular/core';

import { DownloadsService, SystemStats, ResourceLimits } from '../../downloads.service';

@Component({
  selector: 'app-admin-system',
  templateUrl: './admin-system.component.html',
  styleUrls: ['./admin-system.component.sass'],
  standalone: false
})
export class AdminSystemComponent implements OnInit, OnDestroy {
  systemStats: SystemStats | null = null;
  systemStatsError = '';
  systemStatsLoading = false;
  systemStatsRates = { sentPerSec: 0, recvPerSec: 0 };
  private previousSystemStats: SystemStats | null = null;
  private systemStatsIntervalId: number | null = null;
  private systemStatsRequestActive = false;

  resourceLimits: ResourceLimits | null = null;
  editLimits: Partial<ResourceLimits> = {};
  savingLimits = false;
  restarting = false;
  limitsMessage = '';

  constructor(private readonly downloads: DownloadsService) {}

  fetchResourceLimits(): void {
    this.downloads.getResourceLimits().subscribe(result => {
      if ((result as any).status === 'error') {
        this.limitsMessage = (result as any).msg || 'Unable to load resource limits.';
        return;
      }
      this.resourceLimits = result;
      this.editLimits = { ...this.resourceLimits };
      this.limitsMessage = '';
    }, () => {
      this.limitsMessage = 'Unable to load resource limits.';
    });
  }

  saveResourceLimits(): void {
    this.savingLimits = true;
    this.limitsMessage = '';
    this.downloads.updateResourceLimits(this.editLimits).subscribe(result => {
      this.savingLimits = false;
      if ((result as any).status === 'error') {
        this.limitsMessage = (result as any).msg || 'Unable to save resource limits.';
        return;
      }
      this.resourceLimits = result;
      this.editLimits = { ...this.resourceLimits };
      this.limitsMessage = 'Limits saved successfully. Restart may be required.';
    }, () => {
      this.savingLimits = false;
      this.limitsMessage = 'Unable to save resource limits.';
    });
  }

  restartSystem(): void {
    if (!confirm('Are you sure you want to restart the system?')) {
      return;
    }
    this.restarting = true;
    this.limitsMessage = '';
    this.downloads.restartSystem().subscribe(result => {
      this.restarting = false;
      if (result.status === 'error') {
        this.limitsMessage = result.msg || 'Unable to restart system.';
      } else {
        this.limitsMessage = 'System restarting...';
        // The page will reload after restart
      }
    }, () => {
      this.restarting = false;
      this.limitsMessage = 'Unable to restart system.';
    });
  }

  ngOnInit(): void {
    this.fetchSystemStats(true);
    this.fetchResourceLimits();
    this.systemStatsIntervalId = window.setInterval(() => this.fetchSystemStats(), 5000);
  }

  ngOnDestroy(): void {
    if (this.systemStatsIntervalId !== null) {
      window.clearInterval(this.systemStatsIntervalId);
      this.systemStatsIntervalId = null;
    }
  }

  refreshSystemStats(): void {
    this.fetchSystemStats(true);
  }

  formatBytes(bytes: number | null | undefined): string {
    const value = Number(bytes);
    if (!Number.isFinite(value) || value <= 0) {
      return '0 B';
    }
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const exponent = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
    const sized = value / Math.pow(1024, exponent);
    return `${sized.toFixed(exponent === 0 ? 0 : 1)} ${units[exponent]}`;
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
    parts.push(`${remaining}s`);
    return parts.slice(0, 3).join(' ');
  }

  formatRate(value: number): string {
    if (!Number.isFinite(value) || value <= 0) {
      return '0 B/s';
    }
    return `${this.formatBytes(value)} /s`;
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
    return date.toLocaleString();
  }

  private fetchSystemStats(force = false): void {
    if (this.systemStatsRequestActive && !force) {
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
        this.systemStatsRates = { sentPerSec: 0, recvPerSec: 0 };
      }
      this.systemStats = data;
      this.previousSystemStats = data;
    }, () => {
      this.systemStatsRequestActive = false;
      this.systemStatsLoading = false;
      this.systemStatsError = 'Unable to load system statistics.';
    });
  }
}
