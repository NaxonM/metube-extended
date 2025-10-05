import { Injectable } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Observable, of, Subject } from 'rxjs';
import { catchError, tap } from 'rxjs/operators';
import { MeTubeSocket } from './metube-socket';

export interface Status {
  status: string;
  msg?: string;
}

export interface Download {
  id: string;
  title: string;
  url: string;
  quality: string;
  format: string;
  folder: string;
  custom_name_prefix: string;
  playlist_strict_mode: boolean;
  playlist_item_limit: number;
  status: string;
  msg: string;
  percent: number;
  speed: number;
  eta: number;
  filename: string;
  error?: string;
  size?: number;
  thumbnail?: string;
  timestamp?: number;
  history_key?: string;
  checked?: boolean;
  deleting?: boolean;
}

export interface CurrentUser {
  id: string;
  username: string;
  role: 'admin' | 'user';
}

export interface ManagedUser extends CurrentUser {
  disabled: boolean;
  created_at: number;
  updated_at: number;
  last_login_at?: number | null;
  password_updated?: boolean;
}

@Injectable({
  providedIn: 'root'
})
export class DownloadsService {
  loading = true;
  queue = new Map<string, Download>();
  done = new Map<string, Download>();
  queueChanged = new Subject();
  doneChanged = new Subject();
  customDirsChanged = new Subject();
  ytdlOptionsChanged = new Subject();
  configurationChanged = new Subject();
  updated = new Subject();

  configuration = {};
  customDirs = {};
  private readonly fallbackPrefix = 'dl';
  private counter = 0;

  private normalizeDownload(download: Download | null | undefined, key?: string): Download | undefined {
    if (!download) {
      return undefined;
    }

    if (typeof download.timestamp !== 'number') {
      download.timestamp = Date.now();
    }

    if (!download.history_key) {
      if (key) {
        download.history_key = key;
      } else if (download.url) {
        download.history_key = `${download.url}::${download.timestamp}`;
      } else {
        this.counter += 1;
        download.history_key = `${this.fallbackPrefix}-${this.counter}-${download.timestamp}`;
      }
    }

    if (!download.title || download.title.trim().length === 0) {
      if (download.filename && download.filename.trim().length > 0) {
        download.title = download.filename.trim();
      } else if (download.url && download.url.trim().length > 0) {
        download.title = download.url.trim();
      } else if (download.id && download.id.trim().length > 0) {
        download.title = download.id.trim();
      } else {
        download.title = 'Unknown download';
      }
    }

    return download;
  }

