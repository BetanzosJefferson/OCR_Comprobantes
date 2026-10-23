from typing import Iterator

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from .config import DB_PATH

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.close()


def init_db() -> None:
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _agregar_columnas_faltantes()


def _agregar_columnas_faltantes() -> None:
    """create_all no modifica tablas existentes: añade las columnas nuevas para conservar la BD."""
    with engine.begin() as conn:
        for tabla in SQLModel.metadata.sorted_tables:
            existentes = {fila[1] for fila in conn.exec_driver_sql(f'PRAGMA table_info("{tabla.name}")')}
            if not existentes:
                continue
            for col in tabla.columns:
                if col.name in existentes:
                    continue
                tipo = col.type.compile(dialect=engine.dialect)
                sql = f'ALTER TABLE "{tabla.name}" ADD COLUMN "{col.name}" {tipo}'
                default = col.default.arg if col.default is not None and col.default.is_scalar else None
                if isinstance(default, str):
                    sql += " DEFAULT '" + default.replace("'", "''") + "'"
                elif isinstance(default, (int, float)):
                    sql += f" DEFAULT {default}"
                for fk in col.foreign_keys:
                    sql += f' REFERENCES "{fk.column.table.name}"("{fk.column.name}")'
                conn.exec_driver_sql(sql)
                if col.index:
                    conn.exec_driver_sql(
                        f'CREATE INDEX IF NOT EXISTS "ix_{tabla.name}_{col.name}" ON "{tabla.name}" ("{col.name}")'
                    )


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
