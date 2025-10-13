import { Component, OnInit } from '@angular/core';
import { faUserShield, faUserPlus, faUserSlash, faPen, faKey, faTrashAlt } from '@fortawesome/free-solid-svg-icons';

import { DownloadsService, ManagedUser } from '../../downloads.service';

@Component({
  selector: 'app-admin-users',
  templateUrl: './admin-users.component.html',
  styleUrls: ['./admin-users.component.sass'],
  standalone: false
})
export class AdminUsersComponent implements OnInit {
  faUserShield = faUserShield;
  faUserPlus = faUserPlus;
  faUserSlash = faUserSlash;
  faPen = faPen;
  faKey = faKey;
  faTrashAlt = faTrashAlt;

  adminUsers: ManagedUser[] = [];
  adminLoading = false;
  adminError = '';

  private currentUserId: string | null = null;

  constructor(private readonly downloads: DownloadsService) {}

  ngOnInit(): void {
    this.resolveCurrentUser();
  }

  refreshUsers(): void {
    this.adminLoading = true;
    this.adminError = '';
    this.downloads.listUsers().subscribe(response => {
      if (!response || (response as any)?.status === 'error') {
        const message = (response as any)?.msg || 'Unable to load users.';
        this.adminError = message;
        this.adminUsers = [];
        this.adminLoading = false;
        return;
      }
      this.adminUsers = (response.users ?? []).slice().sort((a, b) => a.username.localeCompare(b.username));
      this.adminLoading = false;
    }, () => {
      this.adminLoading = false;
      this.adminError = 'Unable to load users.';
    });
  }

  activeAdminCount(): number {
    return this.adminUsers.filter(user => user.role === 'admin' && !user.disabled).length;
  }

  isSelf(user: ManagedUser): boolean {
    return !!user && !!this.currentUserId && user.id === this.currentUserId;
  }

  promptCreateUser(): void {
    const username = (prompt('Enter a username for the new account') || '').trim();
    if (!username) {
      return;
    }
    const password = prompt(`Enter a password for ${username}`) || '';
    if (!password) {
      alert('Password is required.');
      return;
    }
    const makeAdmin = confirm('Should this user have administrator access?');
    this.downloads.createUser(username, password, makeAdmin ? 'admin' : 'user').subscribe(result => {
      if ((result as any)?.status === 'error') {
        alert((result as any).msg || 'Failed to create user.');
        return;
      }
      this.refreshUsers();
    }, () => alert('Failed to create user.'));
  }

  promptUpdateUser(user: ManagedUser): void {
    const newUsername = (prompt('Update username', user.username) || '').trim();
    if (!newUsername || newUsername === user.username) {
      return;
    }
    this.downloads.updateUser(user.id, { username: newUsername }).subscribe(result => {
      if ((result as any)?.status === 'error') {
        alert((result as any).msg || 'Failed to rename user.');
        return;
      }
      this.refreshUsers();
    }, () => alert('Failed to rename user.'));
  }

  toggleUserDisabled(user: ManagedUser): void {
    const disable = !user.disabled;
    if (user.role === 'admin' && disable && this.activeAdminCount() <= 1) {
      alert('At least one admin must remain active.');
      return;
    }
    this.downloads.updateUser(user.id, { disabled: disable }).subscribe(result => {
      if ((result as any)?.status === 'error') {
        alert((result as any).msg || 'Failed to update user.');
        return;
      }
      this.refreshUsers();
    }, () => alert('Failed to update user.'));
  }

  resetUserPassword(user: ManagedUser): void {
    const password = prompt(`Enter a new password for ${user.username}`) || '';
    if (!password) {
      return;
    }
    this.downloads.updateUser(user.id, { password }).subscribe(result => {
      if ((result as any)?.status === 'error') {
        alert((result as any).msg || 'Failed to reset password.');
        return;
      }
      alert('Password updated.');
    }, () => alert('Failed to reset password.'));
  }

  deleteUser(user: ManagedUser): void {
    if (this.isSelf(user)) {
      alert('You cannot delete your own account.');
      return;
    }
    if (user.role === 'admin' && this.activeAdminCount() <= 1) {
      alert('At least one admin account must remain.');
      return;
    }
    if (!confirm(`Delete user ${user.username}? This cannot be undone.`)) {
      return;
    }
    this.downloads.deleteUser(user.id).subscribe(result => {
      if ((result as any)?.status === 'error') {
        alert((result as any).msg || 'Failed to delete user.');
        return;
      }
      this.refreshUsers();
    }, () => alert('Failed to delete user.'));
  }

  private resolveCurrentUser(): void {
    this.downloads.getCurrentUser().subscribe(user => {
      if (!user || user.role !== 'admin') {
        this.adminError = 'Administrator access required.';
        this.adminUsers = [];
        return;
      }
      this.currentUserId = user.id;
      this.refreshUsers();
    }, () => {
      this.adminError = 'Unable to verify current user.';
      this.adminUsers = [];
    });
  }
}
