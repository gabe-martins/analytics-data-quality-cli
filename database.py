"""Conexões com os bancos de dados suportados."""

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

from cli_helpers import describe

DB_TYPES = ("postgresql", "mysql", "sqlite", "mssql", "oracle")


DRIVERS = {
    "postgresql": "postgresql+psycopg2",  # pip install psycopg2-binary
    "mysql": "mysql+pymysql",             # pip install pymysql
    "sqlite": "sqlite",                   # já vem com o Python
    "oracle": "oracle+oracledb",          # pip install oracledb
    # mssql não passa pelo SQLAlchemy: usa o driver nativo mssql-python (pip install mssql-python)
}


TEST_QUERIES = {"oracle": "SELECT 1 FROM DUAL"}


def build_url(creds):
    db_type = creds["type"]

    if db_type == "sqlite":
        return URL.create(drivername=DRIVERS[db_type], database=creds["database"])

    # URL.create escapa corretamente caracteres especiais na senha (@, :, / ...)
    return URL.create(
        drivername=DRIVERS[db_type],
        username=creds["username"],
        password=creds["password"],
        host=creds["hostname"],
        port=creds["port"],
        database=creds["database"],
    )


def odbc_escape(value):
    """Protege valores com caracteres especiais (; { } = etc.) na connection string."""
    value = str(value)
    if any(c in value for c in ";{}=") or value != value.strip():
        return "{" + value.replace("}", "}}") + "}"
    return value


def connect_mssql(creds):
    """SQL Server com o driver nativo da Microsoft (mssql-python)."""
    import mssql_python  # import tardio: só exige a lib quando você usa SQL Server

    server = creds["hostname"]
    if creds["port"]:
        server = f"{server},{creds['port']}"  # no SQL Server a porta vai após vírgula

    connection_string = (
        f"SERVER={odbc_escape(server)};"
        f"DATABASE={odbc_escape(creds['database'])};"
        f"UID={odbc_escape(creds['username'])};"
        f"PWD={odbc_escape(creds['password'])};"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"  # útil em home lab com cert autoassinado
    )
    return mssql_python.connect(connection_string)


def connect_sqlalchemy(creds):
    """Demais bancos, via SQLAlchemy. Retorna uma conexão DB-API."""
    # NullPool: ao dar close() a conexão é realmente fechada
    engine = create_engine(build_url(creds), poolclass=NullPool)
    return engine.raw_connection()


def connect(creds):
    """Abre a conexão e testa. Retorna uma conexão DB-API (com .cursor()) ou None."""
    try:
        if creds["type"] == "mssql":
            conn = connect_mssql(creds)
        else:
            conn = connect_sqlalchemy(creds)

        cursor = conn.cursor()
        cursor.execute(TEST_QUERIES.get(creds["type"], "SELECT 1"))
        cursor.fetchall()
        cursor.close()

        print(f"Connected to {describe(creds)} successfully!")
        return conn
    except ModuleNotFoundError as e:
        print(f"Driver not installed: {e}")
    except Exception as e:  # cada driver tem sua hierarquia de exceções
        print(f"Connection failed: {e}")

    return None
