"""Main class to use Google Photo Backup."""
import http
import httplib2
import json
import os
import requests
import shutil
import socket
import sys

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import create_engine, Engine
from sqlalchemy import MetaData
from sqlalchemy import Table, Index, Column
from sqlalchemy import Integer, String
from sqlalchemy import select, insert, update, delete

import google.oauth2.credentials
import googleapiclient.discovery

SCOPES = ['https://www.googleapis.com/auth/photoslibrary.readonly']
API_SERVICE_NAME = 'photoslibrary'
API_VERSION = 'v1'


@contextmanager
def disable_exception_traceback():
    """All traceback information is suppressed."""
    default_value = getattr(sys, "tracebacklimit", 1000)
    sys.tracebacklimit = 0
    yield
    sys.tracebacklimit = default_value


class GPhotoBackup:
    """Class that handles creating backups."""
    STORAGE_PATH: str = 'archive'
    metadata_obj: MetaData = MetaData()
    engine: Engine = create_engine("sqlite:///db.sqlite3")
    option_table: Table
    media_table: Table

    def __init__(self) -> None:
        self._define_db_tables()
        self.metadata_obj.create_all(self.engine)

    def _define_db_tables(self) -> None:
        """Define required database tables."""
        self.option_table = Table(
            "options",
            self.metadata_obj,
            Column("key", String(63)),
            Column("value", String(16383)),
            Index("idx_key", "key")
        )
        self.media_table = Table(
            "media",
            self.metadata_obj,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("mediaitem_id", String(255)),
            Column("type", String(15)),
            Column("mime_type", String(31)),
            Column("product_url", String(1023)),
            Column("creation_time", String(31)),
            Column("original_filename", String(1023)),
            Column("filename", String(1023)),
            Index("idx_mediaitem_id", "mediaitem_id"),
            Index("idx_filename", "filename"),
            Index("idx_creation_time", "creation_time")
        )

    def get_option(self, key: str, default_value: Optional[Any] = None) -> Optional[Any]:
        """Get option."""
        with self.engine.connect() as connection:
            statement = (select(self.option_table)
                .where(self.option_table.c.key == key).limit(1))
            option_record = connection.execute(statement).first()
        if not option_record:
            return default_value
        try:
            value = json.loads(option_record.value)
        except json.decoder.JSONDecodeError:
            return default_value
        return value

    def set_option(self, key: str, value: Optional[Any] = None) -> None:
        """Save option."""
        if value is None:
            statement = delete(self.option_table).where(self.option_table.c.key == key)
        else:
            with self.engine.connect() as connection:
                statement = (select(self.option_table)
                    .where(self.option_table.c.key == key).limit(1))
                option_record = connection.execute(statement).first()
            encoded_value = json.dumps(value)    
            if not option_record:
                statement = insert(self.option_table).values(key=key, value=encoded_value)
            else:
                statement = (update(self.option_table)
                    .where(self.option_table.c.key == key)
                    .values(key=key, value=encoded_value))
        with self.engine.connect() as connection:
            connection.execute(statement)
            connection.commit()

    def get_credentials(self) -> Optional[google.oauth2.credentials.Credentials]:
        """Read Google Photo Credentials."""
        credentials_dict = self.get_option('google-photo-credentials')
        if not credentials_dict:
            return None
        return google.oauth2.credentials.Credentials(**credentials_dict)

    def set_credentials(self, credentials: google.oauth2.credentials.Credentials) -> None:
        """Save Google Photo Credentials."""
        credential_value = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes}
        self.set_option('google-photo-credentials', credential_value)

    def check_credentials(self):
        """Check if credentials exist and are valid.
        
        TODO: Organize handling exceptions more accurate way.
        """
        credentials = self.get_credentials()
        if not credentials:
            return False
        try:
            gphoto = googleapiclient.discovery.build(API_SERVICE_NAME,
                API_VERSION,
                credentials=credentials,
                static_discovery=False)
            response = gphoto.mediaItems().list(pageSize=1).execute()
            self.set_credentials(credentials)
        except Exception as error:
            print(error)
            return False
        return True

    def get_mediaitem(self, *, mediaitem_id: Optional[str] = None,
                      filename: Optional[str] = None) -> Any:
        """Get media item from DB."""
        with self.engine.connect() as connection:
            statement = select(self.media_table)
            if mediaitem_id is not None:
                statement = statement.where(self.media_table.c.mediaitem_id == mediaitem_id)
            if filename is not None:
                statement = statement.where(self.media_table.c.filename == filename)
            statement = statement.limit(1)
            return connection.execute(statement).first()

    def file_exists(self, filename: str) -> bool:
        """Check if file exists."""
        abs_filename = os.path.abspath(os.path.join(self.STORAGE_PATH, filename))
        return os.path.exists(abs_filename)

    def generate_filename(self, item: dict[str, Any]) -> Optional[str]:
        """Generate filename based on media item data."""
        folder = 'other'
        creation_time = item.get('mediaMetadata', {}).get('creationTime', '')
        if creation_time:
            time_parts = creation_time.split('-')
            if len(time_parts) > 1:
                folder = os.path.join(time_parts[0], time_parts[1])
        abs_path_folder = os.path.abspath(os.path.join(self.STORAGE_PATH, folder))
        try:
            os.makedirs(abs_path_folder, exist_ok=True)
        except OSError:
            return None
        filename = item['filename']
        i = 2
        while (os.path.exists(os.path.join(abs_path_folder, filename)) or
            self.get_mediaitem(filename=filename)):
            filename_parts = item['filename'].rsplit('.', 1)
            filename_parts[0] += f'-{i}'
            filename = '.'.join(filename_parts)
            i += 1
        return os.path.join(folder, filename)

    def convert_creation_time(self, creation_time: str) -> Optional[int]:
        """Convert creation time to unix timestamp."""
        if not creation_time:
            return None
        return datetime.fromisoformat(creation_time[:19]).timestamp()


    def set_mediaitem(self, item: dict[str, Any]) -> None:
        """Save media item into DB."""
        mediaitem = self.get_mediaitem(mediaitem_id=item['id'])
        item_type = item['mimeType'].split('/')[0]
        creation_time = item.get('mediaMetadata', {}).get('creationTime', '')

        if item_type == 'video':
            status = item.get('mediaMetadata', {}).get('video', {}).get('status', None)
            if status != 'READY':
                print(f'{item["filename"]} - not ready')
                return None

        if not mediaitem:
            filename=self.generate_filename(item)
            with self.engine.connect() as connection:
                item_id = connection.execute(
                    insert(self.media_table).values(
                        mediaitem_id=item['id'],
                        type=item_type,
                        mime_type=item['mimeType'],
                        product_url=item['productUrl'],
                        creation_time=creation_time,
                        original_filename=item['filename'],
                        filename=filename)).inserted_primary_key.id
                connection.commit()
            return {'id': item_id,
                    'creation_time': creation_time,
                    'item_type': item_type,
                    'base_url': item['baseUrl'],
                    'filename': filename}

        if not mediaitem.filename:
            filename=self.generate_filename(item)
            with self.engine.connect() as connection:
                connection.execute(update(self.media_table)
                    .where(self.media_table.c.id == mediaitem.id)
                    .values(filename=filename))
                connection.commit()
            return {'id': mediaitem.id,
                    'creation_time': creation_time,
                    'item_type': item_type,
                    'base_url': item['baseUrl'],
                    'filename': filename}

        abs_path_folder = os.path.dirname(
            os.path.abspath(os.path.join(self.STORAGE_PATH, mediaitem.filename)))
        os.makedirs(abs_path_folder, exist_ok=True)        
        os.path.abspath(os.path.join(self.STORAGE_PATH, mediaitem.filename))
        if not self.file_exists(mediaitem.filename):
            return {'id': mediaitem.id,
                    'creation_time': creation_time,
                    'item_type': item_type,
                    'base_url': item['baseUrl'],
                    'filename': mediaitem.filename}
        
        print(f'{mediaitem.filename} - already downloaded')
        return None

    def download_mediaitem(self, *, creation_time: str, item_type: str,
                           base_url: str, filename: str, **kwargs) -> None:
        """Download media item."""
        print(f'{filename} - downloading')
        url = f'{base_url}=d{"v" if item_type == "video" else ""}'
        full_filename = os.path.abspath(os.path.join(self.STORAGE_PATH, filename))
        filetime = self.convert_creation_time(creation_time)
        try:
            with requests.get(url, timeout=(5, None), stream=True) as r:
                r.raise_for_status()
                with open(full_filename, 'wb') as f:
                    shutil.copyfileobj(r.raw, f)
                os.utime(full_filename, times=(filetime, filetime))
        except Exception:
            if os.path.exists(full_filename):
                print(f'{filename} - failed to download')
                os.remove(full_filename)
            with disable_exception_traceback():
                raise

    def start(self):
        """Start/continue crawling Google Photo."""
        credentials = self.get_credentials()
        if not credentials:
            print('No credentials to access Google Photo were found. '
                  'Please generate them.')
            return
        try:
            gphoto = googleapiclient.discovery.build(API_SERVICE_NAME,
                API_VERSION,
                credentials=credentials,
                static_discovery=False)
        except (httplib2.error.ServerNotFoundError, socket.gaierror):
            print('Can not connect to Google Photo. '
                  'Please check internet connection.')
            return

        page_token = self.get_option('next-page-token')
        i = 0
        while True:
            try:
                response = gphoto.mediaItems().list(pageSize=10,
                                                    pageToken=page_token).execute()
                self.set_credentials(credentials)
            except googleapiclient.errors.HttpError as error:
                print(error)
                return
            except google.auth.exceptions.RefreshError as error:
                print('Invalid credentials to access Google Photo. '
                      'Please generate them.')
                return
            except (http.client.RemoteDisconnected, socket.gaierror):
                print('Can not connect to Google Photo. '
                      'Please check internet connection.')
                return
            except KeyboardInterrupt:
                print('Downloading media items terminated. Run script again to continue.')
                with disable_exception_traceback():
                    raise
            if 'mediaItems' not in response:
                print('No media items in response.')
                return
            files_to_download = []
            for item in response['mediaItems']:
                i += 1
                result = self.set_mediaitem(item)
                if result:
                    files_to_download.append(result)

            with ThreadPoolExecutor(max_workers=5) as executor:
                try:
                    for _ in executor.map(lambda kwargs: self.download_mediaitem(**kwargs),
                                          files_to_download):
                        pass
                except KeyboardInterrupt:
                    print('Downloading media items terminated. Run script again to continue.')
                    with disable_exception_traceback():
                        raise

            if 'nextPageToken' in response:
                self.set_option('next-page-token', response['nextPageToken'])
                page_token = response['nextPageToken']
            else:
                self.set_option('next-page-token', None)
                print('Finished.')
                break
