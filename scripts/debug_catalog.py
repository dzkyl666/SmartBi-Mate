"""Debug script to check catalog column_tables_mapping."""
import sys, os
sys.path.insert(0, r"D:\SmartBi Mate")
os.chdir(r"D:\SmartBi Mate")

from smartbi_mate import config
config.load(r"config\config.yaml")
catalog = config.get().catalog_store

tables = catalog.get_table_list()
print(f"Tables: {tables}")

from smartbi_mate.catalog.retrival_helper import build_column_tables_mapping
mapping = build_column_tables_mapping(catalog)
print(f"Mapping size: {len(mapping)}")
for k, v in list(mapping.items())[:10]:
    print(f"  {k} -> {v}")

cols = catalog.get_column_list("fact_order")
col_names = [c["column_name"] for c in cols]
print(f"fact_order columns ({len(cols)}): {col_names}")
