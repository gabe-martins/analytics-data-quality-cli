"""Seleção e consulta de tabelas pelos adaptadores comuns do motor."""

from cli_helpers import choose_from_list
from db_adapters import get_adapter
from quality import NUMERIC_FAMILIES, profile_rows, type_family

SAMPLE_CAP = 200


def qualified_name(schema, table):
    return f"{schema}.{table}" if schema else table


def quote_identifier(identifier, db_type):
    return get_adapter(db_type).quote_identifier(identifier)


def _table_sql(db_type, schema, table):
    return get_adapter(db_type).qualified_name(schema, table)


def estimate_row_count(conn, db_type, schema, table):
    return get_adapter(db_type).estimate_rows(conn, schema, table)


def common_sample_size(estimates, cap=SAMPLE_CAP):
    """Define limite comum sem deixar uma estimativa pequena colapsar o conjunto."""
    if not isinstance(cap, int) or cap < 1:
        raise ValueError("Sample cap must be a positive integer")
    # Uma tabela vazia ou estatística antiga não reduz todas as outras a uma linha.
    known = [count for count in estimates if count is not None and count > 0]
    if not known:
        return min(cap, 100)
    return min(cap, max(30, int(10 * max(known) ** 0.5)))



def _column_metadata(conn, db_type, schema, table):
    return get_adapter(db_type).metadata(conn, schema, table)


def _is_numeric(data_type):
    return type_family(data_type) in NUMERIC_FAMILIES


def collect_table_profile(conn, creds, schema, table, sample_size, metadata=None):
    adapter = get_adapter(creds["type"])
    metadata = adapter.metadata(conn, schema, table) if metadata is None else metadata
    if not metadata:
        raise ValueError("No column metadata available")
    names, rows = adapter.fetch_random(conn, schema, table, list(metadata), sample_size, metadata=metadata)
    return profile_rows(metadata, names, rows)


def show_table_sample(conn, creds, schema, table, sample_size=None):
    """Exibe amostra e perfil, mantendo compatibilidade com o menu de consulta."""
    if sample_size is None:
        sample_size = common_sample_size([
            estimate_row_count(conn, creds["type"], schema, table)
        ])
    profile = collect_table_profile(conn, creds, schema, table, sample_size)
    print(f"\nRandom sample (up to {sample_size} rows; received {profile['sample_size']}):")
    if profile["sample_rows"]:
        print(" | ".join(profile["sample_columns"]))
        for row in profile["sample_rows"]:
            print(" | ".join("NULL" if value is None else str(value) for value in row))
    else:
        print("No rows found.")
    print("Sample metrics: column | type | null rate | distinct/sample | min | mean | max")
    for name, metric in profile["metrics"].items():
        minimum = metric.get("min", "—")
        average = metric.get("mean", "—")
        maximum = metric.get("max", "—")
        null_rate = "—" if metric["null_rate"] is None else f"{metric['null_rate']:.1%}"
        distinct = "—" if metric["distinct_rate"] is None else f"{metric['distinct_rate']:.1%}"
        print(f"{name} | {metric['type']} | {null_rate} | {distinct} | {minimum} | {average} | {maximum}")
    return profile



def list_tables(conn, db_type):
    return get_adapter(db_type).list_tables(conn)


def select_table(conn, creds):
    try:
        tables = list_tables(conn, creds["type"])
    except Exception as e:
        print(f"Could not list tables: {e}")
        return None
    if not tables:
        print("\nNo tables found in this database.")
        return None
    print(f"\nTables ({len(tables)}):")
    for i, (schema, table) in enumerate(tables, start=1):
        print(f"{i}. {qualified_name(schema, table)}")
    print(f"{len(tables) + 1}. Back")
    index = choose_from_list(range(len(tables) + 1))
    return None if index == len(tables) else tables[index]
