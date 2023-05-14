"""Defines class to work with database."""
import json
from typing import Any, Optional

from sqlalchemy import Table, Index, Column
from sqlalchemy import Integer, String
from sqlalchemy import MetaData
from sqlalchemy import create_engine, Engine, func
from sqlalchemy import select, insert, update, delete

class DB:
    """Definition of database tables."""
    metadata_obj: MetaData = MetaData()
    engine: Engine

    def __init__(self, database_url: str = 'sqlite:///db.sqlite3'):
        self.engine = create_engine(database_url)
        self._define_db_tables()
        self.metadata_obj.create_all(self.engine)

    def _define_db_tables(self) -> None:
        """Define required database tables."""
        self.album_table = Table(
            "albums",
            self.metadata_obj,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("user_id", Integer),
            Column("album_uid", String(255)),
            Column("title", String(1023)),
            Column("type", String(15)),
            Column("product_url", String(1023)),
            Column("cover_mediaitem_uid", Integer),
            Column("last_seen", Integer),
            Index("idx_albums_album_uid", "album_uid")
        )
        self.albumitem_table = Table(
            "albumitems",
            self.metadata_obj,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("album_uid", String(255)),
            Column("mediaitem_uid", String(255)),
            Column("last_seen", Integer),
            Index("idx_albumitems_album_uid", "album_uid"),
            Index("idx_albumitems_mediaitem_uid", "mediaitem_uid")
        )
        self.mediaitem_table = Table(
            "mediaitems",
            self.metadata_obj,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("user_id", Integer),
            Column("mediaitem_uid", String(255)),
            Column("type", String(15)),
            Column("mime_type", String(31)),
            Column("product_url", String(1023)),
            Column("creation_time", String(31)),
            Column("original_filename", String(1023)),
            Column("filename", String(1023)),
            Column("thumbnail", String(1023)),
            Column("width", Integer),
            Column("height", Integer),
            Column("last_seen", Integer),
            Index("idx_mediaitems_mediaitem_uid", "mediaitem_uid"),
            Index("idx_mediaitems_filename", "filename"),
            Index("idx_mediaitems_creation_time", "creation_time")
        )
        self.option_table = Table(
            "options",
            self.metadata_obj,
            Column("user_id", Integer),
            Column("key", String(63)),
            Column("value", String(16383)),
            Index("idx_options_key", "key")
        )
        self.user_table = Table(
            "users",
            self.metadata_obj,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("uid", String(63)),
            Column("email", String(63)),
            Column("image_url", String(255)),
            Index("idx_users_email", "email")
        )

    def get_user_option(self, user_id: int, key: str,
                        default_value: Optional[Any] = None) -> Optional[Any]:
        """Get user option."""
        with self.engine.connect() as connection:
            statement = (select(self.option_table)
                .where(self.option_table.c.user_id == user_id)
                .where(self.option_table.c.key == key)
                .limit(1))
            option_record = connection.execute(statement).first()
        if not option_record:
            return default_value
        try:
            value = json.loads(option_record.value)
        except json.decoder.JSONDecodeError:
            return default_value
        return value

    def set_user_option(self, user_id: int, key: str,
                        value: Optional[Any] = None) -> None:
        """Save user option."""
        if value is None:
            statement = (delete(self.option_table)
                .where(self.option_table.c.user_id == user_id)
                .where(self.option_table.c.key == key))
        else:
            encoded_value = json.dumps(value)
            with self.engine.connect() as connection:
                statement = (select(self.option_table)
                    .where(self.option_table.c.user_id == user_id)
                    .where(self.option_table.c.key == key)
                    .limit(1))
                option_record = connection.execute(statement).first()
            if not option_record:
                statement = insert(self.option_table).values(
                    user_id=user_id, key=key, value=encoded_value)
            else:
                statement = (update(self.option_table)
                    .where(self.option_table.c.user_id == user_id)
                    .where(self.option_table.c.key == key)
                    .values(value=encoded_value))
        with self.engine.connect() as connection:
            connection.execute(statement)
            connection.commit()

    def get_users(self) -> list[Any]:
        """Get users from DB."""
        with self.engine.connect() as connection:
            statement = select(self.user_table).order_by(self.user_table.c.id.asc())
            users = connection.execute(statement).all()
        return users

    def get_user_by(self, *,
                    id: Optional[int] = None,
                    uid: Optional[str] = None,
                    email: Optional[str] = None) -> Any:
        """Get user by field value (id, uid, email)."""
        if id is None and uid is None and email is None:
            raise AttributeError('One of the following arguments must be specified: id, uid, email.')
        statement = select(self.user_table)
        if id is not None:
            statement = statement.where(self.user_table.c.id == id)
        if uid is not None:
            statement = statement.where(self.user_table.c.uid == uid)
        if email is not None:
            statement = statement.where(self.user_table.c.email == email)
        statement = statement.limit(1)
        with self.engine.connect() as connection:
            user_record = connection.execute(statement).first()
        return user_record

    def add_user(self, **kwargs) -> int:
        """Insert new user and return its id."""
        with self.engine.connect() as connection:
            user_id = connection.execute(
                insert(self.user_table).values(**kwargs)).inserted_primary_key.id
            connection.commit()
        return user_id

    def get_user_mediaitems(self, *, user_id: int,
                            offset: Optional[int] = 0,
                            number: Optional[int] = 100) -> list[Any]:
        """Get user mediaitems from DB."""
        with self.engine.connect() as connection:
            statement = (select(self.mediaitem_table)
                .where(self.mediaitem_table.c.user_id == user_id)
                .order_by(self.mediaitem_table.c.creation_time.desc())
                .offset(offset)
                .limit(number))
            mediaitems = connection.execute(statement).all()
        return mediaitems

    def get_user_mediaitems_total(self, *, user_id: int) -> int:
        """Get total user mediaitems from DB."""
        with self.engine.connect() as connection:
            statement = (select(func.count()).select_from(self.mediaitem_table)
                .where(self.mediaitem_table.c.user_id == user_id))
            total = connection.execute(statement).scalar()
        return total

    def get_user_mediaitem_by(self, *, user_id: int,
                              id: Optional[int] = None,
                              mediaitem_uid: Optional[str] = None,
                              filename: Optional[str] = None) -> Any:
        """Get user media item from DB."""
        with self.engine.connect() as connection:
            statement = (select(self.mediaitem_table)
                .where(self.mediaitem_table.c.user_id == user_id))
            if id is not None:
                statement = statement.where(self.mediaitem_table.c.id == id)
            if mediaitem_uid is not None:
                statement = statement.where(self.mediaitem_table.c.mediaitem_uid == mediaitem_uid)
            if filename is not None:
                statement = statement.where(self.mediaitem_table.c.filename == filename)
            statement = statement.limit(1)
            mediaitem_record = connection.execute(statement).first()
        return mediaitem_record

    def add_mediaitem(self, **kwargs) -> int:
        """Insert new media item and return its id."""
        with self.engine.connect() as connection:
            id = connection.execute(
                insert(self.mediaitem_table).values(**kwargs)).inserted_primary_key.id
            connection.commit()
        return id

    def update_mediaitem(self, id: int, **kwargs):
        """Update media item."""
        with self.engine.connect() as connection:
            connection.execute(update(self.mediaitem_table)
                .where(self.mediaitem_table.c.id == id)
                .values(**kwargs))
            connection.commit()

    def get_user_album_by(self, *, user_id: int,
                          id: Optional[int] = None, 
                          album_uid: Optional[str] = None) -> Any:
        """Get user album from DB."""
        with self.engine.connect() as connection:
            statement = (select(self.album_table)
                .where(self.album_table.c.user_id == user_id))
            if id is not None:
                statement = statement.where(self.album_table.c.id == id)
            if album_uid is not None:
                statement = statement.where(self.album_table.c.album_uid == album_uid)
            statement = statement.limit(1)
            album_record = connection.execute(statement).first()
        return album_record

    def get_user_album_after(self, *, user_id: int, id: int) -> Any:
        """Get next user album after specified ID."""
        with self.engine.connect() as connection:
            statement = (select(self.album_table)
                .where(self.album_table.c.user_id == user_id)
                .where(self.album_table.c.id > id)
                .order_by(self.album_table.c.id))
            statement = statement.limit(1)
            album_record = connection.execute(statement).first()
        return album_record

    def update_album(self, id: int, **kwargs):
        """Update album."""
        with self.engine.connect() as connection:
            connection.execute(update(self.album_table)
                .where(self.album_table.c.id == id)
                .values(**kwargs))
            connection.commit()

    def add_album(self, **kwargs) -> int:
        """Insert new album and return its id."""
        with self.engine.connect() as connection:
            id = connection.execute(
                insert(self.album_table).values(**kwargs)).inserted_primary_key.id
            connection.commit()
        return id

    def get_albumitem_by(self, *,
                         id: Optional[int] = None, 
                         album_uid: Optional[str] = None,
                         mediaitem_uid: Optional[str] = None) -> Any:
        """Get user album from DB."""
        with self.engine.connect() as connection:
            statement = select(self.albumitem_table)
            if id is not None:
                statement = statement.where(self.albumitem_table.c.id == id)
            if album_uid is not None:
                statement = statement.where(self.albumitem_table.c.album_uid == album_uid)
            if mediaitem_uid is not None:
                statement = statement.where(self.albumitem_table.c.mediaitem_uid == mediaitem_uid)
            statement = statement.limit(1)
            albumitem_record = connection.execute(statement).first()
        return albumitem_record

    def update_albumitem(self, id: int, **kwargs):
        """Update album item."""
        with self.engine.connect() as connection:
            connection.execute(update(self.albumitem_table)
                .where(self.albumitem_table.c.id == id)
                .values(**kwargs))
            connection.commit()

    def add_albumitem(self, **kwargs) -> int:
        """Insert new album and return its id."""
        with self.engine.connect() as connection:
            id = connection.execute(
                insert(self.albumitem_table).values(**kwargs)).inserted_primary_key.id
            connection.commit()
        return id
