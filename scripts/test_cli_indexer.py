#!/usr/bin/env python3
"""
Test script for CLI command indexer.

Tests indexing of CLI commands into vector store.
"""

import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.data_prep.cli_indexer import index_cli_commands_from_file
from loguru import logger

def main():
    """Test CLI command indexing."""
    
    # Path to CLI commands JSON file
    commands_file = Path("cache/cli_commands.json")
    
    if not commands_file.exists():
        logger.error(f"CLI commands file not found at {commands_file}")
        logger.info("Please run scripts/test_cli_parser.py first to extract commands")
        return 1
    
    logger.info(f"Testing CLI indexer with commands from: {commands_file}")
    logger.info("="*60)
    
    # Index commands
    try:
        stats = index_cli_commands_from_file(
            commands_file=commands_file,
            collection_name="cli_commands"
        )
        
        logger.info("\n" + "="*60)
        logger.info("Indexing Statistics:")
        logger.info("="*60)
        for key, value in stats.items():
            logger.info(f"  {key}: {value}")
        
        logger.info("\n" + "="*60)
        logger.info("Indexing complete!")
        logger.info("="*60)
        
        return 0
        
    except Exception as e:
        logger.error(f"Indexing failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())