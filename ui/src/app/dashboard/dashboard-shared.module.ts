import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { EtaPipe, SpeedPipe, FileSizePipe, EncodeURIComponent } from '../downloads.pipe';
import { MasterCheckboxComponent, SlaveCheckboxComponent } from '../master-checkbox.component';

@NgModule({
  declarations: [
    EtaPipe,
    SpeedPipe,
    FileSizePipe,
    EncodeURIComponent,
    MasterCheckboxComponent,
    SlaveCheckboxComponent
  ],
  imports: [CommonModule, FormsModule],
  exports: [
    EtaPipe,
    SpeedPipe,
    FileSizePipe,
    EncodeURIComponent,
    MasterCheckboxComponent,
    SlaveCheckboxComponent
  ]
})
export class DashboardSharedModule {}
