"""Motor de comparação estrutural e de qualidade entre tabelas."""

from datetime import datetime
from decimal import Decimal

from cli_helpers import ask_yes_no, choose_from_list, describe
from config import COMPARISONS_PATH, load_connections, load_comparisons, save_comparison
from database import connect
from tables import (
    common_sample_size,
    collect_table_profile,
    estimate_row_count,
    qualified_name,
    select_table,
)


def _choose_connection(connections):
    names = list(connections)
    print("\nChoose a connection for this table:")
    for index, name in enumerate(names, start=1):
        print(f"{index}. {name} ({describe(connections[name])})")
    print(f"{len(names) + 1}. Back")
    index = choose_from_list(range(len(names) + 1))
    return None if index == len(names) else names[index]


def compare_table_statistics():
    connections = load_connections()
    if len(connections) < 1:
        print("\nSave at least one connection before comparing tables.")
        return

    selected = []
    opened = []
    seen = set()
    try:
        while True:
            name = _choose_connection(connections)
            if name is None:
                if len(selected) < 2:
                    print("Choose at least two tables to compare.")
                    if not selected:
                        return
                    continue
                break

            creds = connections[name]
            conn = connect(creds)
            if conn is None:
                continue
            opened.append(conn)
            table = select_table(conn, creds)
            if table is None:
                conn.close()
                opened.remove(conn)
                if not selected:
                    return
                continue
            schema, table_name = table
            identity = (name, schema, table_name)
            if identity in seen:
                print("That table is already in this comparison.")
                conn.close()
                opened.remove(conn)
                continue
            seen.add(identity)
            selected.append({"connection": name, "creds": creds, "conn": conn,
                             "schema": schema, "table": table_name})
            if not ask_yes_no("Add another table to this comparison?"):
                if len(selected) < 2:
                    print("Choose at least two tables to compare.")
                    continue
                break

        estimates = [estimate_row_count(item["conn"], item["creds"]["type"],
                                        item["schema"], item["table"])
                     for item in selected]
        sample_size = common_sample_size(estimates)
        print(f"\nShared sampling plan: up to {sample_size} randomly selected rows per table.")

        sources = []
        for item, estimate in zip(selected, estimates):
            profile = collect_table_profile(
                item["conn"], item["creds"], item["schema"], item["table"], sample_size
            )
            profile["estimated_rows"] = estimate
            # Amostras podem conter dados sensíveis; persistimos apenas os indicadores.
            profile.pop("sample_rows", None)
            profile.pop("sample_columns", None)
            sources.append({
                "connection": item["connection"],
                "table": qualified_name(item["schema"], item["table"]),
                **profile,
            })

        print_comparison(sources)
        label = input("\nComparison name (blank for date and time): ").strip()
        created_at = datetime.now().astimezone().isoformat(timespec="seconds")
        if not label:
            label = f"Comparison {created_at[:19].replace('T', ' ')}"
        comparison = {
            "name": label,
            "created_at": created_at,
            "sample_size": sample_size,
            "sources": _yaml_safe(sources),
        }
        save_comparison(comparison)
        print(f"Comparison '{label}' saved to {COMPARISONS_PATH}.")
    except Exception as e:
        print(f"Could not compare table statistics: {e}")
    finally:
        for conn in opened:
            try:
                conn.close()
            except Exception:
                pass


def _type_family(data_type):
    kind = (data_type or "").upper()
    if any(token in kind for token in ("INT", "REAL", "FLOAT", "DOUBLE", "NUM", "DEC", "NUMBER", "MONEY")):
        return "numeric"
    if any(token in kind for token in ("CHAR", "TEXT", "CLOB", "STRING")):
        return "text"
    if "DATE" in kind or "TIME" in kind:
        return "datetime"
    if "BOOL" in kind or kind == "BIT":
        return "boolean"
    if "BINARY" in kind or "BLOB" in kind or "IMAGE" in kind:
        return "binary"
    return "other"


