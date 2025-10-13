import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { NgbModule } from '@ng-bootstrap/ng-bootstrap';
import { FontAwesomeModule } from '@fortawesome/angular-fontawesome';

import { DashboardQueueComponent } from './dashboard-queue.component';
import { DashboardSharedModule } from '../dashboard-shared.module';

@NgModule({
  declarations: [DashboardQueueComponent],
  imports: [CommonModule, NgbModule, FontAwesomeModule, DashboardSharedModule],
  exports: [DashboardQueueComponent]
})
export class DashboardQueueModule {}
