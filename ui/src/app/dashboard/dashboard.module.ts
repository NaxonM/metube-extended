import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { NgbModule } from '@ng-bootstrap/ng-bootstrap';
import { FontAwesomeModule } from '@fortawesome/angular-fontawesome';
import { NgSelectModule } from '@ng-select/ng-select';

import { DashboardComponent } from './dashboard.component';
import { DashboardRoutingModule } from './dashboard-routing.module';
import { DashboardSharedModule } from './dashboard-shared.module';
import { DashboardToolsModule } from './tools/dashboard-tools.module';
import { DashboardQueueModule } from './queue/dashboard-queue.module';
import { DashboardHistoryModule } from './history/dashboard-history.module';

@NgModule({
  declarations: [
    DashboardComponent
  ],
  imports: [
    CommonModule,
    FormsModule,
    NgbModule,
    FontAwesomeModule,
    NgSelectModule,
    DashboardRoutingModule,
    DashboardSharedModule,
    DashboardToolsModule,
    DashboardQueueModule,
    DashboardHistoryModule
  ]
})
export class DashboardModule {}
