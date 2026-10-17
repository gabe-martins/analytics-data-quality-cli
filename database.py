"""Conexões com os bancos de dados suportados."""

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

from cli_helpers import describe

DB_TYPES = ("postgresql", "mysql", "sqlite", "mssql", "oracle", "databricks")


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

    if db_type == "oracle":
        return URL.create(drivername=DRIVERS[db_type], username=creds["username"],
                          password=creds["password"], host=creds["hostname"],
                          port=creds.get("port") or 1521,
                          query={"service_name": creds["database"]})

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


def prepare_read_session(conn, db_type):
    """Configura conexões novas de consulta; nunca chamar em transações de escrita."""
    cursor = conn.cursor()
    try:
        if db_type == "postgresql":
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '30000ms'")
        elif db_type == "mysql":
            cursor.execute("START TRANSACTION READ ONLY")
        elif db_type == "sqlite":
            cursor.execute("PRAGMA query_only = ON")
        elif db_type == "mssql":
            conn.timeout = 30
            cursor.execute("SET LOCK_TIMEOUT 15000")
        elif db_type == "oracle":
            driver = getattr(conn, "driver_connection", conn)
            driver.call_timeout = 30000
            cursor.execute("SET TRANSACTION READ ONLY")
    finally:
        cursor.close()


def connect(creds):
    """Abre a conexão e testa. Retorna uma conexão DB-API (com .cursor()) ou None."""
    conn = None
    try:
        from db_adapters import get_adapter
        get_adapter(creds["type"])
        if creds["type"] == "mssql":
            conn = connect_mssql(creds)
        else:
            conn = connect_sqlalchemy(creds)

        cursor = conn.cursor()
        cursor.execute(TEST_QUERIES.get(creds["type"], "SELECT 1"))
        cursor.fetchall()
        cursor.close()
        conn.rollback()
        prepare_read_session(conn, creds["type"])

        print(f"Connected to {describe(creds)} successfully!")
        return conn
    except ModuleNotFoundError as e:
        print(f"Driver não instalado: {e.name}")
    except Exception as e:  # cada driver tem sua hierarquia de exceções
        print(f"Falha na conexão: {type(e).__name__}")

    if conn is not None:
        conn.close()

    return None
