"""Applique un script SQL Supabase (idempotent) via DATABASE_URL.

Usage: uv run python apply_supabase_setup.py [fichier.sql]
Défaut: supabase_setup_cagecfi.sql
"""

import asyncio
import os
import sys

import asyncpg
from dotenv import load_dotenv

load_dotenv()


async def main() -> None:
    sql_file = sys.argv[1] if len(sys.argv) > 1 else "supabase_setup_cagecfi.sql"
    sql = open(sql_file, encoding="utf-8").read()

    conn = await asyncpg.connect(os.environ["DATABASE_URL"], statement_cache_size=0)
    try:
        await conn.execute(sql)
        for table in ("cagecfi_documents", "cagecfi_chunks"):
            reg = await conn.fetchval(f"SELECT to_regclass('public.{table}')")
            count = await conn.fetchval(f"SELECT COUNT(*) FROM {table}") if reg else "-"
            print(f"{table}: {reg} (lignes={count})")
        print(f"OK - {sql_file} appliqué")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
