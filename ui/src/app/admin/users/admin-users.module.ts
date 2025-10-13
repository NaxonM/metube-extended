import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FontAwesomeModule } from '@fortawesome/angular-fontawesome';

import { AdminUsersComponent } from './admin-users.component';
import { AdminUsersRoutingModule } from './admin-users-routing.module';

@NgModule({
  declarations: [AdminUsersComponent],
  imports: [CommonModule, FontAwesomeModule, AdminUsersRoutingModule]
})
export class AdminUsersModule {}
