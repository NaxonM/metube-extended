import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';

import { AdminSystemComponent } from './admin-system.component';

const routes: Routes = [
  {
    path: '',
    component: AdminSystemComponent
  }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class AdminSystemRoutingModule {}
