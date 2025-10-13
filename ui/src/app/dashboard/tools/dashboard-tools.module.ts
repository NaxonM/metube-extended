import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { NgbModule } from '@ng-bootstrap/ng-bootstrap';
import { FontAwesomeModule } from '@fortawesome/angular-fontawesome';

import { DashboardToolsComponent } from './dashboard-tools.component';
import { DashboardSharedModule } from '../dashboard-shared.module';
import { AdminGalleryModule } from '../../admin/gallery/admin-gallery.module';

@NgModule({
  declarations: [DashboardToolsComponent],
  imports: [CommonModule, FormsModule, NgbModule, FontAwesomeModule, DashboardSharedModule, AdminGalleryModule],
  exports: [DashboardToolsComponent]
})
export class DashboardToolsModule {}