  constructor(private http: HttpClient, private socket: MeTubeSocket) {
    socket.fromEvent('all').subscribe((strdata: string) => {
      this.loading = false;
      const data: [Array<[string, Download]>, Array<[string, Download]>] = JSON.parse(strdata);
      this.queue.clear();
      data[0].forEach(([key, download]) => {
        const normalized = this.normalizeDownload(download, key);
        if (!normalized) {
          return;
        }
        this.queue.set(normalized.url ?? key, normalized);
      });
      this.done.clear();
      data[1].forEach(([key, download]) => {
        const normalized = this.normalizeDownload(download, key);
        if (!normalized) {
          return;
        }
        this.done.set(normalized.history_key, normalized);
      });
      this.queueChanged.next(null);
      this.doneChanged.next(null);
    });
    socket.fromEvent('added').subscribe((strdata: string) => {
      const data: Download = JSON.parse(strdata);
      const normalized = this.normalizeDownload(data);
      if (!normalized) {
        return;
      }
      this.queue.set(normalized.url ?? normalized.history_key, normalized);
      this.queueChanged.next(null);
    });
    socket.fromEvent('updated').subscribe((strdata: string) => {
      const data: Download = JSON.parse(strdata);
      const dl: Download | undefined = this.queue.get(data.url);
      if (!data.history_key && dl?.history_key) {
        data.history_key = dl.history_key;
      }
      data.checked = dl?.checked;
      data.deleting = dl?.deleting;
      const normalized = this.normalizeDownload(data);
      if (!normalized) {
        return;
      }
      this.queue.set(normalized.url ?? normalized.history_key, normalized);
      this.queueChanged.next(null);
      this.updated.next(null);
    });
    socket.fromEvent('completed').subscribe((strdata: string) => {
      const data: Download = JSON.parse(strdata);
      const normalized = this.normalizeDownload(data);
      if (!normalized) {
        return;
      }
      const queueKey = normalized.url ?? normalized.history_key;
      this.queue.delete(queueKey);

      const existing = this.done.get(normalized.history_key) || this.done.get(queueKey);
      if (existing) {
        normalized.checked = existing.checked;
        normalized.deleting = existing.deleting;
        if (normalized.history_key !== queueKey) {
          this.done.delete(queueKey);
        }
      }

      this.done.set(normalized.history_key, normalized);
      this.queueChanged.next(null);
      this.doneChanged.next(null);
    });
    socket.fromEvent('canceled').subscribe((strdata: string) => {
      let data: string = JSON.parse(strdata);
      this.queue.delete(data);
      this.queueChanged.next(null);
    });
    socket.fromEvent('cleared').subscribe((strdata: string) => {
      const key: string = JSON.parse(strdata);
      let removed = this.done.delete(key);

      if (!removed) {
        for (const [mapKey, download] of this.done.entries()) {
          if (download.history_key === key || download.url === key) {
            this.done.delete(mapKey);
            removed = true;
            break;
          }
        }
      }

      if (removed) {
        this.doneChanged.next(null);
      }
    });
    socket.fromEvent('renamed').subscribe((strdata: string) => {
      const data: Download = JSON.parse(strdata);
      const normalized = this.normalizeDownload(data);
      if (!normalized) {
        return;
      }

      const key = normalized.history_key || normalized.url;
      let existing: Download | undefined = this.done.get(key);

      const urlKey = normalized.url ?? normalized.history_key;

      if (!existing && normalized.history_key && this.done.has(urlKey)) {
        existing = this.done.get(urlKey);
        this.done.delete(urlKey);
      }

      if (!existing) {
        this.done.set(key, normalized);
        this.doneChanged.next(null);
        return;
      }

      const merged = {
        ...existing,
        ...normalized,
        history_key: normalized.history_key ?? existing.history_key
      };

      this.done.set(key, merged);
      this.doneChanged.next(null);
    });
    socket.fromEvent('configuration').subscribe((strdata: string) => {
      let data = JSON.parse(strdata);
      console.debug("got configuration:", data);
      this.configuration = data;
      this.configurationChanged.next(data);
    });
    socket.fromEvent('custom_dirs').subscribe((strdata: string) => {
      let data = JSON.parse(strdata);
      console.debug("got custom_dirs:", data);
      this.customDirs = data;
      this.customDirsChanged.next(data);
    });
    socket.fromEvent('ytdl_options_changed').subscribe((strdata: string) => {
      let data = JSON.parse(strdata);
      this.ytdlOptionsChanged.next(data);
    });
  }

  handleHTTPError(error: HttpErrorResponse) {
    var msg = error.error instanceof ErrorEvent ? error.error.message : error.error;
    return of({status: 'error', msg: msg})
  }

  public add(url: string, quality: string, format: string, folder: string, customNamePrefix: string, playlistStrictMode: boolean, playlistItemLimit: number, autoStart: boolean) {
    return this.http.post<Status>('add', {url: url, quality: quality, format: format, folder: folder, custom_name_prefix: customNamePrefix, playlist_strict_mode: playlistStrictMode, playlist_item_limit: playlistItemLimit, auto_start: autoStart}).pipe(
      catchError(this.handleHTTPError)
    );
  }

  public startById(ids: string[]) {
    return this.http.post('start', {ids: ids});
  }

