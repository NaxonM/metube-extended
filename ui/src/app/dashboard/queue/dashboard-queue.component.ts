import { Component, OnInit, OnDestroy, AfterViewInit, ViewChild, ElementRef } from '@angular/core';
import { Subscription } from 'rxjs';

import { faDownload, faTrashAlt, faExternalLinkAlt, faCircleInfo, faLayerGroup } from '@fortawesome/free-solid-svg-icons';

import { DownloadsService } from '../../downloads.service';
import { MasterCheckboxComponent } from '../../master-checkbox.component';

@Component({
    selector: 'app-dashboard-queue',
    templateUrl: './dashboard-queue.component.html',
    styleUrls: ['./dashboard-queue.component.sass'],
    standalone: false
})
export class DashboardQueueComponent implements OnInit, AfterViewInit, OnDestroy {
  readonly queueDisplayLimit = 50;

  queueExpanded = false;
  visibleQueueKeys: string[] = [];
  hiddenQueueCount = 0;

  faDownload = faDownload;
  faTrashAlt = faTrashAlt;
  faExternalLinkAlt = faExternalLinkAlt;
  faCircleInfo = faCircleInfo;
  faLayerGroup = faLayerGroup;

  @ViewChild('queueMasterCheckbox') queueMasterCheckbox!: MasterCheckboxComponent;
  @ViewChild('queueDelSelected') queueDelSelected!: ElementRef<HTMLButtonElement>;
  @ViewChild('queueDownloadSelected') queueDownloadSelected!: ElementRef<HTMLButtonElement>;

  private queueSubscription?: Subscription;

  constructor(public readonly downloads: DownloadsService) {}

  ngOnInit(): void {
    this.refreshQueueView();
    this.queueSubscription = this.downloads.queueChanged.subscribe(() => {
      this.refreshQueueView();
      if (this.queueMasterCheckbox) {
        this.queueMasterCheckbox.selectionChanged();
      }
      this.updateBulkButtons();
    });
  }

  ngAfterViewInit(): void {
    this.updateBulkButtons();
  }

  ngOnDestroy(): void {
    this.queueSubscription?.unsubscribe();
  }

  trackByKey(index: number, key: string): string {
    return key;
  }

  queueSelectionChanged(checked: number): void {
    if (this.queueDelSelected) {
      this.queueDelSelected.nativeElement.disabled = checked === 0;
    }
    if (this.queueDownloadSelected) {
      this.queueDownloadSelected.nativeElement.disabled = checked === 0;
    }
  }

  showAllQueue(): void {
    if (this.queueExpanded) {
      return;
    }
    this.queueExpanded = true;
    this.refreshQueueView();
  }

  showLessQueue(): void {
    if (!this.queueExpanded) {
      return;
    }
    this.queueExpanded = false;
    this.refreshQueueView();
  }

  downloadItemByKey(id: string): void {
    this.downloads.startById([id]).subscribe();
  }

  delDownload(id: string): void {
    this.downloads.delById('queue', [id]).subscribe();
  }

  startSelectedDownloads(): void {
    this.downloads.startByFilter('queue', dl => dl.checked).subscribe();
  }

  delSelectedDownloads(): void {
    this.downloads.delByFilter('queue', dl => dl.checked).subscribe();
  }

  private refreshQueueView(): void {
    const keys = Array.from(this.downloads.queue.keys());
    this.visibleQueueKeys = this.queueExpanded ? keys : keys.slice(0, this.queueDisplayLimit);
    this.hiddenQueueCount = Math.max(keys.length - this.visibleQueueKeys.length, 0);
  }

  private updateBulkButtons(): void {
    if (!this.queueDelSelected || !this.queueDownloadSelected) {
      return;
    }
    const checked = Array.from(this.downloads.queue.values()).filter(dl => dl.checked).length;
    this.queueSelectionChanged(checked);
  }
}
