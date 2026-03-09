#!/usr/bin/env python3
"""
Test PyEgeria agent detection with detailed logging.
"""
import sys
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.agents.pyegeria_agent import get_pyegeria_agent

# Configure logging to see all debug messages
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def test_detection():
    """Test PyEgeria query detection."""
    print("=" * 80)
    print("Testing PyEgeria Agent Detection")
    print("=" * 80)
    
    # Get agent
    agent = get_pyegeria_agent()
    
    # Test queries
    test_queries = [
        "what methods does ProjectManager have?",
        "tell me about GlossaryManager",
        "how do I use the AssetManager class?",
        "what is pyegeria?",
        "show me python client examples",
        "what is Egeria?",  # Should NOT trigger
        "how do I configure a server?"  # Should NOT trigger
    ]
    
    print("\nTesting queries:\n")
    for query in test_queries:
        print(f"\nQuery: {query}")
        print("-" * 80)
        is_pyegeria = agent.is_pyegeria_query(query)
        print(f"Result: {'✓ PyEgeria' if is_pyegeria else '✗ Not PyEgeria'}")
        print()

if __name__ == "__main__":
    test_detection()