  public delById(where: 'queue' | 'done', ids: string[]) {
    ids.forEach(id => {
      const entry = (this as any)[where]?.get(id);
      if (entry) {
        entry.deleting = true;
      }
    });

    return this.http.post<any>('delete', {where: where, ids: ids}).pipe(
      tap(result => {
        if (!result || result.status === 'error') {
          ids.forEach(id => {
            const entry = (this as any)[where]?.get(id);
            if (entry) {
              entry.deleting = false;
            }
          });
        }

        if (where !== 'done' || !result) {
          return;
        }

        if (result.status === 'ok') {
          const deleted: string[] = result.deleted || [];
          const missing: string[] = result.missing || [];
          let messageParts: string[] = [];
          if (deleted.length) {
            messageParts.push('Removed from disk:\n' + deleted.map(name => `• ${name}`).join('\n'));
          }
          if (missing.length) {
            messageParts.push('Already missing on disk:\n' + missing.map(name => `• ${name}`).join('\n'));
          }
          if (!messageParts.length) {
            messageParts.push('Selected downloads removed.');
          }
          alert(messageParts.join('\n\n'));
        } else {
          const errors = result.errors ? Object.values(result.errors).join('\n') : (result.msg || 'Unknown error.');
          alert('Unable to remove one or more files:\n' + errors);
        }
      }),
      catchError(error => {
        ids.forEach(id => {
          const entry = (this as any)[where]?.get(id);
          if (entry) {
            entry.deleting = false;
          }
        });
        if (where === 'done') {
          const message = error.error instanceof ErrorEvent ? error.error.message : (error.error || error.message || 'Request failed');
          alert('Unable to remove files:\n' + message);
        }
        return this.handleHTTPError(error);
      })
    );
  }

  public startByFilter(where: 'queue' | 'done', filter: (dl: Download) => boolean) {
    let ids: string[] = [];
    this[where].forEach((dl: Download, key: string) => { if (filter(dl)) ids.push(key); });
    return this.startById(ids);
  }

  public delByFilter(where: 'queue' | 'done', filter: (dl: Download) => boolean) {
    let ids: string[] = [];
    this[where].forEach((dl: Download, key: string) => { if (filter(dl)) ids.push(key); });
    return this.delById(where, ids);
  }
  public addDownloadByUrl(url: string): Promise<any> {
    const defaultQuality = 'best';
    const defaultFormat = 'mp4';
    const defaultFolder = ''; 
    const defaultCustomNamePrefix = '';
    const defaultPlaylistStrictMode = false;
    const defaultPlaylistItemLimit = 0;
    const defaultAutoStart = true;
    
    return new Promise((resolve, reject) => {
      this.add(url, defaultQuality, defaultFormat, defaultFolder, defaultCustomNamePrefix, defaultPlaylistStrictMode, defaultPlaylistItemLimit, defaultAutoStart)
        .subscribe(
          response => resolve(response),
          error => reject(error)
        );
    });
  }
  public exportQueueUrls(): string[] {
    return Array.from(this.queue.values()).map(download => download.url);
  }
  
  public rename(id: string, newName: string) {
    return this.http.post<Status>('rename', {id: id, new_name: newName}).pipe(
      catchError(this.handleHTTPError)
    );
  }

  public setCookies(cookies: string) {
    return this.http.post<Status>('cookies', {cookies: cookies}).pipe(
      catchError(this.handleHTTPError)
    );
  }

  public clearCookies() {
    return this.http.delete<Status>('cookies').pipe(
      catchError(this.handleHTTPError)
    );
  }

  public getCookiesStatus() {
    return this.http.get<{has_cookies: boolean}>('cookies').pipe(
      catchError(() => of({has_cookies: false}))
    );
  }

  public getCurrentUser() {
    return this.http.get<CurrentUser>('me').pipe(
      catchError(() => of(null as CurrentUser | null))
    );
  }

  public listUsers() {
    return this.http.get<{users: ManagedUser[]}>('admin/users').pipe(
      catchError(() => of({users: [] as ManagedUser[]}))
    );
  }

  public createUser(username: string, password: string, role: 'admin' | 'user') {
    return this.http.post<ManagedUser>('admin/users', {username, password, role}).pipe(
      catchError(this.handleHTTPError)
    );
  }

  public updateUser(userId: string, payload: Partial<{password: string; role: 'admin' | 'user'; disabled: boolean;}>) {
    return this.http.patch<ManagedUser>(`admin/users/${userId}`, payload).pipe(
      catchError(this.handleHTTPError)
    );
  }

  public deleteUser(userId: string) {
    return this.http.delete('admin/users/' + userId).pipe(
      catchError(this.handleHTTPError)
    );
  }
  
}
