import { Component, OnInit } from '@angular/core';

import { DownloadsService, GalleryDlCredentialSummary, GalleryDlCredentialDetail, GalleryDlCookieFile, GalleryDlCredentialPayload } from '../../downloads.service';

@Component({
  selector: 'app-admin-gallery',
  templateUrl: './admin-gallery.component.html',
  styleUrls: ['./admin-gallery.component.sass'],
  standalone: false
})
export class AdminGalleryComponent implements OnInit {
  gallerySettingsLoading = false;
  gallerySettingsError = '';
  galleryCredentials: GalleryDlCredentialSummary[] = [];
  galleryCookies: GalleryDlCookieFile[] = [];

  galleryCredentialLoading = false;
  galleryCredentialSaving = false;
  galleryCredentialMessage = '';
  galleryCredentialPasswordDirty = false;
  galleryCredentialForm = {
    id: null as string | null,
    name: '',
    extractor: '',
    username: '',
    password: '',
    twofactor: '',
    extraArgs: ''
  };

  galleryCookieLoading = false;
  galleryCookieSaving = false;
  galleryCookieMessage = '';
  galleryCookieForm = {
    name: '',
    content: ''
  };

  constructor(private readonly downloads: DownloadsService) {}

  ngOnInit(): void {
    this.refreshGallerydlSettings();
  }

  refreshGallerydlSettings(): void {
    this.gallerySettingsLoading = true;
    this.gallerySettingsError = '';
    let pending = 2;
    const finalize = () => {
      pending -= 1;
      if (pending <= 0) {
        this.gallerySettingsLoading = false;
      }
    };
    this.downloads.getGallerydlCredentials().subscribe(response => {
      this.galleryCredentials = response?.credentials ?? [];
      finalize();
    }, () => {
      this.gallerySettingsError = 'Unable to load credentials.';
      this.galleryCredentials = [];
      finalize();
    });

    this.downloads.listGallerydlCookies().subscribe(response => {
      this.galleryCookies = response?.cookies ?? [];
      finalize();
    }, () => {
      this.gallerySettingsError = this.gallerySettingsError || 'Unable to load cookies.';
      this.galleryCookies = [];
      finalize();
    });
  }

  newGalleryCredential(): void {
    this.galleryCredentialForm = {
      id: null,
      name: '',
      extractor: '',
      username: '',
      password: '',
      twofactor: '',
      extraArgs: ''
    };
    this.galleryCredentialPasswordDirty = false;
    this.galleryCredentialMessage = '';
  }

  selectGalleryCredential(credential: GalleryDlCredentialSummary): void {
    this.galleryCredentialLoading = true;
    this.galleryCredentialMessage = '';
    this.downloads.getGallerydlCredential(credential.id).subscribe(response => {
      this.galleryCredentialLoading = false;
      const detail = response?.credential as GalleryDlCredentialDetail;
      if (!detail) {
        return;
      }
      this.galleryCredentialForm = {
        id: detail.id,
        name: detail.name || '',
        extractor: detail.extractor || '',
        username: (detail.values?.username || '') as string,
        password: '',
        twofactor: (detail.values?.twofactor || '') as string,
        extraArgs: this.convertExtraArgsToText(detail.values?.extra_args as string[])
      };
      this.galleryCredentialPasswordDirty = false;
    }, () => {
      this.galleryCredentialLoading = false;
      this.galleryCredentialMessage = 'Unable to load credential.';
    });
  }

  onGalleryCredentialPasswordChange(): void {
    this.galleryCredentialPasswordDirty = true;
  }

