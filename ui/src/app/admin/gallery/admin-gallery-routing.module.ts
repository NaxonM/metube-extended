import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';

import { AdminGalleryComponent } from './admin-gallery.component';

const routes: Routes = [
  {
    path: '',
    component: AdminGalleryComponent
  }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class AdminGalleryRoutingModule {}