def _yaml_safe(value):
    """Converte decimais de drivers em valores que PyYAML grava com segurança."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _yaml_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_yaml_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_yaml_safe(item) for item in value]
    return value


def compare_schema(sources):
    all_names = []
    for source in sources:
        for name in source["columns"]:
            if name not in all_names:
                all_names.append(name)
    print("\nSchema comparison (column names are matched exactly):")
    print("Column | Presence | Declared types | Families | Nullable | Primary key | PK unique in sample")
    for name in all_names:
        present = [source["columns"].get(name) for source in sources]
        presence = "/".join("yes" if info else "no" for info in present)
        declared_types = "/".join(_format_type(info) if info else "—" for info in present)
        families = "/".join(_type_family(info.get("type")) if info else "—" for info in present)
        nullable = "/".join(("yes" if info.get("nullable") else "no") if info else "—" for info in present)
        primary = "/".join(("yes" if info.get("primary_key") else "no") if info else "—" for info in present)
        unique = "/".join(
            "yes" if source["metrics"].get(name, {}).get("sample_unique") is True
            else "no" if source["metrics"].get(name, {}).get("sample_unique") is False
            else "—" for source in sources
        )
        print(f"{name} | {presence} | {declared_types} | {families} | {nullable} | {primary} | {unique}")


def _format_type(info):
    data_type = info.get("type", "")
    precision = info.get("precision")
    scale = info.get("scale")
    length = info.get("length")
    if precision is not None:
        suffix = f"({precision}" + (f",{scale}" if scale is not None else "") + ")"
    elif length is not None and length != -1:
        suffix = f"({length})"
    else:
        suffix = ""
    return f"{data_type}{suffix}"


def print_comparison(sources):
    print("\nComparison:")
    for index, source in enumerate(sources, start=1):
        count = source.get("estimated_rows")
        count_text = "unknown" if count is None else f"~{count} rows"
        print(f"{index}. {source['connection']} — {source['table']} "
              f"({source['sample_size']} sampled; {count_text})")
    compare_schema(sources)

    names = []
    for source in sources:
        for name in source["metrics"]:
            if name not in names:
                names.append(name)
    print("\nSample quality metrics:")
    print("Column | Null rate by table | Distinct rate by table | Numeric min / mean / max")
    for name in names:
        metrics = [source["metrics"].get(name) for source in sources]
        nulls = "/".join("—" if not m or m["null_rate"] is None else f"{m['null_rate']:.1%}" for m in metrics)
        distinct = "/".join("—" if not m or m["distinct_rate"] is None else f"{m['distinct_rate']:.1%}" for m in metrics)
        numeric = "/".join(
            "—" if not m or "mean" not in m
            else f"{m['min']} / {m['mean']} / {m['max']}" for m in metrics
        )
        print(f"{name} | {nulls} | {distinct} | {numeric}")
    print("Rates and numeric summaries describe the sample, not the full table.")


def _print_saved_comparison(comparison):
    print(f"\n{comparison['name']} ({comparison['created_at']})")
    if "sources" in comparison:
        print_comparison(comparison["sources"])
        return
    # Compatibilidade com comparações salvas antes da atualização do motor.
    first, second = comparison["first"], comparison["second"]
    print(f"{first['connection']} — {first['table']}  |  {second['connection']} — {second['table']}")
    print_comparison_rows(first["statistics"], second["statistics"])


def print_comparison_rows(first_stats, second_stats):
    shared_columns = [column for column in first_stats if column in second_stats]
    if not shared_columns:
        print("No numeric columns with matching names and values in both samples.")
        return
    print("Column | Min (1 / 2) | Average (1 / 2) | Max (1 / 2)")
    for column in shared_columns:
        a_min, a_avg, a_max = first_stats[column]
        b_min, b_avg, b_max = second_stats[column]
        print(f"{column} | {a_min} / {b_min} | {a_avg} / {b_avg} | {a_max} / {b_max}")


def view_saved_comparison():
    try:
        comparisons = load_comparisons()
    except Exception as e:
        print(f"Could not read saved comparisons: {e}")
        return
    if not comparisons:
        print("\nNo saved comparisons yet.")
        return
    print("\nSaved comparisons:")
    for index, comparison in enumerate(comparisons, start=1):
        print(f"{index}. {comparison['name']} ({comparison['created_at']})")
    print(f"{len(comparisons) + 1}. Back")
    index = choose_from_list(range(len(comparisons) + 1))
    if index != len(comparisons):
        _print_saved_comparison(comparisons[index])
