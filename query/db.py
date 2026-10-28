import os

from sqlalchemy import create_engine

# Local mode: set DATABASE_URL (e.g. postgresql+pg8000://rag:rag@localhost:5432/rag).
# Cloud mode: leave DATABASE_URL unset and set INSTANCE_CONNECTION_NAME and DB_USER.
DATABASE_URL = os.environ.get("DATABASE_URL")
DB_NAME = os.environ.get("DB_NAME", "rag")

_engine = None


def _cloud_engine():
    from google.cloud.sql.connector import Connector, IPTypes

    instance = os.environ["INSTANCE_CONNECTION_NAME"]  # project:region:instance
    db_user = os.environ["DB_USER"]                    # SERVICE@PROJECT_ID.iam
    connector = Connector()

    def _getconn():
        return connector.connect(
            instance,
            "pg8000",
            user=db_user,
            db=DB_NAME,
            enable_iam_auth=True,
            ip_type=IPTypes.PUBLIC,
        )

    return create_engine("postgresql+pg8000://", creator=_getconn, pool_size=2)


def get_engine():
    global _engine
    if _engine is None:
        if DATABASE_URL:
            _engine = create_engine(DATABASE_URL, pool_size=2)
        else:
            _engine = _cloud_engine()
    return _engine
