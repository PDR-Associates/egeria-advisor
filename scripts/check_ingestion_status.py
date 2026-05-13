#!/usr/bin/env python3
"""
Check the status of collection ingestion in Milvus.
Shows entity counts and index status for all collections.
"""

from pymilvus import connections, Collection, utility
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
import sys

def check_status():
    """Check and display collection ingestion status."""
    console = Console()
    
    try:
        # Connect to Milvus
        connections.connect(host='localhost', port='19530')
        
        # Get all collections
        collections = utility.list_collections()
        
        if not collections:
            console.print("[yellow]No collections found in Milvus[/yellow]")
            return
        
        # Create table
        table = Table(title="Milvus Collection Status", show_header=True, header_style="bold magenta")
        table.add_column("Collection", style="cyan", width=20)
        table.add_column("Entities", justify="right", style="green")
        table.add_column("Status", style="yellow")
        
        total_entities = 0
        phase2_collections = ['egeria_java', 'egeria_docs', 'egeria_workspaces']
        phase2_status = {}
        
        for coll_name in sorted(collections):
            coll = Collection(coll_name)
            
            try:
                # Get entity count first (works without index)
                count = coll.num_entities
                
                # Try to load collection (requires index)
                try:
                    coll.load()
                    status = "✅ Indexed & Ready"
                    total_entities += count
                    
                    if coll_name in phase2_collections:
                        phase2_status[coll_name] = ('complete', count)
                except Exception as load_error:
                    # Collection exists but no index yet (still ingesting)
                    if "index not found" in str(load_error):
                        status = f"🔄 Ingesting ({count:,} entities)"
                        if coll_name in phase2_collections:
                            phase2_status[coll_name] = ('ingesting', count)
                    else:
                        status = f"⚠️ No Index ({count:,} entities)"
                        if coll_name in phase2_collections:
                            phase2_status[coll_name] = ('no_index', count)
                    
            except Exception as e:
                # Collection exists but can't get count
                status = f"❌ Error: {str(e)[:30]}"
                count = "?"
                if coll_name in phase2_collections:
                    phase2_status[coll_name] = ('error', 0)
            
            table.add_row(coll_name, str(count) if count != "?" else count, status)
        
        # Display table
        console.print()
        console.print(table)
        console.print()
        console.print(f"[bold]Total Entities:[/bold] {total_entities:,}")
        console.print()
        
        # Phase 2 status summary
        console.print(Panel.fit(
            "[bold cyan]Phase 2 Collections Status[/bold cyan]\n\n" +
            f"egeria_java: {phase2_status.get('egeria_java', ('pending', 0))[0]}\n" +
            f"egeria_docs: {phase2_status.get('egeria_docs', ('pending', 0))[0]}\n" +
            f"egeria_workspaces: {phase2_status.get('egeria_workspaces', ('pending', 0))[0]}",
            title="Phase 2 Progress"
        ))
        
        # Check if all Phase 2 collections are complete
        all_complete = all(
            phase2_status.get(coll, ('pending', 0))[0] == 'complete' 
            for coll in phase2_collections
        )
        
        if all_complete:
            console.print("\n[bold green]✅ All Phase 2 collections are complete![/bold green]")
            console.print("\n[bold]Next steps:[/bold]")
            console.print("1. Test Phase 2 routing with Java/docs/workspace queries")
            console.print("2. Run comprehensive multi-collection tests")
            console.print("3. Commit changes to git")
        else:
            console.print("\n[yellow]⏳ Phase 2 ingestion still in progress...[/yellow]")
            console.print("\n[bold]To monitor progress:[/bold]")
            console.print("  watch -n 30 python scripts/check_ingestion_status.py")
        
    except Exception as e:
        console.print(f"[red]Error connecting to Milvus: {e}[/red]")
        sys.exit(1)
    finally:
        try:
            connections.disconnect('default')
        except:
            pass

if __name__ == "__main__":
    check_status()