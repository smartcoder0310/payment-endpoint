"""The database handle, and the declarative base every model is built on.

Both live here rather than under app/models/ so that importing them cannot pull
the models in: the models import this module, and a cycle would follow.
"""

import datetime as dt

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, registry


class Model(DeclarativeBase):
    """Base class for all mapped classes."""

    # Every timestamp in the schema is TIMESTAMPTZ, so every `Mapped[datetime]`
    # must be one too. Without this, SQLAlchemy would map them to a naive
    # TIMESTAMP, and a value on its way into the database would lose its offset
    # to whatever time zone the server happens to be set to.
    registry = registry(type_annotation_map={dt.datetime: DateTime(timezone=True)})


db = SQLAlchemy(model_class=Model)
