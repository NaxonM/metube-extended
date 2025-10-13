import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';

import { AdminProxyComponent } from './admin-proxy.component';

const routes: Routes = [
  {
    path: '',
    component: AdminProxyComponent
  }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class AdminProxyRoutingModule {}
