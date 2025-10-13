import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { NgbModule } from '@ng-bootstrap/ng-bootstrap';
import { FontAwesomeModule } from '@fortawesome/angular-fontawesome';

import { DashboardHistoryComponent } from './dashboard-history.component';
import { DashboardSharedModule } from '../dashboard-shared.module';

@NgModule({
  declarations: [DashboardHistoryComponent],
  imports: [CommonModule, FormsModule, NgbModule, FontAwesomeModule, DashboardSharedModule],
  exports: [DashboardHistoryComponent]
})
export class DashboardHistoryModule {}
