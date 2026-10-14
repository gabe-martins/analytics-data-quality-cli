"""Leitura e gravação das conexões e comparações salvas."""

import os
from pathlib import Path

import yaml

from cli_helpers import ask_yes_no

CONFIG_PATH = Path("credentials.yaml")


COMPARISONS_PATH = Path("comparisons.yaml")


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


def load_comparisons():
    if not COMPARISONS_PATH.exists():
        return []
    with COMPARISONS_PATH.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or []


def save_comparison(comparison):
    comparisons = load_comparisons()
    comparisons.append(comparison)
    with COMPARISONS_PATH.open("w", encoding="utf-8") as file:
        yaml.safe_dump(comparisons, file, allow_unicode=True, sort_keys=False)
