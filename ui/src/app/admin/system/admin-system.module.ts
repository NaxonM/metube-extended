import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { AdminSystemComponent } from './admin-system.component';
import { AdminSystemRoutingModule } from './admin-system-routing.module';

@NgModule({
  declarations: [AdminSystemComponent],
  imports: [CommonModule, AdminSystemRoutingModule]
})
export class AdminSystemModule {}
