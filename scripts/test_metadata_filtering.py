#!/usr/bin/env python3
"""
Test metadata filtering enhancements for PyEgeria and CLI Command agents.

This script tests:
1. PyEgeria Agent with metadata filtering
2. CLI Command Agent with metadata filtering
3. Performance comparison (with vs without filtering)
"""

import sys
import time
from pathlib import Path
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.agents.pyegeria_agent import PyEgeriaAgent
from advisor.agents.cli_command_agent import CLICommandAgent
from advisor.vector_store import VectorStoreManager


def test_pyegeria_filtering():
    """Test PyEgeria agent with metadata filtering."""
    logger.info("=" * 80)
    logger.info("TESTING PYEGERIA AGENT WITH METADATA FILTERING")
    logger.info("=" * 80)
    
    agent = PyEgeriaAgent()
    
    # Test queries that should benefit from metadata filtering
    test_queries = [
        "what methods are in CollectionManager?",
        "show me all async methods in GlossaryManager",
        "what classes are in the admin module?",
        "list all methods in ProjectManager class",
        "what functions are in the utils module?",
    ]
    
    for query in test_queries:
        logger.info(f"\n{'=' * 60}")
        logger.info(f"Query: {query}")
        logger.info(f"{'=' * 60}")
        
        # Test WITH filtering
        start = time.time()
        results_with = agent.search_pyegeria(query, top_k=5, use_metadata_filters=True)
        time_with = time.time() - start
        
        # Test WITHOUT filtering
        start = time.time()
        results_without = agent.search_pyegeria(query, top_k=5, use_metadata_filters=False)
        time_without = time.time() - start
        
        logger.info(f"\nResults WITH filtering: {len(results_with)} results in {time_with:.3f}s")
        if results_with:
            logger.info(f"  Top result: {results_with[0].get('metadata', {}).get('name', 'N/A')} "
                       f"(score: {results_with[0].get('score', 0):.3f})")
        
        logger.info(f"\nResults WITHOUT filtering: {len(results_without)} results in {time_without:.3f}s")
        if results_without:
            logger.info(f"  Top result: {results_without[0].get('metadata', {}).get('name', 'N/A')} "
                       f"(score: {results_without[0].get('score', 0):.3f})")
        
        speedup = time_without / time_with if time_with > 0 else 1.0
        logger.info(f"\n⚡ Speedup: {speedup:.2f}x")
        
        if speedup > 2.0:
            logger.info(f"✓ Significant performance improvement!")
        elif speedup > 1.2:
            logger.info(f"✓ Moderate performance improvement")
        else:
            logger.info(f"⚠ Minimal performance difference")


def test_cli_filtering():
    """Test CLI Command agent with metadata filtering."""
    logger.info("\n" + "=" * 80)
    logger.info("TESTING CLI COMMAND AGENT WITH METADATA FILTERING")
    logger.info("=" * 80)
    
    agent = CLICommandAgent()
    
    # Test queries that should benefit from metadata filtering
    test_queries = [
        "how do I list all glossaries?",
        "show me asset commands",
        "what are the project commands?",
        "how to create a collection?",
    ]
    
    for query in test_queries:
        logger.info(f"\n{'=' * 60}")
        logger.info(f"Query: {query}")
        logger.info(f"{'=' * 60}")
        
        # Test WITH filtering
        start = time.time()
        results_with = agent.search_commands(query, top_k=5, use_metadata_filters=True)
        time_with = time.time() - start
        
        # Test WITHOUT filtering
        start = time.time()
        results_without = agent.search_commands(query, top_k=5, use_metadata_filters=False)
        time_without = time.time() - start
        
        logger.info(f"\nResults WITH filtering: {len(results_with)} results in {time_with:.3f}s")
        if results_with:
            logger.info(f"  Top result: {results_with[0].get('command', 'N/A')} "
                       f"(score: {results_with[0].get('score', 0):.3f})")
        
        logger.info(f"\nResults WITHOUT filtering: {len(results_without)} results in {time_without:.3f}s")
        if results_without:
            logger.info(f"  Top result: {results_without[0].get('command', 'N/A')} "
                       f"(score: {results_without[0].get('score', 0):.3f})")
        
        speedup = time_without / time_with if time_with > 0 else 1.0
        logger.info(f"\n⚡ Speedup: {speedup:.2f}x")


def test_filter_extraction():
    """Test metadata filter extraction."""
    logger.info("\n" + "=" * 80)
    logger.info("TESTING METADATA FILTER EXTRACTION")
    logger.info("=" * 80)
    
    from advisor.metadata_filters import extract_pyegeria_filters, extract_cli_filters
    
    # Test PyEgeria filter extraction
    pyegeria_queries = [
        "what methods are in CollectionManager?",
        "show me async methods",
        "list all classes in admin module",
        "what private methods does GlossaryManager have?",
    ]
    
    logger.info("\nPyEgeria Filter Extraction:")
    for query in pyegeria_queries:
        filters = extract_pyegeria_filters(query)
        logger.info(f"\nQuery: {query}")
        logger.info(f"Filters: {filters}")
    
    # Test CLI filter extraction
    cli_queries = [
        "how do I list glossaries?",
        "show me asset create commands",
        "what are the project commands?",
    ]
    
    logger.info("\n\nCLI Filter Extraction:")
    for query in cli_queries:
        filters = extract_cli_filters(query)
        logger.info(f"\nQuery: {query}")
        logger.info(f"Filters: {filters}")


def verify_collection_schema():
    """Verify that collections have the required scalar fields."""
    logger.info("\n" + "=" * 80)
    logger.info("VERIFYING COLLECTION SCHEMAS")
    logger.info("=" * 80)
    
    from pymilvus import Collection, connections
    
    connections.connect('default', host='localhost', port='19530')
    
    # Check PyEgeria collection
    logger.info("\nPyEgeria Collection:")
    pyegeria = Collection('pyegeria')
    logger.info(f"  Entities: {pyegeria.num_entities}")
    logger.info(f"  Schema fields:")
    for field in pyegeria.schema.fields:
        logger.info(f"    - {field.name}: {field.dtype}")
    
    # Check CLI Commands collection
    logger.info("\nCLI Commands Collection:")
    cli_commands = Collection('cli_commands')
    logger.info(f"  Entities: {cli_commands.num_entities}")
    logger.info(f"  Schema fields:")
    for field in cli_commands.schema.fields:
        logger.info(f"    - {field.name}: {field.dtype}")


def main():
    """Run all tests."""
    logger.info("=" * 80)
    logger.info("METADATA FILTERING TEST SUITE")
    logger.info("=" * 80)
    
    try:
        # Verify schemas first
        verify_collection_schema()
        
        # Test filter extraction
        test_filter_extraction()
        
        # Test PyEgeria filtering
        test_pyegeria_filtering()
        
        # Test CLI filtering
        test_cli_filtering()
        
        logger.info("\n" + "=" * 80)
        logger.info("✓ ALL TESTS COMPLETED")
        logger.info("=" * 80)
        
        return 0
        
    except Exception as e:
        logger.error(f"\n✗ Test failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())