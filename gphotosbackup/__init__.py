"""Main class to use Google Photos Backup."""
import os
import queue
import threading
import time

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable, Optional

import google.oauth2.credentials
import googleapiclient.discovery

from . import errors, models, utils

THUMBNAIL_SIZE = 640


class GPhotosBackup:
    """Class that handles creating backups."""
    storage_path: str
    user: Any
    credentials: google.oauth2.credentials.Credentials
    gphoto_resource: googleapiclient.discovery.Resource
    update_credentials_callback: Callable
    db: models.DB
    log_queue: queue.SimpleQueue
    global_crawler_lock: threading.Event
    current_cycle: int
    crawling_termination_time: Optional[float] = None
    download_thumbnails: bool = True

    def __init__(self, *,
                 global_crawler_lock: threading.Event,
                 user_id: str,
                 credentials: google.oauth2.credentials.Credentials,
                 update_credentials_callback: Callable,
                 db: models.DB,
                 storage_path: str = 'archive'):
        self.global_crawler_lock = global_crawler_lock
        self.credentials = credentials
        self.update_credentials_callback = update_credentials_callback
        self.db = db
        self.storage_path = storage_path
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
        abs_filename = os.path.abspath(os.path.join(self.storage_path,
                                                    self.user.email,
                                                    filename))
        return os.path.exists(abs_filename)

    def generate_filename(self, item: dict[str, Any],
                          is_thumbnail: bool = False) -> Optional[str]:
        """Generate filename based on media item data."""
        folder = 'other'
        creation_time = item.get('mediaMetadata', {}).get('creationTime', '')
        if creation_time:
            time_parts = creation_time.split('-')
            if len(time_parts) > 1:
                folder = os.path.join(time_parts[0], time_parts[1])
        abs_path_folder = os.path.abspath(os.path.join(self.storage_path,
                                                       self.user.email,
                                                       folder))
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
                                                  mediaitem_uid=item['id'])
        item_type = item['mimeType'].split('/')[0].lower()
        creation_time = item.get('mediaMetadata', {}).get('creationTime', '')
        width = item.get('mediaMetadata', {}).get('width')
        height = item.get('mediaMetadata', {}).get('height')
        download_info = utils.DownloadInfo(
            id=0,
            mediaitem_uid=item['id'],
            creation_time=creation_time,
            item_type=item_type,
            base_url=item['baseUrl'],
            filename='',
            original_filename=item['filename'],
            thumbnail='',
            download_status=utils.DownloadStatus.ITEM_AND_THUMBNAIL
        )

        if item_type == 'video':
            status = item.get('mediaMetadata', {}).get('video', {}).get('status', None)
            if status != 'READY':
                download_info.download_status = utils.DownloadStatus.NOT_READY
                return download_info

        if not mediaitem:
            filename = self.generate_filename(item)
            # TODO: Assume that we don't have files *.<video_ext>.jpg
            thumbnail = filename + ('.jpg' if item_type == 'video' else '')
            item_id = self.db.add_mediaitem(
                user_id=self.user.id,
                last_seen=self.current_cycle,
                mediaitem_uid=item['id'],
                type=item_type,
                mime_type=item['mimeType'],
                product_url=item['productUrl'],
                creation_time=creation_time,
                original_filename=item['filename'],
                filename=filename,
                thumbnail=thumbnail,
                width=width,
                height=height)
            download_info.id = item_id
            download_info.filename = filename
            download_info.thumbnail = thumbnail
            return download_info

        download_info.id = mediaitem.id
        if not mediaitem.filename:
            filename = self.generate_filename(item)
            # TODO: Assume that we don't have files *.<video_ext>.jpg
            thumbnail = filename + ('.jpg' if item_type == 'video' else '')
            self.db.update_mediaitem(id=mediaitem.id,
                                     filename=filename,
                                     thumbnail=thumbnail,
                                     last_seen=self.current_cycle)
            download_info.filename = filename
            download_info.thumbnail = thumbnail
            return download_info

        thumbnail = mediaitem.thumbnail
        if not thumbnail:
            # TODO: Assume that we don't have files *.<video_ext>.jpg
            thumbnail = mediaitem.filename + ('.jpg' if item_type == 'video' else '')
        self.db.update_mediaitem(id=mediaitem.id,
                                 thumbnail=thumbnail,
                                 last_seen=self.current_cycle)
        download_info.filename = mediaitem.filename
        download_info.thumbnail = thumbnail

        abs_path_filename = os.path.abspath(os.path.join(self.storage_path,
                                                         self.user.email,
                                                         mediaitem.filename))
        if not self.file_exists(abs_path_filename):
            return download_info

        abs_path_thumbnail = os.path.abspath(os.path.join(self.storage_path,
                                                          self.user.email,
                                                          utils.THUMBNAILS_FOLDER,
                                                          thumbnail))
        if not self.file_exists(abs_path_thumbnail) and self.download_thumbnails:
            download_info.download_status = utils.DownloadStatus.THUMBNAIL_ONLY
        else:
            download_info.download_status = utils.DownloadStatus.ALREADY_DOWNLOADED

        return download_info

    def handle_mediaitem(self, download_info: utils.DownloadInfo) -> None:
        """Download media item."""
        print(f'Processing: {download_info.filename}')
        if download_info.download_status == utils.DownloadStatus.NOT_READY:
            self.log_queue.put(f'{download_info.original_filename} - not ready '
                               'for downloading')
            return
        if download_info.download_status == utils.DownloadStatus.ALREADY_DOWNLOADED:
            self.log_queue.put(f'{download_info.original_filename} - aready '
                               'downloaded')
            return
        filetime = utils.convert_iso_to_timestamp(download_info.creation_time)
        if download_info.download_status == utils.DownloadStatus.ITEM_AND_THUMBNAIL:
            filename_url = (f'{download_info.base_url}=d'
                            f'{"v" if download_info.item_type == "video" else ""}')
            full_filename = os.path.abspath(os.path.join(self.storage_path,
                self.user.email, download_info.filename))
            os.makedirs(os.path.dirname(full_filename), exist_ok=True)
            start_downloading_time = time.time()
            status, error = utils.download_file(url=filename_url,
                filename=full_filename, filetime = filetime)
            end_downloading_time = time.time()
            if status == 404:
                self.log_queue.put(f'{download_info.original_filename} - not available')
                return
            elif status == 429:
                print('The rate limit for this service has been exceeded. Try again in 24 hours.')
                self.log_queue.put('The rate limit for this service has been exceeded. '
                                   'Try again in 24 hours.')
                with utils.disable_exception_traceback():
                    raise error
            elif status != 200:
                with utils.disable_exception_traceback():
                    raise error
            self.log_queue.put(f'{download_info.original_filename} - file downloaded '
                               f'({(end_downloading_time - start_downloading_time):.3f}s)')

        thumbnail_url = (f'{download_info.base_url}=w{THUMBNAIL_SIZE}-h{THUMBNAIL_SIZE}'
                         f'{"-no" if download_info.item_type == "video" else ""}')
        full_thumbnail = os.path.abspath(os.path.join(self.storage_path,
            self.user.email, utils.THUMBNAILS_FOLDER, download_info.thumbnail))
        os.makedirs(os.path.dirname(full_thumbnail), exist_ok=True)
        status, error = utils.download_file(url=thumbnail_url,
                                            filename=full_thumbnail,
                                            filetime = filetime)
        if status != 200:
            with utils.disable_exception_traceback():
                raise error
        if download_info.download_status == utils.DownloadStatus.THUMBNAIL_ONLY:
            self.log_queue.put(f'{download_info.original_filename} - thumbnail downloaded')


    def download_mediaitems_from_next_page(self, album: Optional[str] = None) -> bool:
        """Reads next 10 media items from Google Photos and download them.
        
        Returns: True, if downloading of all items from all pages are finished.
        """
        page_token = self.db.get_user_option(self.user.id, 'next-page-token')
        try:
            if album:
                body = {
                    'pageSize': 10,
                    'albumId': album,
                    'pageToken': page_token
                }
                response = self.gphoto_resource.mediaItems().search(
                    body=body).execute()
            else:
                response = self.gphoto_resource.mediaItems().list(
                    pageSize=10, pageToken=page_token).execute()
            self.update_credentials_callback()
        except KeyboardInterrupt:
            print('Downloading media items terminated. Run script again to continue.')
            with utils.disable_exception_traceback():
                raise
        if 'mediaItems' not in response and 'nextPageToken' not in response:
            print('No mediaItems and nextPageToken nodes in response.')
            raise errors.InvalidResponse()
        if 'mediaItems' in response:
            files_to_download = []
            for item in response['mediaItems']:
                result = self.set_mediaitem(item)
                if album:
                    albumitem = self.db.get_albumitem_by(album_uid=album,
                                                        mediaitem_uid=result.mediaitem_uid)
                    if albumitem:
                        self.db.update_albumitem(id=albumitem.id,
                                                last_seen=self.current_cycle)
                    else:
                        self.db.add_albumitem(album_uid=album,
                                            mediaitem_uid=result.mediaitem_uid,
                                            last_seen=self.current_cycle)
                files_to_download.append(result)

            with ThreadPoolExecutor(max_workers=5) as executor:
                try:
                    for _ in executor.map(self.handle_mediaitem, files_to_download):
                        pass
                except KeyboardInterrupt:
                    print('Downloading media items terminated. Run script again to continue.')
                    with utils.disable_exception_traceback():
                        raise

        if 'nextPageToken' in response:
            self.db.set_user_option(self.user.id,
                'next-page-token', response['nextPageToken'])
            return False
        else:
            self.db.set_user_option(self.user.id, 'next-page-token', None)

        return True

    def download_albums_from_next_page(self) -> bool:
        """Reads next 50 albums from Google Photos and save them into DB.
        
        Returns: True, if downloading of all items from all pages are finished.
        """
        page_token = self.db.get_user_option(self.user.id, 'next-page-token')
        try:
            response = self.gphoto_resource.albums().list(
                pageSize=50, pageToken=page_token).execute()
            self.update_credentials_callback()
        except KeyboardInterrupt:
            print('Downloading albums terminated. Run script again to continue.')
            with utils.disable_exception_traceback():
                raise
        if 'albums' not in response:
            print('No albums node in response.')
            raise errors.InvalidResponse()
        for item in response['albums']:
            album = self.db.get_user_album_by(user_id=self.user.id,
                                              album_uid=item['id'])
            if not album:
                self.db.add_album(user_id=self.user.id,
                                  album_uid=item['id'],
                                  title=item['title'],
                                  type='album',
                                  product_url=item['productUrl'],
                                  cover_mediaitem_uid=item['coverPhotoMediaItemId'],
                                  last_seen=self.current_cycle)
                self.log_queue.put(f'Album "{item["title"]}" added')
            else:
                self.db.update_album(id=album.id,
                                     title=item['title'],
                                     last_seen=self.current_cycle)
                self.log_queue.put(f'Album "{item["title"]}" updated')

        if 'nextPageToken' in response:
            self.db.set_user_option(self.user.id,
                'next-page-token', response['nextPageToken'])
            return False
        else:
            self.db.set_user_option(self.user.id, 'next-page-token', None)

        return True

    def crawl(self):
        """Crawl Google Photos and download media items."""
        self.global_crawler_lock.set()
        try:
            backup_stage = utils.BackupStage(
                self.db.get_user_option(self.user.id,
                    'backup-stage', utils.BackupStage.MEDIA_ITEM.value))
        except ValueError:
            backup_stage = utils.BackupStage.MEDIA_ITEM
        while True:
            if self.crawling_termination_time:
                if datetime.utcnow().timestamp() > self.crawling_termination_time:
                    break
            if backup_stage == utils.BackupStage.MEDIA_ITEM:
                switch_stage = self.download_mediaitems_from_next_page()
                if switch_stage:
                    backup_stage = utils.BackupStage.ALBUM
                    self.db.set_user_option(self.user.id, 'backup-stage', backup_stage.value)
            elif backup_stage == utils.BackupStage.ALBUM:
                switch_stage = self.download_albums_from_next_page()
                if switch_stage:
                    album = self.db.get_user_album_after(user_id=self.user.id, id=0)
                    if album:
                        self.db.set_user_option(self.user.id, 'backup-stage-args', album.id)
                        backup_stage = utils.BackupStage.ALBUM_ITEM
                        self.db.set_user_option(self.user.id, 'backup-stage', backup_stage.value)
                    else:
                        backup_stage = utils.BackupStage.END
            elif backup_stage == utils.BackupStage.ALBUM_ITEM:
                album_id = self.db.get_user_option(self.user.id, 'backup-stage-args', 0)
                if not album_id:
                    album = self.db.get_user_album_after(user_id=self.user.id,
                                                         id=0)
                else:
                    album = self.db.get_user_album_by(user_id=self.user.id,
                                                      id=album_id)
                    if not album:
                        album = self.db.get_user_album_after(user_id=self.user.id,
                                                             id=album_id)
                if album:
                    switch_stage = self.download_mediaitems_from_next_page(
                        album=album.album_uid)
                    if switch_stage:
                        album = self.db.get_user_album_after(user_id=self.user.id,
                                                             id=album.id)
                        if album:
                            self.db.set_user_option(self.user.id,
                                                    'backup-stage-args',
                                                    album.id)
                        else:
                            backup_stage = utils.BackupStage.END
                else:
                    backup_stage = utils.BackupStage.END
            else:
                raise errors.UnknownBackupStage('Unknown backup stage.')
            
            if backup_stage == utils.BackupStage.END:
                backup_stage = utils.BackupStage.MEDIA_ITEM
                self.db.set_user_option(self.user.id, 'backup-stage', backup_stage.value)
                self.db.set_user_option(self.user.id, 'backup-stage-args', None)
                self.current_cycle += 1
                self.db.set_user_option(self.user.id, 'current-cycle', self.current_cycle)

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
