import { Component, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { faTachometerAlt, faUserShield, faServer, faImages } from '@fortawesome/free-solid-svg-icons';

import { DownloadsService, CurrentUser } from '../downloads.service';

interface AdminNavLink {
  label: string;
  description: string;
  icon: any;
  link: string;
}

@Component({
    selector: 'app-admin',
    templateUrl: './admin.component.html',
    styleUrls: ['./admin.component.sass'],
    standalone: false
})
export class AdminComponent implements OnInit {
  faUserShield = faUserShield;
  faTachometerAlt = faTachometerAlt;
  faServer = faServer;
  faImages = faImages;

  navLinks: AdminNavLink[] = [
    { label: 'Users', description: 'Manage accounts and roles.', icon: faUserShield, link: 'users' },
    { label: 'Proxy', description: 'Configure proxy download limits.', icon: faTachometerAlt, link: 'proxy' },
    { label: 'System', description: 'Monitor resource utilisation.', icon: faServer, link: 'system' },
    { label: 'Gallery-dl', description: 'Maintain gallery-dl credentials and cookies.', icon: faImages, link: 'gallery' }
  ];

  currentUser: CurrentUser | null = null;
  loadingUser = true;
  loadError = '';

  constructor(private readonly downloads: DownloadsService, private readonly router: Router) {}

  ngOnInit(): void {
    this.loadCurrentUser();
  }

  navigateBack(): void {
    this.router.navigateByUrl('/');
  }

  private loadCurrentUser(): void {
    this.loadingUser = true;
    this.downloads.getCurrentUser().subscribe(user => {
      this.loadingUser = false;
      if (!user || user.role !== 'admin') {
        this.loadError = 'Administrator access required.';
        this.router.navigateByUrl('/');
        return;
      }
      this.currentUser = user;
    }, () => {
      this.loadingUser = false;
      this.loadError = 'Unable to verify administrator access.';
      this.router.navigateByUrl('/');
    });
  }
}
