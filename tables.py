"""Descoberta de metadados e amostragem comparável entre bancos."""

from decimal import Decimal
from numbers import Number

from cli_helpers import choose_from_list

TABLE_QUERIES = {
    "postgresql": """
        SELECT table_schema, table_name FROM information_schema.tables
        WHERE table_type = 'BASE TABLE'
          AND table_schema NOT IN ('pg_catalog', 'information_schema')
        ORDER BY table_schema, table_name
    """,
    "mysql": """
        SELECT table_schema, table_name FROM information_schema.tables
        WHERE table_type = 'BASE TABLE' AND table_schema = DATABASE()
        ORDER BY table_name
    """,
    "mssql": """
        SELECT table_schema, table_name FROM information_schema.tables
        WHERE table_type = 'BASE TABLE' ORDER BY table_schema, table_name
    """,
    "sqlite": """
        SELECT '', name FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name
    """,
    "oracle": "SELECT USER, table_name FROM user_tables ORDER BY table_name",
}

SAMPLE_CAP = 200


def qualified_name(schema, table):
    return f"{schema}.{table}" if schema else table


def quote_identifier(identifier, db_type):
    """Delimita identificadores, sem aceitar SQL fornecido pelo usuário."""
    identifier = str(identifier)
    if db_type == "mysql":
        return "`" + identifier.replace("`", "``") + "`"
    if db_type == "mssql":
        return f"[{identifier.replace(']', ']]')}]"
    return '"' + identifier.replace('"', '""') + '"'


def _table_sql(db_type, schema, table):
    return ".".join(
        quote_identifier(part, db_type) for part in (schema, table) if part
    )


def sample_query(db_type, table_sql, sample_size):
    """Consulta portátil por dialeto; todas as tabelas usam o mesmo limite."""
    sample_size = max(1, min(int(sample_size), SAMPLE_CAP))
    random_order = {
        "postgresql": "RANDOM()", "mysql": "RAND()", "sqlite": "RANDOM()",
        "mssql": "NEWID()", "oracle": "DBMS_RANDOM.VALUE",
    }[db_type]
    if db_type == "mssql":
        return f"SELECT TOP {sample_size} * FROM {table_sql} ORDER BY {random_order}"
    if db_type == "oracle":
        return (f"SELECT * FROM {table_sql} ORDER BY {random_order} "
                f"FETCH FIRST {sample_size} ROWS ONLY")
    return f"SELECT * FROM {table_sql} ORDER BY {random_order} LIMIT {sample_size}"


def estimate_row_count(conn, db_type, schema, table):
    """Lê estimativas do catálogo quando disponíveis, sem varrer a tabela."""
    cursor = conn.cursor()
    try:
        if db_type == "postgresql":
            cursor.execute("""SELECT c.reltuples::bigint
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = %s AND c.relname = %s""", (schema, table))
        elif db_type == "mysql":
            cursor.execute("""SELECT table_rows FROM information_schema.tables
                WHERE table_schema = %s AND table_name = %s""", (schema, table))
        elif db_type == "mssql":
            cursor.execute("""SELECT SUM(p.rows) FROM sys.tables t
                JOIN sys.schemas s ON s.schema_id = t.schema_id
                JOIN sys.partitions p ON p.object_id = t.object_id
                WHERE s.name = ? AND t.name = ? AND p.index_id IN (0, 1)""",
                (schema, table))
        elif db_type == "oracle":
            cursor.execute("""SELECT num_rows FROM user_tables
                WHERE table_name = :table_name""", {"table_name": table.upper()})
        else:
            # SQLite não mantém uma estimativa de cardinalidade no catálogo.
            return None
        row = cursor.fetchone()
        count = row[0] if row else None
        if count is None or int(count) < 0:
            return None
        return int(count)
    except Exception:
        # Estatísticas podem estar desatualizadas ou indisponíveis por permissão.
        return None
    finally:
        cursor.close()


def common_sample_size(estimates, cap=SAMPLE_CAP):
    """Define um limite único a partir da menor tabela estimada do conjunto."""
    known = [count for count in estimates if count is not None]
    if not known:
        return min(cap, 100)
    smallest = min(known)
    if smallest <= 0:
        return 1
    # Cresce com a população, mas limita custo e mantém o mesmo N na comparação.
    return max(1, min(cap, int(10 * smallest ** 0.5)))


