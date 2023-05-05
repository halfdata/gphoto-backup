"""Defines class to work with database."""
import json
from typing import Any, Optional

from sqlalchemy import Table, Index, Column
from sqlalchemy import Integer, String
from sqlalchemy import MetaData
from sqlalchemy import create_engine, Engine
from sqlalchemy import select, insert, update, delete

class DB:
    """Definition of database tables."""
    metadata_obj: MetaData = MetaData()
    engine: Engine = create_engine("sqlite:///db.sqlite3")

    def __init__(self):
        self._define_db_tables()
        self.metadata_obj.create_all(self.engine)

    def _define_db_tables(self) -> None:
        """Define required database tables."""
        self.user_table = Table(
            "users",
            self.metadata_obj,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("uid", String(63)),
            Column("email", String(63)),
            Column("image_url", String(255)),
            Index("idx_email", "email")
        )
        self.option_table = Table(
            "options",
            self.metadata_obj,
            Column("user_id", Integer),
            Column("key", String(63)),
            Column("value", String(16383)),
            Index("idx_key", "key")
        )
        self.media_table = Table(
            "media",
            self.metadata_obj,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("user_id", Integer),
            Column("mediaitem_id", String(255)),
            Column("type", String(15)),
            Column("mime_type", String(31)),
            Column("product_url", String(1023)),
            Column("creation_time", String(31)),
            Column("original_filename", String(1023)),
            Column("filename", String(1023)),
            Column("thumbnail", String(1023)),
            Index("idx_mediaitem_id", "mediaitem_id"),
            Index("idx_filename", "filename"),
            Index("idx_creation_time", "creation_time")
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

    def get_user_mediaitem_by(self, *, user_id: int,
                              mediaitem_id: Optional[str] = None,
                              filename: Optional[str] = None) -> Any:
        """Get user media item from DB."""
        with self.engine.connect() as connection:
            statement = (select(self.media_table)
                .where(self.media_table.c.user_id == user_id))
            if mediaitem_id is not None:
                statement = statement.where(self.media_table.c.mediaitem_id == mediaitem_id)
            if filename is not None:
                statement = statement.where(self.media_table.c.filename == filename)
            statement = statement.limit(1)
            mediaitem_record = connection.execute(statement).first()
        return mediaitem_record

    def add_mediaitem(self, **kwargs) -> int:
        """Insert new media item and return its id."""
        with self.engine.connect() as connection:
            mediaitem_id = connection.execute(
                insert(self.media_table).values(**kwargs)).inserted_primary_key.id
            connection.commit()
        return mediaitem_id

    def update_mediaitem(self, id: int, **kwargs):
        """Update media item."""
        with self.engine.connect() as connection:
            connection.execute(update(self.media_table)
                .where(self.media_table.c.id == id)
                .values(**kwargs))
            connection.commit()
