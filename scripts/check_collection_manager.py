#!/usr/bin/env python3
"""Check CollectionManager methods in pyegeria collection."""

from pymilvus import Collection, connections

connections.connect('default', host='localhost', port='19530')
c = Collection('pyegeria')
c.load()

# Check all CollectionManager elements
results = c.query(
    expr='class_name == "CollectionManager"',
    output_fields=['method_name', 'element_type'],
    limit=100
)

print(f'Total elements with class_name=CollectionManager: {len(results)}')

# Breakdown by type
types = {}
for r in results:
    t = r.get('element_type', 'unknown')
    types[t] = types.get(t, 0) + 1

print(f'\nBreakdown by type:')
for k, v in types.items():
    print(f'  {k}: {v}')

print(f'\nAll methods:')
methods = [r for r in results if r.get('element_type') == 'method']
for i, m in enumerate(sorted(methods, key=lambda x: x.get('method_name', '')), 1):
    print(f'  {i}. {m.get("method_name")}')