"""Comparação e consulta do histórico de estatísticas."""

from datetime import datetime

from cli_helpers import choose_from_list, describe
from config import COMPARISONS_PATH, load_connections, load_comparisons, save_comparison
from database import connect
from tables import qualified_name, select_table, show_table_sample

def choose_saved_connection(connections, prompt, excluded=()):
    names = [name for name in connections if name not in excluded]
    if not names:
        print("Not enough saved connections to compare.")
        return None

    print(f"\n{prompt}:")
    for i, name in enumerate(names, start=1):
        print(f"{i}. {name} ({describe(connections[name])})")
    print(f"{len(names) + 1}. Back")
    index = choose_from_list(range(len(names) + 1))
    return None if index == len(names) else names[index]


def compare_table_statistics():
    connections = load_connections()
    if len(connections) < 2:
        print("\nSave at least two connections before comparing tables.")
        return

    first_name = choose_saved_connection(connections, "First connection")
    if first_name is None:
        return
    second_name = choose_saved_connection(
        connections, "Second connection", excluded=(first_name,)
    )
    if second_name is None:
        return

    selected = []
    opened = []
    try:
        for name in (first_name, second_name):
            creds = connections[name]
            conn = connect(creds)
            if conn is None:
                return
            opened.append(conn)
            table = select_table(conn, creds)
            if table is None:
                return
            selected.append((name, creds, conn, table))

        results = []
        for name, creds, conn, (schema, table) in selected:
            stats = show_table_sample(conn, creds, schema, table)
            results.append((name, qualified_name(schema, table), stats))

        first, second = results
        print("\nComparison (statistics from independent random samples):")
        print(f"{first[0]} — {first[1]}  |  {second[0]} — {second[1]}")
        print_comparison_rows(first[2], second[2])

        label = input("\nComparison name (blank for date and time): ").strip()
        created_at = datetime.now().astimezone().isoformat(timespec="seconds")
        if not label:
            label = f"Comparison {created_at[:19].replace('T', ' ')}"
        comparison = {
            "name": label,
            "created_at": created_at,
            "first": serialize_result(first),
            "second": serialize_result(second),
        }
        save_comparison(comparison)
        print(f"Comparison '{label}' saved to {COMPARISONS_PATH}.")
    except Exception as e:
        print(f"Could not compare table statistics: {e}")
    finally:
        for conn in opened:
            conn.close()


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


def serialize_result(result):
    name, table, stats = result
    return {
        "connection": name,
        "table": table,
        "statistics": {
            column: [str(value) for value in values]
            for column, values in stats.items()
        },
    }


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
    if index == len(comparisons):
        return

    comparison = comparisons[index]
    first, second = comparison["first"], comparison["second"]
    print(f"\n{comparison['name']} ({comparison['created_at']})")
    print(f"{first['connection']} — {first['table']}  |  {second['connection']} — {second['table']}")
    print_comparison_rows(first["statistics"], second["statistics"])
