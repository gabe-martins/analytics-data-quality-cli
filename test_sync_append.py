"""Testes locais: plano e append transacional, sem acesso aos bancos reais."""

import sqlite3
import unittest

from sync_append import append_table, build_plan, insert_sql, order_plan


def columns(*names):
    return {name: {"pk": name.casefold() == "id", "identity": False, "generated": False}
            for name in names}


class CursorAdapter:
    """Adapta apenas sintaxe SQL Server para executar o append em SQLite local."""

    def __init__(self, conn):
        self.cursor = conn.cursor()

    def execute(self, sql, params=()):
        if sql == "SELECT @@ROWCOUNT":
            affected = self.cursor.rowcount
            self.cursor.execute("SELECT ?", (affected,))
        else:
            self.cursor.execute(sql.replace(" WITH (UPDLOCK, HOLDLOCK)", ""), params)

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchmany(self, size):
        return self.cursor.fetchmany(size)

    def close(self):
        self.cursor.close()


class ConnectionAdapter:
    def __init__(self, conn):
        self.conn = conn

    def cursor(self, **kwargs):
        return CursorAdapter(self.conn)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()


class SyncAppendTests(unittest.TestCase):
    def test_maps_case_and_schemas(self):
        plan = build_plan({("public", "users"): columns("id", "name")},
                          {("dbo", "Users"): columns("Id", "Name")})
        self.assertEqual(plan[0]["source_columns"], ["id", "name"])
        self.assertEqual(plan[0]["pk"], ["Id"])

    def test_preflight_rejects_missing_table_columns_and_pk(self):
        src = {("public", "users"): columns("id", "name")}
        for dst in ({}, {("dbo", "users"): columns("id")},
                    {("dbo", "users"): columns("name")},
                    {("dbo", "users"): columns("id", "name", "extra")}):
            with self.subTest(dst=dst), self.assertRaises(ValueError):
                build_plan(src, dst)

    def test_preflight_rejects_ambiguous_mapping(self):
        with self.assertRaises(ValueError):
            build_plan({("public", "users"): columns("id")},
                       {("a", "users"): columns("id"), ("b", "users"): columns("id")})

    def test_dependency_order_and_cycles(self):
        parent, child = ("dbo", "parent"), ("dbo", "child")
        plan = [{"target": child}, {"target": parent}]
        self.assertEqual(order_plan(plan, [(child, parent)]), list(reversed(plan)))
        for edges in ([(child, parent), (parent, child)], [(parent, parent)]):
            with self.assertRaises(ValueError):
                order_plan(plan, edges)

    def test_parameterizes_composite_key_and_quotes_identifiers(self):
        sql = insert_sql({"target": ("dbo", "a]b"), "columns": ["id", "part", "value"],
                          "pk": ["id", "part"]})
        self.assertIn("[dbo].[a]]b]", sql)
        self.assertIn("[id] = ? AND [part] = ?", sql)
        self.assertEqual(sql.count("?"), 5)

    def run_append(self, source_rows, target_rows):
        src, dst = sqlite3.connect(":memory:"), sqlite3.connect(":memory:")
        self.addCleanup(src.close)
        self.addCleanup(dst.close)
        for conn in (src, dst):
            conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)")
        src.executemany("INSERT INTO users VALUES (?, ?)", source_rows)
        dst.executemany("INSERT INTO users VALUES (?, ?)", target_rows)
        dst.commit()
        plan = build_plan({("main", "users"): columns("id", "name")},
                          {("main", "users"): columns("id", "name")})
        return src, dst, plan[0]

    def test_append_is_repeatable_and_preserves_existing_values(self):
        src, dst, item = self.run_append([(1, "source"), (2, "new")], [(1, "existing")])
        self.assertEqual(append_table(ConnectionAdapter(src), ConnectionAdapter(dst), item, 1), (2, 1))
        self.assertEqual(append_table(ConnectionAdapter(src), ConnectionAdapter(dst), item, 1), (2, 0))
        self.assertEqual(dst.execute("SELECT * FROM users ORDER BY id").fetchall(),
                         [(1, "existing"), (2, "new")])

    def test_failure_rolls_back_whole_current_table(self):
        src, dst, item = self.run_append([(1, "new"), (2, "conflict")], [(9, "conflict")])
        with self.assertRaises(sqlite3.IntegrityError):
            append_table(ConnectionAdapter(src), ConnectionAdapter(dst), item, 1)
        self.assertEqual(dst.execute("SELECT * FROM users").fetchall(), [(9, "conflict")])


if __name__ == "__main__":
    unittest.main()
