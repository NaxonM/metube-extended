import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { AdminSystemComponent } from './admin-system.component';
import { AdminSystemRoutingModule } from './admin-system-routing.module';

@NgModule({
  declarations: [AdminSystemComponent],
  imports: [CommonModule, FormsModule, AdminSystemRoutingModule]
})
export class AdminSystemModule {}
