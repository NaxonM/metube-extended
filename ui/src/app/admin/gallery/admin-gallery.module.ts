import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { NgbModule } from '@ng-bootstrap/ng-bootstrap';

import { AdminGalleryComponent } from './admin-gallery.component';
import { AdminGalleryRoutingModule } from './admin-gallery-routing.module';

@NgModule({
  declarations: [AdminGalleryComponent],
  imports: [CommonModule, FormsModule, NgbModule, AdminGalleryRoutingModule],
  exports: [AdminGalleryComponent]
})
export class AdminGalleryModule {}