def _column_metadata(conn, db_type, schema, table):
    cursor = conn.cursor()
    try:
        if db_type == "sqlite":
            cursor.execute(f"PRAGMA table_info({quote_identifier(table, db_type)})")
            return {
                row[1]: {"type": row[2] or "", "nullable": not bool(row[3]),
                         "primary_key": bool(row[5])}
                for row in cursor.fetchall()
            }
        if db_type == "oracle":
            cursor.execute("""SELECT column_name, data_type, nullable,
                data_length, data_precision, data_scale
                FROM user_tab_columns WHERE table_name = :table_name
                ORDER BY column_id""", {"table_name": table.upper()})
            rows = cursor.fetchall()
            metadata = {r[0]: {"type": r[1], "nullable": r[2] == "Y",
                               "length": r[3], "precision": r[4], "scale": r[5],
                               "primary_key": False} for r in rows}
            cursor.execute("""SELECT cc.column_name FROM user_constraints c
                JOIN user_cons_columns cc ON cc.constraint_name = c.constraint_name
                WHERE c.constraint_type = 'P' AND c.table_name = :table_name""",
                {"table_name": table.upper()})
            for row in cursor.fetchall():
                if row[0] in metadata:
                    metadata[row[0]]["primary_key"] = True
            return metadata
        if db_type == "mssql":
            query = """SELECT c.column_name, c.data_type, c.is_nullable,
                c.character_maximum_length, c.numeric_precision, c.numeric_scale,
                CASE WHEN k.column_name IS NULL THEN 0 ELSE 1 END
                FROM information_schema.columns c LEFT JOIN (
                    SELECT ku.table_schema, ku.table_name, ku.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage ku
                      ON tc.constraint_name = ku.constraint_name
                     AND tc.table_schema = ku.table_schema
                     AND tc.table_name = ku.table_name
                    WHERE tc.constraint_type = 'PRIMARY KEY'
                ) k ON k.table_schema=c.table_schema AND k.table_name=c.table_name
                   AND k.column_name=c.column_name
                WHERE c.table_schema = ? AND c.table_name = ? ORDER BY c.ordinal_position"""
            cursor.execute(query, (schema, table))
        else:
            query = """SELECT c.column_name, c.data_type, c.is_nullable,
                c.character_maximum_length, c.numeric_precision, c.numeric_scale,
                CASE WHEN k.column_name IS NULL THEN 0 ELSE 1 END
                FROM information_schema.columns c LEFT JOIN (
                    SELECT ku.table_schema, ku.table_name, ku.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage ku
                      ON tc.constraint_name = ku.constraint_name
                     AND tc.table_schema = ku.table_schema
                     AND tc.table_name = ku.table_name
                    WHERE tc.constraint_type = 'PRIMARY KEY'
                ) k ON k.table_schema=c.table_schema AND k.table_name=c.table_name
                   AND k.column_name=c.column_name
                WHERE c.table_schema = %s AND c.table_name = %s ORDER BY c.ordinal_position"""
            cursor.execute(query, (schema, table))
        rows = cursor.fetchall()
        return {r[0]: {"type": r[1], "nullable": r[2] == "YES",
                       "length": r[3], "precision": r[4], "scale": r[5],
                       "primary_key": bool(r[6])}
                for r in rows}
    finally:
        cursor.close()


def _is_numeric(data_type):
    normalized = (data_type or "").upper()
    return any(token in normalized for token in (
        "INT", "REAL", "FLOA", "DOUB", "NUM", "DEC", "MONEY", "NUMBER"
    )) and "INTERVAL" not in normalized


def collect_table_profile(conn, creds, schema, table, sample_size):
    """Retorna metadados e métricas simples calculadas somente na amostra."""
    db_type = creds["type"]
    metadata = _column_metadata(conn, db_type, schema, table)
    cursor = conn.cursor()
    try:
        cursor.execute(sample_query(db_type, _table_sql(db_type, schema, table), sample_size))
        rows = cursor.fetchall()
        names = [column[0] for column in cursor.description or ()]
    finally:
        cursor.close()

    metrics = {}
    for index, name in enumerate(names):
        values = [row[index] for row in rows]
        non_null = [value for value in values if value is not None]
        info = metadata.get(name, {"type": "", "nullable": True})
        metric = {
            "type": info.get("type", ""),
            "nullable": info.get("nullable", True),
            "primary_key": info.get("primary_key", False),
            "sample_count": len(values),
            "null_count": len(values) - len(non_null),
            "null_rate": (len(values) - len(non_null)) / len(values) if values else None,
            "distinct_count": len({repr(value) for value in non_null}),
            "distinct_rate": len({repr(value) for value in non_null}) / len(non_null)
                if non_null else None,
        }
        if _is_numeric(info.get("type", "")):
            numeric = [value for value in non_null if isinstance(value, (Number, Decimal))]
            if numeric:
                metric["min"] = min(numeric)
                metric["mean"] = sum(numeric) / len(numeric)
                metric["max"] = max(numeric)
                metric["numeric_count"] = len(numeric)
        if info.get("primary_key"):
            metric["sample_unique"] = len({repr(value) for value in non_null}) == len(non_null)
        metrics[name] = metric

    return {"columns": metadata, "metrics": metrics, "sample_size": len(rows),
            "sample_columns": names, "sample_rows": rows}


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
    cursor = conn.cursor()
    try:
        cursor.execute(TABLE_QUERIES[db_type])
        return [(row[0], row[1]) for row in cursor.fetchall()]
    finally:
        cursor.close()


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
