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

  constructor(private http: HttpClient, private socket: MeTubeSocket) {
    socket.fromEvent('all').subscribe((strdata: string) => {
      this.loading = false;
      let data: [[[string, Download]], [[string, Download]]] = JSON.parse(strdata);
      this.queue.clear();
      data[0].forEach(entry => this.queue.set(...entry));
      this.done.clear();
      data[1].forEach(entry => this.done.set(...entry));
      this.queueChanged.next(null);
      this.doneChanged.next(null);
    });
    socket.fromEvent('added').subscribe((strdata: string) => {
      let data: Download = JSON.parse(strdata);
      this.queue.set(data.url, data);
      this.queueChanged.next(null);
    });
    socket.fromEvent('updated').subscribe((strdata: string) => {
      let data: Download = JSON.parse(strdata);
      let dl: Download = this.queue.get(data.url);
      data.checked = dl?.checked;
      data.deleting = dl?.deleting;
      this.queue.set(data.url, data);
      this.updated.next(null);
    });
    socket.fromEvent('completed').subscribe((strdata: string) => {
      let data: Download = JSON.parse(strdata);
      this.queue.delete(data.url);
      this.done.set(data.url, data);
      this.queueChanged.next(null);
      this.doneChanged.next(null);
    });
    socket.fromEvent('canceled').subscribe((strdata: string) => {
      let data: string = JSON.parse(strdata);
      this.queue.delete(data);
      this.queueChanged.next(null);
    });
    socket.fromEvent('cleared').subscribe((strdata: string) => {
      let data: string = JSON.parse(strdata);
      this.done.delete(data);
      this.doneChanged.next(null);
    });
    socket.fromEvent('renamed').subscribe((strdata: string) => {
      let data: Download = JSON.parse(strdata);
      let existing: Download = this.done.get(data.url);
      if (!existing) {
        return;
      }
      existing = {
        ...existing,
        filename: data.filename ?? data.title ?? existing.filename,
        title: data.title ?? existing.title,
        msg: data.msg ?? existing.msg,
        error: data.error ?? existing.error,
        size: data.size ?? existing.size
      };
      this.done.set(data.url, existing);
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
    this[where].forEach((dl: Download) => { if (filter(dl)) ids.push(dl.url) });
    return this.startById(ids);
  }

  public delByFilter(where: 'queue' | 'done', filter: (dl: Download) => boolean) {
    let ids: string[] = [];
    this[where].forEach((dl: Download) => { if (filter(dl)) ids.push(dl.url) });
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
