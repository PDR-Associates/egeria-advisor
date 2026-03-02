#!/usr/bin/env python3
"""
Terminal-based monitoring dashboard using Rich.

Displays real-time metrics for collections, queries, and system resources.
"""

import sys
import time
from pathlib import Path
from typing import Dict, List

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from rich.console import Console
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, BarColumn, TextColumn
from rich.text import Text

from advisor.metrics_collector import get_metrics_collector, CollectionHealth
from advisor.collection_config import get_enabled_collections


console = Console()


def create_collection_health_table(collector) -> Table:
    """Create table showing collection health."""
    table = Table(title="Collection Health", show_header=True, header_style="bold cyan")
    table.add_column("Collection", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Entities", justify="right", style="magenta")
    table.add_column("Health", justify="right", style="green")
    table.add_column("Size (MB)", justify="right", style="yellow")
    
    health_data = collector.get_collection_health()
    
    if not health_data:
        # Show enabled collections with placeholder data
        for collection in get_enabled_collections():
            table.add_row(
                collection.name,
                "🟡 Unknown",
                "-",
                "-",
                "-"
            )
    else:
        for health in health_data:
            # Status emoji
            if health['status'] == 'healthy':
                status = "🟢 Healthy"
            elif health['status'] == 'degraded':
                status = "🟡 Degraded"
            else:
                status = "🔴 Critical"
            
            table.add_row(
                health['collection_name'],
                status,
                f"{health['entity_count']:,}",
                f"{health['health_score']:.1f}",
                f"{health['storage_size_mb']:.2f}"
            )
    
    return table


def create_query_stats_panel(collector) -> Panel:
    """Create panel showing query statistics."""
    stats = collector.get_query_stats(hours=1)
    
    content = Text()
    content.append("Last Hour Statistics\n\n", style="bold cyan")
    content.append(f"Total Queries: ", style="white")
    content.append(f"{stats['total_queries']}\n", style="bold green")
    content.append(f"Success Rate: ", style="white")
    content.append(f"{stats['success_rate']:.1%}\n", style="bold green")
    content.append(f"Cache Hit Rate: ", style="white")
    content.append(f"{stats['cache_hit_rate']:.1%}\n", style="bold green")
    content.append(f"\nLatency (ms):\n", style="bold white")
    content.append(f"  Average: {stats['avg_latency_ms']:.1f}\n", style="yellow")
    content.append(f"  P50: {stats['p50_latency_ms']:.1f}\n", style="yellow")
    content.append(f"  P95: {stats['p95_latency_ms']:.1f}\n", style="yellow")
    content.append(f"  P99: {stats['p99_latency_ms']:.1f}\n", style="yellow")
    
    return Panel(content, title="Query Performance", border_style="green")


def create_system_metrics_panel(collector) -> Panel:
    """Create panel showing system resource metrics."""
    metrics = collector.collect_system_metrics()
    
    content = Text()
    content.append("System Resources\n\n", style="bold cyan")
    
    # CPU
    cpu_color = "green" if metrics.cpu_percent < 70 else "yellow" if metrics.cpu_percent < 90 else "red"
    content.append(f"CPU: ", style="white")
    content.append(f"{metrics.cpu_percent:.1f}%\n", style=f"bold {cpu_color}")
    
    # Memory
    mem_color = "green" if metrics.memory_percent < 70 else "yellow" if metrics.memory_percent < 90 else "red"
    content.append(f"Memory: ", style="white")
    content.append(f"{metrics.memory_percent:.1f}%\n", style=f"bold {mem_color}")
    
    # GPU (if available)
    if metrics.gpu_percent is not None:
        gpu_color = "green" if metrics.gpu_percent < 70 else "yellow" if metrics.gpu_percent < 90 else "red"
        content.append(f"GPU: ", style="white")
        content.append(f"{metrics.gpu_percent:.1f}%\n", style=f"bold {gpu_color}")
    
    content.append(f"\nDisk I/O:\n", style="bold white")
    content.append(f"  Read: {metrics.disk_io_read_mb:.2f} MB\n", style="cyan")
    content.append(f"  Write: {metrics.disk_io_write_mb:.2f} MB\n", style="cyan")
    
    content.append(f"\nNetwork:\n", style="bold white")
    content.append(f"  Sent: {metrics.network_sent_mb:.2f} MB\n", style="magenta")
    content.append(f"  Recv: {metrics.network_recv_mb:.2f} MB\n", style="magenta")
    
    return Panel(content, title="System Status", border_style="blue")


def create_recent_queries_table(collector) -> Table:
    """Create table showing recent queries."""
    table = Table(title="Recent Queries (Last 10)", show_header=True, header_style="bold cyan")
    table.add_column("Time", style="cyan", width=8)
    table.add_column("Query", style="white", width=40, overflow="ellipsis")
    table.add_column("Collection", style="yellow", width=15)
    table.add_column("Latency", justify="right", style="magenta", width=10)
    table.add_column("Status", justify="center", width=8)
    
    queries = collector.get_recent_queries(limit=10)
    
    for query in queries:
        # Format timestamp
        time_str = time.strftime("%H:%M:%S", time.localtime(query['timestamp']))
        
        # Truncate query text
        query_text = query['query_text'][:37] + "..." if len(query['query_text']) > 40 else query['query_text']
        
        # Collection name
        collection = query['collection_name'] or "N/A"
        
        # Latency with color
        latency = f"{query['latency_ms']:.1f}ms"
        
        # Status
        if query['success']:
            if query['cache_hit']:
                status = "🟢 Cache"
            else:
                status = "🟢 OK"
        else:
            status = "🔴 Error"
        
        table.add_row(time_str, query_text, collection, latency, status)
    
    return table


def create_dashboard_layout() -> Layout:
    """Create the dashboard layout with focus on queries and collections."""
    layout = Layout()
    
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=3)
    )
    
    # Main body: 70% queries/collections, 30% stats/system
    layout["body"].split_row(
        Layout(name="main", ratio=7),
        Layout(name="sidebar", ratio=3)
    )
    
    # Main area: Recent queries (60%) and collections (40%)
    layout["main"].split_column(
        Layout(name="queries", ratio=6),
        Layout(name="collections", ratio=4)
    )
    
    # Sidebar: Compact stats and system
    layout["sidebar"].split_column(
        Layout(name="stats", ratio=5),
        Layout(name="system", ratio=5)
    )
    
    return layout


