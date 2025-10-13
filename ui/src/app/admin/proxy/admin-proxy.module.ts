import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { AdminProxyComponent } from './admin-proxy.component';
import { AdminProxyRoutingModule } from './admin-proxy-routing.module';

@NgModule({
  declarations: [AdminProxyComponent],
  imports: [CommonModule, AdminProxyRoutingModule]
})
export class AdminProxyModule {}
