#!/usr/bin/env python3
"""
Diagnose retrieval issues - check if data is in Milvus and if search works.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pymilvus import connections, utility, Collection
from rich.console import Console
from rich.table import Table

console = Console()


def check_milvus_connection():
    """Check if Milvus is accessible."""
    console.print("\n[bold cyan]1. Checking Milvus Connection...[/bold cyan]")
    try:
        connections.connect(host="localhost", port="19530")
        console.print("  [green]✓[/green] Connected to Milvus")
        return True
    except Exception as e:
        console.print(f"  [red]✗[/red] Failed to connect: {e}")
        return False


def check_collections():
    """Check what collections exist."""
    console.print("\n[bold cyan]2. Checking Collections...[/bold cyan]")
    try:
        collections = utility.list_collections()
        console.print(f"  Found {len(collections)} collections:")
        for coll in collections:
            console.print(f"    • {coll}")
        return collections
    except Exception as e:
        console.print(f"  [red]✗[/red] Error: {e}")
        return []


def check_collection_data(collection_name: str):
    """Check if a collection has data."""
    console.print(f"\n[bold cyan]3. Checking '{collection_name}' Collection...[/bold cyan]")
    try:
        collection = Collection(collection_name)
        collection.load()
        
        num_entities = collection.num_entities
        console.print(f"  Total entities: [cyan]{num_entities}[/cyan]")
        
        if num_entities == 0:
            console.print("  [yellow]⚠[/yellow] Collection is empty!")
            return False
        
        # Try a simple search
        console.print("\n  Testing search for 'glossary'...")
        results = collection.search(
            data=[[0.1] * 384],  # Dummy vector
            anns_field="embedding",
            param={"metric_type": "L2", "params": {"nprobe": 10}},
            limit=5
        )
        
        console.print(f"  [green]✓[/green] Search works, found {len(results[0])} results")
        return True
        
    except Exception as e:
        console.print(f"  [red]✗[/red] Error: {e}")
        return False


def test_vector_search():
    """Test actual vector search with embeddings."""
    console.print("\n[bold cyan]4. Testing Vector Search with Real Embeddings...[/bold cyan]")
    try:
        from advisor.embeddings import get_embedding_generator
        from advisor.vector_store import get_vector_store
        
        # Generate embedding for "glossary"
        emb_gen = get_embedding_generator()
        query_embedding = emb_gen.generate_embedding("glossary")
        console.print(f"  Generated embedding: {len(query_embedding)} dimensions")
        
        # Search
        vs = get_vector_store()
        results = vs.search(
            collection_name="code_elements",
            query_embedding=query_embedding,
            top_k=5
        )
        
        console.print(f"\n  Search results for 'glossary':")
        if results:
            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("#", style="dim")
            table.add_column("Score", justify="right")
            table.add_column("Name")
            table.add_column("File")
            
            for i, r in enumerate(results, 1):
                table.add_row(
                    str(i),
                    f"{r.score:.3f}",
                    r.metadata.get("name", "Unknown")[:40],
                    r.metadata.get("file_path", "Unknown")[:50]
                )
            
            console.print(table)
            return True
        else:
            console.print("  [yellow]⚠[/yellow] No results found!")
            return False
            
    except Exception as e:
        console.print(f"  [red]✗[/red] Error: {e}")
        import traceback
        console.print(traceback.format_exc())
        return False


def main():
    """Run all diagnostics."""
    console.print("\n" + "=" * 60)
    console.print("[bold cyan]Egeria Advisor - Retrieval Diagnostics[/bold cyan]")
    console.print("=" * 60)
    
    # Check connection
    if not check_milvus_connection():
        console.print("\n[red]✗ Cannot connect to Milvus. Is it running?[/red]")
        console.print("  Start with: docker start milvus-standalone")
        return 1
    
    # Check collections
    collections = check_collections()
    if not collections:
        console.print("\n[red]✗ No collections found. Data needs to be ingested.[/red]")
        console.print("  Run: python advisor/ingest_to_milvus.py")
        return 1
    
    # Check main collection
    if "egeria_code" in collections:
        if not check_collection_data("egeria_code"):
            console.print("\n[yellow]⚠ Collection exists but is empty or has issues.[/yellow]")
    else:
        console.print("\n[yellow]⚠ 'egeria_code' collection not found.[/yellow]")
        console.print("  Available collections:", collections)
    
    # Test actual search
    if not test_vector_search():
        console.print("\n[red]✗ Vector search is not working properly.[/red]")
        return 1
    
    # Summary
    console.print("\n" + "=" * 60)
    console.print("[bold green]✓ Diagnostics Complete[/bold green]")
    console.print("=" * 60)
    console.print("\nIf search is working but queries fail, the issue is likely:")
    console.print("  1. Retrieval threshold too high (min_score in config)")
    console.print("  2. Query embedding mismatch")
    console.print("  3. Metadata filtering issues")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())