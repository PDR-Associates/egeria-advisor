#!/usr/bin/env python3
"""Print the number of vectors in each Milvus collection."""

from pymilvus import connections, Collection, utility

HOST = "localhost"
PORT = 19530

COLLECTIONS = [
    "pyegeria",
    "pyegeria_cli",
    "pyegeria_drE",
    "egeria_java",
    "egeria_docs",
    "egeria_concepts",
    "egeria_types",
    "egeria_general",
    "egeria_workspaces",
    "egeria_templates",
]

connections.connect(host=HOST, port=PORT)

existing = set(utility.list_collections())
total = 0

print(f"{'Collection':<25} {'Vectors':>10}")
print("-" * 37)

for name in COLLECTIONS:
    if name not in existing:
        print(f"{name:<25} {'(not found)':>10}")
        continue
    col = Collection(name)
    col.load()
    count = col.num_entities
    total += count
    print(f"{name:<25} {count:>10,}")

print("-" * 37)
print(f"{'TOTAL':<25} {total:>10,}")
