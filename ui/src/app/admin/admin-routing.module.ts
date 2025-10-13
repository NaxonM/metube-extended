import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { AdminComponent } from './admin.component';

const routes: Routes = [
  {
    path: '',
    component: AdminComponent,
    children: [
      { path: '', redirectTo: 'users', pathMatch: 'full' },
      {
        path: 'users',
        loadChildren: () => import('./users/admin-users.module').then(m => m.AdminUsersModule)
      },
      {
        path: 'proxy',
        loadChildren: () => import('./proxy/admin-proxy.module').then(m => m.AdminProxyModule)
      },
      {
        path: 'system',
        loadChildren: () => import('./system/admin-system.module').then(m => m.AdminSystemModule)
      }
    ]
  }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class AdminRoutingModule {}
