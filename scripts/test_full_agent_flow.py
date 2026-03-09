#!/usr/bin/env python3
"""
Test full ConversationAgent flow with PyEgeria detection.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Force clean import
modules_to_clear = [
    'advisor.agents.pyegeria_agent',
    'advisor.agents.conversation_agent',
]

for mod in modules_to_clear:
    if mod in sys.modules:
        del sys.modules[mod]

# Now import fresh
from advisor.agents.conversation_agent import create_agent

print("\n" + "="*60)
print("Testing Full ConversationAgent Flow")
print("="*60)

# Create agent
agent = create_agent(enable_mlflow=False)  # Disable MLflow for simpler output

# Test query
test_query = "list all the methods in ProjectManager"
print(f"\nTest Query: '{test_query}'")
print("-" * 60)

# Run query
print("\nCalling agent.run()...")
result = agent.run(test_query, use_rag=True)

print("\n" + "="*60)
print("RESULT")
print("="*60)

# Check metadata
metadata = result.get('metadata', {})
routed_to = metadata.get('routed_to', 'UNKNOWN')
agent_type = metadata.get('agent', 'UNKNOWN')

print(f"\nRouted to: {routed_to}")
print(f"Agent type: {agent_type}")

if routed_to == 'pyegeria_agent':
    print("\n✓ SUCCESS: Query routed to PyEgeria Agent")
else:
    print(f"\n✗ FAIL: Query routed to '{routed_to}' instead of 'pyegeria_agent'")

# Check response
response_content = result.get('content', '')
response_lines = response_content.split('\n')
print(f"\nResponse has {len(response_lines)} lines")

# Count methods mentioned
method_count = sum(1 for line in response_lines if 'def ' in line or line.strip().startswith(('1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.')))
print(f"Methods mentioned: ~{method_count}")

if method_count >= 40:
    print("✓ SUCCESS: Returned many methods (exhaustive query worked)")
elif method_count >= 10:
    print("⚠ PARTIAL: Returned some methods but not all")
else:
    print("✗ FAIL: Only returned a few methods (semantic search, not exhaustive)")

print("\n" + "="*60)