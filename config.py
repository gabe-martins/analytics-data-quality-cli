"""Leitura e gravação das conexões e comparações salvas."""

import os
import tempfile
from pathlib import Path

import yaml

from cli_helpers import ask_yes_no

PROJECT_PATH = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_PATH / "credentials.yaml"


COMPARISONS_PATH = PROJECT_PATH / "comparisons.yaml"


def load_connections(path=None):
    """Retorna um dict {nome: credenciais}."""
    path = Path(path) if path is not None else CONFIG_PATH
    if not path.exists():
        return {}

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    # Compatibilidade com o formato antigo (uma única conexão)
    if "connection" in data and "connections" not in data:
        return {"default": data["connection"]}

    return data.get("connections") or {}


def write_connections(connections, path=None):
    # Cria o arquivo já com permissão 600 (só o dono lê/escreve)
    path = Path(path) if path is not None else CONFIG_PATH
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


def load_comparisons():
    if not COMPARISONS_PATH.exists():
        return []
    with COMPARISONS_PATH.open("r", encoding="utf-8") as file:
        comparisons = yaml.safe_load(file) or []
    if not isinstance(comparisons, list) or any(not isinstance(item, dict) for item in comparisons):
        raise ValueError("Invalid comparison history: expected a list of records")
    return comparisons


def save_comparison(comparison):
    comparisons = load_comparisons()
    comparisons.append(comparison)
    # Serializar antes de abrir o arquivo preserva o histórico em caso de erro.
    serialized = yaml.safe_dump(comparisons, allow_unicode=True, sort_keys=False)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False,
                                         dir=COMPARISONS_PATH.parent, prefix=".comparisons-") as file:
            temporary = file.name
            file.write(serialized)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, COMPARISONS_PATH)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
