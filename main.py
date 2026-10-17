"""Ponto de entrada e fluxo principal da CLI."""

from getpass import getpass

from cli_helpers import ask_yes_no, choose_from_list, describe
from comparison import compare_table_statistics, view_saved_comparison
from config import load_connections, save_connection
from database import DB_TYPES, connect
from tables import qualified_name, select_table, show_table_sample
from db_adapters import SUPPORTED_DATABASES

def get_database():
    available = [kind for kind in DB_TYPES if kind in SUPPORTED_DATABASES]
    print("\nSelecione o banco de dados:")
    for i, db_type in enumerate(available, start=1):
        print(f"{i}. {db_type}")

    return available[choose_from_list(available)]


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


def use_connection(creds):
    conn = connect(creds)
    if conn is None:
        return

    try:
        selected = select_table(conn, creds)
        if selected:
            print(f"\nSelected table: {qualified_name(*selected)}")
            show_table_sample(conn, creds, *selected)
    except Exception as e:
        print(f"Could not read table sample: {e}")
    finally:
        conn.close()


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
    ("Usar uma conexão salva", use_saved_connection),
    ("Cadastrar uma conexão", add_new_connection),
    ("Comparar duas tabelas", compare_table_statistics),
    ("Consultar comparações salvas", view_saved_comparison),
    ("Sair", None),
)


def _menu():
    while True:
        print("\n=== Analytics Data Quality ===")
        for i, (label, _) in enumerate(MENU, start=1):
            print(f"{i}. {label}")

        _, action = MENU[choose_from_list(MENU)]
        if action is None:
            print("Até mais!")
            break

        action()


def main():
    try:
        _menu()
    except (EOFError, KeyboardInterrupt):
        print("\nExecução encerrada.")

if __name__ == "__main__":
    main()
