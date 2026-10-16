#!/usr/bin/env python3
"""Append manual de PostgreSQL para SQL Server, sem alterar registros existentes."""

import argparse
from contextlib import closing
from pathlib import Path
import sys

from config import load_connections
from database import connect_mssql, connect_sqlalchemy
from tables import quote_identifier


DEFAULT_CREDENTIALS = Path(__file__).resolve().with_name("credentials.yaml")


def table_sql(table, db_type):
    return ".".join(quote_identifier(part, db_type) for part in table)


def query(conn, sql, params=()):
    with closing(conn.cursor()) as cursor:
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
        return cursor.fetchall()


def metadata(conn, db_type):
    """Obtém tabelas, colunas e PKs; não lê valores de negócio."""
    if db_type == "postgresql":
        rows = query(conn, """
            SELECT n.nspname, t.relname, a.attname,
                   a.attgenerated <> '', a.attidentity <> '',
                   EXISTS (SELECT 1 FROM pg_index i
                           WHERE i.indrelid = t.oid AND i.indisprimary
                             AND a.attnum = ANY(i.indkey))
            FROM pg_class t
            JOIN pg_namespace n ON n.oid = t.relnamespace
            JOIN pg_attribute a ON a.attrelid = t.oid
            WHERE t.relkind IN ('r', 'p') AND NOT t.relispartition
              AND n.nspname NOT IN ('pg_catalog', 'information_schema')
              AND n.nspname NOT LIKE 'pg_toast%'
              AND a.attnum > 0 AND NOT a.attisdropped
            ORDER BY n.nspname, t.relname, a.attnum
        """)
    else:
        rows = query(conn, """
            SELECT s.name, t.name, c.name,
                   CASE WHEN c.is_computed = 1 OR c.generated_always_type <> 0
                             OR c.system_type_id = 189 THEN 1 ELSE 0 END,
                   c.is_identity,
                   CASE WHEN EXISTS (
                       SELECT 1 FROM sys.indexes i
                       JOIN sys.index_columns ic
                         ON ic.object_id = i.object_id AND ic.index_id = i.index_id
                       WHERE i.object_id = t.object_id AND i.is_primary_key = 1
                         AND ic.column_id = c.column_id AND ic.key_ordinal > 0
                   ) THEN 1 ELSE 0 END
            FROM sys.tables t
            JOIN sys.schemas s ON s.schema_id = t.schema_id
            JOIN sys.columns c ON c.object_id = t.object_id
            WHERE t.is_ms_shipped = 0 AND t.temporal_type <> 1
            ORDER BY s.name, t.name, c.column_id
        """)
    result = {}
    for schema, table, column, generated, identity, pk in rows:
        result.setdefault((schema, table), {})[column] = {
            "generated": bool(generated), "identity": bool(identity), "pk": bool(pk),
        }
    return result


def unique_names(names):
    result = {}
    for name in names:
        key = name.casefold()
        if key in result:
            raise ValueError(f"Nomes ambíguos (maiúsculas/minúsculas): {name}")
        result[key] = name
    return result


def build_plan(source, target):
    """Exige um destino inequívoco e colunas compatíveis para TODAS as tabelas."""
    if not source:
        raise ValueError("Nenhuma tabela encontrada na origem.")
    plan = []
    for src, src_columns in source.items():
        exact = [dst for dst in target if dst == src]
        candidates = exact or [dst for dst in target if dst[1].casefold() == src[1].casefold()]
        if len(candidates) != 1:
            raise ValueError(f"{src}: destino ausente ou ambíguo; crie/ajuste a tabela no destino.")
        dst = candidates[0]
        if any(item["target"] == dst for item in plan):
            raise ValueError(f"Mais de uma tabela de origem aponta para {dst}.")
        dst_columns = target[dst]
        src_names = unique_names(src_columns)
        unique_names(dst_columns)
        columns = [name for name, info in dst_columns.items() if not info["generated"]]
        missing = [name for name in columns if name.casefold() not in src_names]
        if missing:
            raise ValueError(f"{dst}: colunas ausentes na origem: {', '.join(missing)}")
        # Colunas calculadas no destino são regeneradas; nenhuma outra é descartada.
        dst_names = {name.casefold() for name in dst_columns}
        extra = [name for name in src_columns if name.casefold() not in dst_names]
        if extra:
            raise ValueError(f"{src}: colunas ausentes no destino: {', '.join(extra)}")
        pk = [name for name, info in dst_columns.items() if info["pk"]]
        source_pk = {name.casefold() for name, info in src_columns.items() if info["pk"]}
        if not pk or {name.casefold() for name in pk} != source_pk:
            raise ValueError(f"{dst}: exige a mesma chave primária nos dois bancos.")
        if any(name not in columns for name in pk):
            raise ValueError(f"{dst}: chave primária gerada/calculada não pode ser preservada.")
        plan.append({"source": src, "target": dst, "columns": columns, "pk": pk,
                     "source_columns": [src_names[name.casefold()] for name in columns],
                     "identity": any(dst_columns[name]["identity"] for name in columns)})
    return plan


def order_plan(plan, foreign_keys):
    """Pais primeiro, sem desabilitar constraints. Ciclos exigem tratamento específico."""
    pending = {item["target"]: item for item in plan}
    dependencies = {table: set() for table in pending}
    for child, parent in foreign_keys:
        if child in pending and parent in pending:
            dependencies[child].add(parent)
    ordered = []
    while pending:
        ready = [table for table in pending if not dependencies[table].intersection(pending)]
        if not ready:
            raise ValueError(f"Ciclo de chaves estrangeiras (incluindo autorreferências): {list(pending)}")
        for table in ready:
            ordered.append(pending.pop(table))
    return ordered