  saveGalleryCredential(): void {
    const form = this.galleryCredentialForm;
    const name = form.name.trim();
    if (!name) {
      this.galleryCredentialMessage = 'Name is required.';
      return;
    }

    const payload: GalleryDlCredentialPayload & { extra_args?: string[] } = {
      name,
      extractor: form.extractor.trim() || null,
      username: form.username.trim() || null,
      twofactor: form.twofactor.trim() || null,
      extra_args: this.parseExtraArgsText(form.extraArgs)
    };

    this.galleryCredentialSaving = true;
    this.galleryCredentialMessage = '';

    if (form.id) {
      if (this.galleryCredentialPasswordDirty) {
        payload.password = form.password;
      }
      this.downloads.updateGallerydlCredential(form.id, payload).subscribe(response => {
        this.galleryCredentialSaving = false;
        if ((response as any)?.status === 'error') {
          this.galleryCredentialMessage = (response as any).msg || 'Unable to update credential.';
          return;
        }
        this.galleryCredentialPasswordDirty = false;
        this.galleryCredentialMessage = 'Credential updated.';
        this.refreshGallerydlSettings();
      }, error => {
        this.galleryCredentialSaving = false;
        this.galleryCredentialMessage = (error?.error && typeof error.error === 'string') ? error.error : 'Unable to update credential.';
      });
      return;
    }

    payload.password = form.password || '';
    this.downloads.createGallerydlCredential(payload).subscribe(response => {
      this.galleryCredentialSaving = false;
      if ((response as any)?.status === 'error') {
        this.galleryCredentialMessage = (response as any).msg || 'Unable to create credential.';
        return;
      }
      this.galleryCredentialMessage = 'Credential created.';
      this.newGalleryCredential();
      this.refreshGallerydlSettings();
    }, error => {
      this.galleryCredentialSaving = false;
      this.galleryCredentialMessage = (error?.error && typeof error.error === 'string') ? error.error : 'Unable to create credential.';
    });
  }

  deleteGalleryCredential(): void {
    const form = this.galleryCredentialForm;
    if (!form.id) {
      return;
    }
    if (!confirm(`Delete credential "${form.name}"?`)) {
      return;
    }
    this.downloads.deleteGallerydlCredential(form.id).subscribe(() => {
      this.galleryCredentialMessage = 'Credential deleted.';
      this.newGalleryCredential();
      this.refreshGallerydlSettings();
    }, error => {
      this.galleryCredentialMessage = (error?.error && typeof error.error === 'string') ? error.error : 'Unable to delete credential.';
    });
  }

  editGalleryCookie(cookie: GalleryDlCookieFile): void {
    this.galleryCookieLoading = true;
    this.galleryCookieMessage = '';
    this.downloads.getGallerydlCookie(cookie.name).subscribe(response => {
      this.galleryCookieLoading = false;
      this.galleryCookieForm = {
        name: response?.name || cookie.name,
        content: response?.content || ''
      };
    }, error => {
      this.galleryCookieLoading = false;
      this.galleryCookieMessage = (error?.error && typeof error.error === 'string') ? error.error : 'Unable to load cookie.';
    });
  }

  resetGalleryCookieForm(): void {
    this.galleryCookieForm = {
      name: '',
      content: ''
    };
    this.galleryCookieMessage = '';
  }

  saveGalleryCookie(): void {
    const name = this.galleryCookieForm.name.trim();
    const content = this.galleryCookieForm.content.trim();
    if (!name) {
      this.galleryCookieMessage = 'Cookie name is required.';
      return;
    }
    if (!content) {
      this.galleryCookieMessage = 'Cookie content is required.';
      return;
    }
    this.galleryCookieSaving = true;
    this.galleryCookieMessage = '';
    this.downloads.saveGallerydlCookie({ name, content }).subscribe(response => {
      this.galleryCookieSaving = false;
      if ((response as any)?.status === 'error') {
        this.galleryCookieMessage = (response as any).msg || 'Unable to save cookie.';
        return;
      }
      this.galleryCookieMessage = 'Cookie saved.';
      this.refreshGallerydlSettings();
    }, error => {
      this.galleryCookieSaving = false;
      this.galleryCookieMessage = (error?.error && typeof error.error === 'string') ? error.error : 'Unable to save cookie.';
    });
  }

  deleteGalleryCookie(name: string): void {
    const trimmed = (name || '').trim();
    if (!trimmed) {
      return;
    }
    if (!confirm(`Delete cookie "${trimmed}"?`)) {
      return;
    }
    this.downloads.deleteGallerydlCookie(trimmed).subscribe(() => {
      this.galleryCookieMessage = 'Cookie deleted.';
      if (this.galleryCookieForm.name.trim() === trimmed) {
        this.resetGalleryCookieForm();
      }
      this.refreshGallerydlSettings();
    }, error => {
      this.galleryCookieMessage = (error?.error && typeof error.error === 'string') ? error.error : 'Unable to delete cookie.';
    });
  }

  private convertExtraArgsToText(args?: string[] | null): string {
    if (!args || !args.length) {
      return '';
    }
    return args.join('\n');
  }

  private parseExtraArgsText(value: string): string[] {
    if (!value) {
      return [];
    }
    return value
      .split(/\r?\n/)
      .map(line => line.trim())
      .filter(line => !!line)
      .slice(0, 32);
  }
}