def update_dashboard(layout: Layout, collector):
    """Update dashboard with current metrics."""
    # Header
    header = Panel(
        Text("Egeria Advisor Monitoring Dashboard", justify="center", style="bold white"),
        style="bold cyan"
    )
    layout["header"].update(header)
    
    # Recent queries (larger, more prominent)
    layout["queries"].update(create_recent_queries_table(collector))
    
    # Collections (more compact)
    layout["collections"].update(create_collection_health_table(collector))
    
    # Query stats (compact)
    layout["stats"].update(create_query_stats_panel(collector))
    
    # System metrics (compact)
    layout["system"].update(create_system_metrics_panel(collector))
    
    # Footer
    footer_text = Text()
    footer_text.append("Press ", style="white")
    footer_text.append("Ctrl+C", style="bold red")
    footer_text.append(" to exit | Refreshing every 5 seconds", style="white")
    footer = Panel(footer_text, style="dim")
    layout["footer"].update(footer)


def main():
    """Run the terminal dashboard."""
    console.print(Panel.fit(
        "[bold cyan]Egeria Advisor Monitoring Dashboard[/bold cyan]\n"
        "Real-time metrics for collections, queries, and system resources",
        border_style="cyan"
    ))
    
    collector = get_metrics_collector()
    layout = create_dashboard_layout()
    
    try:
        with Live(layout, console=console, screen=True, refresh_per_second=0.2) as live:
            while True:
                update_dashboard(layout, collector)
                time.sleep(5)  # Refresh every 5 seconds
    
    except KeyboardInterrupt:
        console.print("\n[yellow]Dashboard stopped.[/yellow]")


if __name__ == "__main__":
    main()