#!/usr/bin/env python3
"""
Check if ProjectManager exists in PyEgeria collection.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.vector_store import get_vector_store
from pymilvus import Collection
from rich.console import Console
from rich.table import Table

console = Console()

def check_projectmanager():
    """Check if ProjectManager is in the collection."""
    
    console.print("[bold cyan]Checking PyEgeria Collection for ProjectManager...[/bold cyan]\n")
    
    # Connect to vector store
    vs = get_vector_store()
    vs.connect()
    
    collection_name = "pyegeria_drE"
    
    # Get collection
    collection = Collection(collection_name)
    collection.load()
    
    # Check total count
    total = collection.num_entities
    console.print(f"[bold]Total entities in collection:[/bold] {total:,}\n")
    
    # Search for ProjectManager by class_name
    console.print("[bold]Searching for ProjectManager by class_name...[/bold]")
    results = collection.query(
        expr='class_name == "ProjectManager"',
        output_fields=['class_name', 'element_type', 'method_name', 'metadata'],
        limit=10
    )
    
    if results:
        console.print(f"[green]✓ Found {len(results)} items with class_name='ProjectManager'[/green]\n")
        
        table = Table(title="ProjectManager Items")
        table.add_column("Type", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("File", style="yellow")
        
        for r in results[:5]:
            element_type = r.get('element_type', 'unknown')
            name = r.get('method_name', r.get('class_name', 'unknown'))
            metadata = r.get('metadata', {})
            file_path = metadata.get('file_path', 'unknown')
            file_name = Path(file_path).name if file_path != 'unknown' else 'unknown'
            
            table.add_row(element_type, name, file_name)
        
        console.print(table)
    else:
        console.print("[red]✗ No items found with class_name='ProjectManager'[/red]")
        console.print("\n[yellow]Trying semantic search...[/yellow]")
        
        # Try semantic search
        from advisor.agents.pyegeria_agent import get_pyegeria_agent
        agent = get_pyegeria_agent()
        
        search_results = agent.search_pyegeria("ProjectManager", top_k=5, min_score=0.0)
        
        if search_results:
            console.print(f"[green]✓ Semantic search found {len(search_results)} results[/green]\n")
            
            table = Table(title="Semantic Search Results")
            table.add_column("Score", style="cyan")
            table.add_column("Text Preview", style="green")
            
            for r in search_results:
                score = r.get('score', 0.0)
                text = r.get('text', '')[:100]
                table.add_row(f"{score:.3f}", text)
            
            console.print(table)
        else:
            console.print("[red]✗ Semantic search also found nothing[/red]")
            console.print("\n[bold red]ProjectManager is NOT in the collection![/bold red]")
            console.print("[yellow]You may need to re-index the PyEgeria collection.[/yellow]")

if __name__ == "__main__":
    check_projectmanager()