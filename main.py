import os
from getpass import getpass
from pathlib import Path

import yaml  # pip install pyyaml
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

CONFIG_PATH = Path("credentials.yaml")

DB_TYPES = ("postgresql", "mysql", "sqlite", "mssql", "oracle")

# Driver Python usado por cada tipo de banco
DRIVERS = {
    "postgresql": "postgresql+psycopg2",  # pip install psycopg2-binary
    "mysql": "mysql+pymysql",             # pip install pymysql
    "sqlite": "sqlite",                   # já vem com o Python
    "mssql": "mssql+pyodbc",              # pip install pyodbc (+ ODBC Driver 18 instalado no SO)
    "oracle": "oracle+oracledb",          # pip install oracledb
}

# Query mínima de teste (Oracle exige FROM DUAL)
TEST_QUERIES = {"oracle": "SELECT 1 FROM DUAL"}


# ---------------------------------------------------------------- entrada
def get_database():
    print("Select a database type:")

    for i, db_type in enumerate(DB_TYPES, start=1):
        print(f"{i}. {db_type}")

    while True:
        try:
            choice = int(input("Enter your choice: "))
            if 1 <= choice <= len(DB_TYPES):
                return DB_TYPES[choice - 1]
            print("Invalid choice. Please try again.")
        except ValueError:
            print("Invalid input. Please enter a number.")


def get_db_credentials(db_type):
    if db_type == "sqlite":
        # SQLite é um arquivo local: não tem host, porta nem login
        creds = {
            "type": db_type,
            "hostname": None,
            "port": None,
            "username": None,
            "password": None,
            "database": input("Enter database file path (e.g. app.db): "),
        }
    else:
        hostname = input("Enter hostname: ")
        port = input("Enter port: ")
        creds = {
            "type": db_type,
            "hostname": hostname,
            "port": int(port) if port.strip() else None,
            "username": input("Enter username: "),
            "password": getpass("Enter password: "),  # não exibe a senha
            "database": input("Enter database name (or service name): "),
        }

    opt_in = input("Would you like to save the credentials? (y/n) ")
    if opt_in.strip().lower() in ("yes", "y"):
        save_credentials(creds)

    return creds


# ---------------------------------------------------------------- YAML
def save_credentials(creds, path=CONFIG_PATH):
    # Cria o arquivo já com permissão 600 (só o dono lê/escreve)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        yaml.safe_dump({"connection": creds}, f, default_flow_style=False, sort_keys=False)

    print(f"Credentials saved to {path}")


def load_credentials(path=CONFIG_PATH):
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("connection")


# ---------------------------------------------------------------- conexão
def build_url(creds):
    db_type = creds["type"]

    if db_type == "sqlite":
        return URL.create(drivername=DRIVERS[db_type], database=creds["database"])

    query = {}
    if db_type == "mssql":
        query["driver"] = "ODBC Driver 18 for SQL Server"
        query["TrustServerCertificate"] = "yes"  # útil em home lab com cert autoassinado

    # URL.create escapa corretamente caracteres especiais na senha (@, :, / ...)
    return URL.create(
        drivername=DRIVERS[db_type],
        username=creds["username"],
        password=creds["password"],
        host=creds["hostname"],
        port=creds["port"],
        database=creds["database"],
        query=query,
    )


def connect(creds):
    """Cria o engine e testa a conexão. Retorna o engine ou None se falhar."""
    engine = create_engine(build_url(creds))
    test_query = TEST_QUERIES.get(creds["type"], "SELECT 1")

    try:
        with engine.connect() as conn:
            conn.execute(text(test_query))
        print(f"Connected to {creds['type']} successfully!")
        return engine
    except ModuleNotFoundError as e:
        print(f"Driver not installed: {e}")
    except SQLAlchemyError as e:
        print(f"Connection failed: {e}")

    engine.dispose()
    return None


# ---------------------------------------------------------------- main
def main():
    creds = load_credentials()

    if creds:
        use_saved = input(
            f"Use saved credentials ({creds['type']} @ {creds['hostname'] or creds['database']})? (y/n) "
        )
        if use_saved.strip().lower() not in ("yes", "y"):
            creds = None

    if not creds:
        db_type = get_database()
        creds = get_db_credentials(db_type)

    engine = connect(creds)
    if engine is None:
        return

    # Exemplo de uso: aqui você já pode rodar suas queries
    # with engine.connect() as conn:
    #     rows = conn.execute(text("SELECT ...")).fetchall()

    engine.dispose()


if __name__ == "__main__":
    main()