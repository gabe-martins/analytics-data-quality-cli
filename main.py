import os
from getpass import getpass
from pathlib import Path

import yaml  # pip install pyyaml
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

CONFIG_PATH = Path("credentials.yaml")

DB_TYPES = ("postgresql", "mysql", "sqlite", "mssql", "oracle")

# Driver Python usado por cada tipo de banco
DRIVERS = {
    "postgresql": "postgresql+psycopg2",  # pip install psycopg2-binary
    "mysql": "mysql+pymysql",             # pip install pymysql
    "sqlite": "sqlite",                   # já vem com o Python
    "oracle": "oracle+oracledb",          # pip install oracledb
    # mssql não passa pelo SQLAlchemy: usa o driver nativo mssql-python (pip install mssql-python)
}

# Query mínima de teste (Oracle exige FROM DUAL)
TEST_QUERIES = {"oracle": "SELECT 1 FROM DUAL"}


# ---------------------------------------------------------------- helpers
def ask_yes_no(prompt):
    return input(f"{prompt} (y/n) ").strip().lower() in ("yes", "y", "s", "sim")


def choose_from_list(options, prompt="Enter your choice: "):
    """Mostra a lista numerada e retorna o índice escolhido (0-based)."""
    while True:
        try:
            choice = int(input(prompt))
            if 1 <= choice <= len(options):
                return choice - 1
            print("Invalid choice. Please try again.")
        except ValueError:
            print("Invalid input. Please enter a number.")


def describe(creds):
    where = creds["hostname"] or creds["database"]
    return f"{creds['type']} @ {where}"


# ---------------------------------------------------------------- YAML
def load_connections(path=CONFIG_PATH):
    """Retorna um dict {nome: credenciais}."""
    if not path.exists():
        return {}

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    # Compatibilidade com o formato antigo (uma única conexão)
    if "connection" in data and "connections" not in data:
        return {"default": data["connection"]}

    return data.get("connections") or {}


def write_connections(connections, path=CONFIG_PATH):
    # Cria o arquivo já com permissão 600 (só o dono lê/escreve)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            {"connections": connections},
            f,
            default_flow_style=False,
            sort_keys=False,
        )


def save_connection(name, creds):
    connections = load_connections()

    if name in connections and not ask_yes_no(f"'{name}' already exists. Overwrite?"):
        print("Connection not saved.")
        return

    connections[name] = creds
    write_connections(connections)
    print(f"Connection '{name}' saved to {CONFIG_PATH}")


# ---------------------------------------------------------------- entrada
def get_database():
    print("\nSelect a database type:")
    for i, db_type in enumerate(DB_TYPES, start=1):
        print(f"{i}. {db_type}")

    return DB_TYPES[choose_from_list(DB_TYPES)]


def get_db_credentials(db_type):
    if db_type == "sqlite":
        # SQLite é um arquivo local: não tem host, porta nem login
        return {
            "type": db_type,
            "hostname": None,
            "port": None,
            "username": None,
            "password": None,
            "database": input("Enter database file path (e.g. app.db): "),
        }

    hostname = input("Enter hostname: ")
    port = input("Enter port: ")
    return {
        "type": db_type,
        "hostname": hostname,
        "port": int(port) if port.strip() else None,
        "username": input("Enter username: "),
        "password": getpass("Enter password: "),  # não exibe a senha
        "database": input("Enter database name (or service name): "),
    }


# ---------------------------------------------------------------- conexão
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


def use_connection(creds):
    conn = connect(creds)
    if conn is None:
        return

    # Aqui você já pode rodar suas queries (mesma API para todos os bancos):
    # cursor = conn.cursor()
    # cursor.execute("SELECT ...")
    # rows = cursor.fetchall()

    conn.close()


# ---------------------------------------------------------------- menu
def use_saved_connection():
    connections = load_connections()

    if not connections:
        print("\nNo saved connections yet. Add a new one first.")
        return

    names = list(connections)
    print("\nSaved connections:")
    for i, name in enumerate(names, start=1):
        print(f"{i}. {name} ({describe(connections[name])})")
    print(f"{len(names) + 1}. Back")

    index = choose_from_list(range(len(names) + 1))
    if index == len(names):
        return

    use_connection(connections[names[index]])


def add_new_connection():
    name = input("\nConnection name (e.g. homelab-postgres): ").strip()
    if not name:
        print("Name cannot be empty.")
        return

    db_type = get_database()
    creds = get_db_credentials(db_type)

    if ask_yes_no("Save this connection?"):
        save_connection(name, creds)

    use_connection(creds)


MENU = (
    ("Use a saved connection", use_saved_connection),
    ("Add a new connection", add_new_connection),
    ("Exit", None),
)


def main():
    while True:
        print("\n=== Database Manager ===")
        for i, (label, _) in enumerate(MENU, start=1):
            print(f"{i}. {label}")

        _, action = MENU[choose_from_list(MENU)]
        if action is None:
            print("Bye!")
            break

        action()


if __name__ == "__main__":
    main()