def foreign_keys(conn):
    rows = query(conn, """
        SELECT cs.name, ct.name, ps.name, pt.name
        FROM sys.foreign_keys f
        JOIN sys.tables ct ON ct.object_id = f.parent_object_id
        JOIN sys.schemas cs ON cs.schema_id = ct.schema_id
        JOIN sys.tables pt ON pt.object_id = f.referenced_object_id
        JOIN sys.schemas ps ON ps.schema_id = pt.schema_id
        WHERE f.is_disabled = 0
    """)
    return [((cs, ct), (ps, pt)) for cs, ct, ps, pt in rows]


def insert_sql(item):
    columns = item["columns"]
    names = ", ".join(quote_identifier(name, "mssql") for name in columns)
    predicate = " AND ".join(f"{quote_identifier(name, 'mssql')} = ?" for name in item["pk"])
    table = table_sql(item["target"], "mssql")
    return (f"INSERT INTO {table} ({names}) SELECT {', '.join('?' for _ in columns)} "
            f"WHERE NOT EXISTS (SELECT 1 FROM {table} WITH (UPDLOCK, HOLDLOCK) WHERE {predicate})")


def append_table(source, target, item, batch_size):
    """Transação por tabela; fetchmany limita a memória de leitura."""
    table = table_sql(item["target"], "mssql")
    names = ", ".join(quote_identifier(name, "postgresql") for name in item["source_columns"])
    pk_indexes = [item["columns"].index(name) for name in item["pk"]]
    sql = insert_sql(item)
    scanned = inserted = 0
    # Cursor nomeado do psycopg2: evita carregar toda a origem na memória.
    with closing(source.cursor(name="sync_append_rows")) as reader, closing(target.cursor()) as writer:
        try:
            reader.execute(f"SELECT {names} FROM {table_sql(item['source'], 'postgresql')}")
            if item["identity"]:
                writer.execute(f"SET IDENTITY_INSERT {table} ON")
            while True:
                rows = reader.fetchmany(batch_size)
                if not rows:
                    break
                for row in rows:
                    values = tuple(row)
                    writer.execute(sql, values + tuple(values[i] for i in pk_indexes))
                    # @@ROWCOUNT também funciona quando NOCOUNT está habilitado.
                    writer.execute("SELECT @@ROWCOUNT")
                    inserted += int(writer.fetchone()[0])
                scanned += len(rows)
                print(f"  {table}: {scanned} lidos, {inserted} inseridos (ainda sem commit)", flush=True)
            if item["identity"]:
                writer.execute(f"SET IDENTITY_INSERT {table} OFF")
            target.commit()
        except BaseException:
            target.rollback()
            # Em erro, a conexão é fechada pelo chamador, limpando IDENTITY_INSERT.
            raise
    return scanned, inserted


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", type=Path, default=DEFAULT_CREDENTIALS)
    parser.add_argument("--source", default="main-db", help="Conexão PostgreSQL (padrão: main-db)")
    parser.add_argument("--target", default="sql-server", help="Conexão SQL Server (padrão: sql-server)")
    parser.add_argument("--batch-size", type=int, default=1000, help="Linhas lidas por lote (padrão: 1000)")
    parser.add_argument("--dry-run", action="store_true", help="Valida e mostra o plano, sem inserir")
    args = parser.parse_args(argv)
    if args.batch_size < 1:
        parser.error("--batch-size deve ser positivo")
    connections = load_connections(args.credentials)
    if args.source not in connections or args.target not in connections:
        parser.error("Origem/destino não encontrados no arquivo de credenciais.")
    src, dst = connections[args.source], connections[args.target]
    if src.get("type") != "postgresql" or dst.get("type") != "mssql":
        parser.error("Este script suporta origem PostgreSQL e destino SQL Server.")
    print(f"Append: {args.source} → {args.target}", flush=True)
    with closing(connect_sqlalchemy(src)) as source, closing(connect_mssql(dst)) as target:
        # Snapshot consistente da origem e garantia de que nada será gravado nela.
        with closing(source.cursor()) as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        target.autocommit = False
        plan = order_plan(build_plan(metadata(source, "postgresql"), metadata(target, "mssql")),
                          foreign_keys(target))
        for item in plan:
            print(f"  {'.'.join(item['source'])} → {'.'.join(item['target'])}; "
                  f"PK: {', '.join(item['pk'])}", flush=True)
        if args.dry_run:
            target.rollback()
            print(f"Simulação concluída: {len(plan)} tabelas; nenhuma gravação.")
            return 0
        total = 0
        for item in plan:
            print(f"Copiando {'.'.join(item['source'])} → {'.'.join(item['target'])}...", flush=True)
            scanned, inserted = append_table(source, target, item, args.batch_size)
            total += inserted
            print(f"OK {'.'.join(item['target'])}: {inserted} inseridos, "
                  f"{scanned - inserted} já existentes; commit concluído.", flush=True)
        print(f"Concluído: {len(plan)} tabelas, {total} registros inseridos.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrompido. A tabela em andamento foi revertida; commits anteriores permanecem.", file=sys.stderr)
        sys.exit(130)
    except Exception as error:
        # Mensagens dos drivers podem conter SQL, valores ou credenciais.
        detail = str(error) if isinstance(error, ValueError) else type(error).__name__
        print(f"Erro: {detail}. Execução interrompida; commits anteriores permanecem.", file=sys.stderr)
        sys.exit(1)
