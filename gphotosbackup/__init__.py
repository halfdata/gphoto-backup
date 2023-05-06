"""Main class to use Google Photos Backup."""
import http
import os
import queue
import requests
import shutil
import socket
import threading
import time

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable, Optional

import google.oauth2.credentials
import googleapiclient.discovery

from . import errors, models, utils


class GPhotosBackup:
    """Class that handles creating backups."""
    STORAGE_PATH: str = 'archive'
    user: Any
    credentials: google.oauth2.credentials.Credentials
    gphoto_resource: googleapiclient.discovery.Resource
    update_credentials_callback: Callable
    db: models.DB
    log_queue: queue.SimpleQueue
    global_crawler_lock: threading.Event
    current_cycle: int
    crawling_termination_time: Optional[float] = None

    def __init__(self, *,
                 global_crawler_lock: threading.Event,
                 user_id: str,
                 credentials: google.oauth2.credentials.Credentials,
                 update_credentials_callback: Callable,
                 db: models.DB):
        self.global_crawler_lock = global_crawler_lock
        self.credentials = credentials
        self.update_credentials_callback = update_credentials_callback
        self.db = db
        self.user = self.db.get_user_by(id=user_id)
        if not self.user:
            raise AttributeError(f'User with id "{user_id}" not found.')
        self.gphoto_resource = googleapiclient.discovery.build(
            'photoslibrary', 'v1', credentials=self.credentials,
            static_discovery=False)
        self.log_queue = queue.SimpleQueue()
        self.current_cycle = self.db.get_user_option(self.user.id, 'current-cycle', 0)

    def file_exists(self, filename: str) -> bool:
        """Check if file exists."""
        abs_filename = os.path.abspath(os.path.join(self.STORAGE_PATH,
                                                    self.user.email,
                                                    filename))
        return os.path.exists(abs_filename)

    def generate_filename(self, item: dict[str, Any]) -> Optional[str]:
        """Generate filename based on media item data."""
        folder = 'other'
        creation_time = item.get('mediaMetadata', {}).get('creationTime', '')
        if creation_time:
            time_parts = creation_time.split('-')
            if len(time_parts) > 1:
                folder = os.path.join(time_parts[0], time_parts[1])
        abs_path_folder = os.path.abspath(os.path.join(self.STORAGE_PATH,
                                                       self.user.email,
                                                       folder))
        try:
            os.makedirs(abs_path_folder, exist_ok=True)
        except OSError:
            return None
        filename = item['filename']
        i = 2
        while (os.path.exists(os.path.join(abs_path_folder, filename)) or
            self.db.get_user_mediaitem_by(user_id=self.user.id,
                                          filename=filename)):
            filename_parts = item['filename'].rsplit('.', 1)
            filename_parts[0] += f'-{i}'
            filename = '.'.join(filename_parts)
            i += 1
        return os.path.join(folder, filename)

    def set_mediaitem(self, item: dict[str, Any]) -> utils.DownloadInfo:
        """Save media item into DB."""
        mediaitem = self.db.get_user_mediaitem_by(user_id=self.user.id,
                                                  mediaitem_id=item['id'])
        item_type = item['mimeType'].split('/')[0]
        creation_time = item.get('mediaMetadata', {}).get('creationTime', '')
        download_info = utils.DownloadInfo(
            id=0,
            creation_time=creation_time,
            item_type=item_type,
            base_url=item['baseUrl'],
            filename='',
            original_filename=item['filename'],
            download_status=utils.DownloadStatus.READY
        )

        if item_type == 'video':
            status = item.get('mediaMetadata', {}).get('video', {}).get('status', None)
            if status != 'READY':
                download_info.download_status = utils.DownloadStatus.NOT_READY
                return download_info

        if not mediaitem:
            filename=self.generate_filename(item)
            item_id = self.db.add_mediaitem(
                user_id=self.user.id,
                last_seen=self.current_cycle,
                mediaitem_id=item['id'],
                type=item_type,
                mime_type=item['mimeType'],
                product_url=item['productUrl'],
                creation_time=creation_time,
                original_filename=item['filename'],
                filename=filename)
            download_info.id = item_id
            download_info.filename = filename
            return download_info

        download_info.id = mediaitem.id
        if not mediaitem.filename:
            filename=self.generate_filename(item)
            self.db.update_mediaitem(id=mediaitem.id,
                                     filename=filename,
                                     last_seen=self.current_cycle)
            download_info.filename = filename
            return download_info

        self.db.update_mediaitem(id=mediaitem.id, last_seen=self.current_cycle)
        download_info.filename = mediaitem.filename
        abs_path_folder = os.path.dirname(
            os.path.abspath(os.path.join(self.STORAGE_PATH,
                                         self.user.email,
                                         mediaitem.filename)))
        os.makedirs(abs_path_folder, exist_ok=True)        
        if not self.file_exists(mediaitem.filename):
            return download_info
        
        download_info.download_status = utils.DownloadStatus.ALREADY_DOWNLOADED
        return download_info

    def download_mediaitem(self, download_info: utils.DownloadInfo) -> None:
        """Download media item."""
        print(f'{download_info.filename} - downloading')
        url = f'{download_info.base_url}=d{"v" if download_info.item_type == "video" else ""}'
        full_filename = os.path.abspath(os.path.join(self.STORAGE_PATH,
                                                     self.user.email,
                                                     download_info.filename))
        filetime = utils.convert_iso_to_timestamp(download_info.creation_time)
        try:
            with requests.get(url, timeout=(5, None), stream=True) as r:
                r.raise_for_status()
                with open(full_filename, 'wb') as f:
                    shutil.copyfileobj(r.raw, f)
                os.utime(full_filename, times=(filetime, filetime))
                self.log_queue.put(f'{download_info.original_filename} - '
                                   'downloaded')
        except Exception:
            if os.path.exists(full_filename):
                print(f'{download_info.filename} - failed to download')
                self.log_queue.put(f'{download_info.original_filename} - '
                                   'failed to download')
                os.remove(full_filename)
            with utils.disable_exception_traceback():
                raise

    def _download_mediaitems_from_next_page(self) -> list[utils.DownloadInfo]:
        """Reads next 10 media items from Google Photos and download them.
        
        Returns: list with information about processed media items.
        """
        page_token = self.db.get_user_option(self.user.id, 'next-page-token')
        try:
            response = self.gphoto_resource.mediaItems().list(
                pageSize=10, pageToken=page_token).execute()
            self.update_credentials_callback()
        except googleapiclient.errors.HttpError as error:
            print(error)
            raise
        except google.auth.exceptions.RefreshError as error:
            print('Invalid credentials to access Google Photos.')
            raise
        except (http.client.RemoteDisconnected, socket.gaierror):
            print('Can not connect to Google Photos. '
                  'Please check internet connection.')
            raise
        except KeyboardInterrupt:
            print('Downloading media items terminated. Run script again to continue.')
            with utils.disable_exception_traceback():
                raise
        if 'mediaItems' not in response:
            print('No media items in response.')
            raise errors.InvalidResponse()
        files_to_download = []
        return_info = []
        for item in response['mediaItems']:
            result = self.set_mediaitem(item)
            return_info.append(result)
            if result.download_status == utils.DownloadStatus.READY:
                files_to_download.append(result)
            else:
                self.log_queue.put(f'{result.original_filename} - {result.download_status}')

        with ThreadPoolExecutor(max_workers=5) as executor:
            try:
                for _ in executor.map(self.download_mediaitem, files_to_download):
                    pass
            except KeyboardInterrupt:
                print('Downloading media items terminated. Run script again to continue.')
                with utils.disable_exception_traceback():
                    raise

        if 'nextPageToken' in response:
            self.db.set_user_option(self.user.id,
                'next-page-token', response['nextPageToken'])
        else:
            self.db.set_user_option(self.user.id, 'next-page-token', None)
            self.current_cycle += 1
            self.db.set_user_option(self.user.id, 'current-cycle', self.current_cycle)

        return return_info

    def crawl(self):
        """Crawl Google Photos and download media items."""
        self.global_crawler_lock.set()
        while True:
            if self.crawling_termination_time:
                if datetime.utcnow().timestamp() > self.crawling_termination_time:
                    break
            self._download_mediaitems_from_next_page()
        print('Terminated by watchdog.')
        self.global_crawler_lock.clear()

    def run(self):
        """Start/continue crawling Google Photos and download media items."""
        while self.global_crawler_lock.is_set():
            yield 'Waiting for termination of other crawling process.\n'
            time.sleep(3)
        self.crawling_termination_time = datetime.utcnow().timestamp() + 10
        threading.Thread(target=self.crawl, daemon=True).start()
        yield 'Start downloading...\n'
        while True:
            self.crawling_termination_time = datetime.utcnow().timestamp() + 10
            output = ''
            try:
                while not self.log_queue.empty():
                    output += str(self.log_queue.get_nowait()) + '\n'
            except queue.Empty:
                pass
            if output:
                yield output
            time.sleep(1)
