"""Listagem, amostragem e resumo de tabelas."""

from decimal import Decimal
from numbers import Number

from cli_helpers import choose_from_list

TABLE_QUERIES = {
    "postgresql": """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_type = 'BASE TABLE'
          AND table_schema NOT IN ('pg_catalog', 'information_schema')
        ORDER BY table_schema, table_name
    """,
    "mysql": """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_type = 'BASE TABLE'
          AND table_schema = DATABASE()
        ORDER BY table_name
    """,
    "mssql": """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_type = 'BASE TABLE'
        ORDER BY table_schema, table_name
    """,
    "sqlite": """
        SELECT '', name
        FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
    """,
    "oracle": """
        SELECT USER, table_name
        FROM user_tables
        ORDER BY table_name
    """,
}


def qualified_name(schema, table):
    return f"{schema}.{table}" if schema else table


def quote_identifier(identifier, db_type):
    """Delimita um identificador de banco sem tratar nomes como SQL livre."""
    identifier = str(identifier)
    if db_type == "mysql":
        return "`" + identifier.replace("`", "``") + "`"
    if db_type == "mssql":
        return f"[{identifier.replace(']', ']]')}]"
    return '"' + identifier.replace('"', '""') + '"'


def sample_query(db_type, table_sql):
    random_order = {
        "postgresql": "RANDOM()",
        "mysql": "RAND()",
        "sqlite": "RANDOM()",
        "mssql": "NEWID()",
        "oracle": "DBMS_RANDOM.VALUE",
    }[db_type]
    limit = "FETCH FIRST 10 ROWS ONLY" if db_type == "oracle" else "LIMIT 10"
    if db_type == "mssql":
        return f"SELECT TOP 10 * FROM {table_sql} ORDER BY {random_order}"
    return f"SELECT * FROM {table_sql} ORDER BY {random_order} {limit}"


def numeric_columns(conn, db_type, schema, table):
    """Retorna nomes de colunas numéricas sem depender de valores da amostra."""
    cursor = conn.cursor()
    try:
        if db_type == "sqlite":
            pragma = f"PRAGMA table_info({quote_identifier(table, db_type)})"
            cursor.execute(pragma)
            return [row[1] for row in cursor.fetchall()
                    if any(kind in (row[2] or "").upper()
                           for kind in ("INT", "REAL", "FLOA", "DOUB", "NUM", "DEC"))]

        if db_type == "postgresql":
            query = """SELECT column_name FROM information_schema.columns
                       WHERE table_schema = %s AND table_name = %s
                         AND data_type IN ('smallint','integer','bigint','numeric','decimal','real','double precision')"""
        elif db_type == "mysql":
            query = """SELECT column_name FROM information_schema.columns
                       WHERE table_schema = %s AND table_name = %s
                         AND data_type IN ('tinyint','smallint','mediumint','int','integer','bigint','decimal','numeric','float','double','real','year')"""
        elif db_type == "mssql":
            query = """SELECT column_name FROM information_schema.columns
                       WHERE table_schema = ? AND table_name = ?
                         AND data_type IN ('tinyint','smallint','int','bigint','decimal','numeric','float','real','money','smallmoney')"""
        else:
            query = """SELECT column_name FROM user_tab_columns
                       WHERE table_name = :table_name
                         AND data_type IN ('NUMBER','FLOAT','BINARY_FLOAT','BINARY_DOUBLE')"""

        if db_type == "oracle":
            cursor.execute(query, {"table_name": table.upper()})
        else:
            cursor.execute(query, (schema, table))
        return [row[0] for row in cursor.fetchall()]
    finally:
        cursor.close()


def show_table_sample(conn, creds, schema, table):
    """Exibe uma amostra aleatória e retorna as estatísticas numéricas dela."""
    db_type = creds["type"]
    table_sql = ".".join(
        quote_identifier(part, db_type) for part in (schema, table) if part
    )
    cursor = conn.cursor()
    try:
        cursor.execute(sample_query(db_type, table_sql))
        rows = cursor.fetchall()
        column_names = [column[0] for column in cursor.description or ()]
    finally:
        cursor.close()

    print("\nRandom sample (up to 10 rows):")
    if rows:
        print(" | ".join(column_names))
        for row in rows:
            print(" | ".join("NULL" if value is None else str(value) for value in row))
    else:
        print("No rows found.")

    numeric_names = numeric_columns(conn, db_type, schema, table)
    indexes = [i for i, name in enumerate(column_names) if name in numeric_names]
    stats = {}
    for index in indexes:
        values = [row[index] for row in rows if row[index] is not None
                  and isinstance(row[index], (Number, Decimal))]
        if values:
            stats[column_names[index]] = (
                min(values), sum(values) / len(values), max(values)
            )

    print("\nNumeric summary for the sample:")
    if not stats:
        print("No numeric columns with values in this sample.")
        return stats
    print("Column | Min | Average | Max")
    for name, (minimum, average, maximum) in stats.items():
        print(f"{name} | {minimum} | {average} | {maximum}")
    return stats


def list_tables(conn, db_type):
    """Retorna uma lista de tuplas (schema, tabela) do banco conectado."""
    cursor = conn.cursor()
    try:
        cursor.execute(TABLE_QUERIES[db_type])
        return [(row[0], row[1]) for row in cursor.fetchall()]
    finally:
        cursor.close()


def select_table(conn, creds):
    """Lista as tabelas e deixa o usuário escolher uma.
    Retorna (schema, tabela) ou None se não houver escolha."""
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
    if index == len(tables):
        return None

    return tables[index]
