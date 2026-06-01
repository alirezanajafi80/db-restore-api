from sqlalchemy import Column, DateTime, String
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.inspection import inspect
from common.utils.timestamp  import DatetimeUtil


class BaseEntity(DeclarativeBase):
    id = Column(String(64), primary_key=True)

    deleted_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=DatetimeUtil.utc_now_datetime)
    updated_at = Column(DateTime(timezone=True), nullable=True, default=None)

    def to_dict(self):
        # Get the columns of the model
        columns = inspect(self.__class__).columns.keys()
        columns.remove('created_at')
        # Create a dictionary of column values
        public_vars = {column: getattr(self, column) for column in columns}
        return public_vars
