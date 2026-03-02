"""
Interactive REPL Mode for Egeria Advisor

This module provides an interactive session with command history and context preservation.
"""

import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt, Confirm
from rich.table import Table

from advisor.cli.formatters import ResponseFormatter
from advisor.feedback_collector import get_feedback_collector


class InteractiveSession:
    """Interactive REPL session for the Egeria Advisor."""
    
    # Special commands
    COMMANDS = {
        '/help': 'Show help message',
        '/clear': 'Clear conversation context',
        '/history': 'Show query history',
        '/exit': 'Exit interactive mode',
        '/quit': 'Exit interactive mode',
        '/verbose': 'Toggle verbose mode',
        '/citations': 'Toggle citation display',
        '/feedback': 'Provide feedback on last response',
        '/stats': 'Show feedback statistics',
    }
    
    def __init__(self, rag_system, options: Dict[str, Any], console: Console):
        """
        Initialize interactive session.
        
        Parameters
        ----------
        rag_system
            RAG system instance
        options : dict
            CLI options
        console : Console
            Rich console for output
        """
        self.rag = rag_system
        self.options = options
        self.console = console
        
        # Session state
        self.context: List[Dict[str, str]] = []
        self.history: List[Dict[str, Any]] = []
        self.running = True
        self.last_response: Optional[Dict[str, Any]] = None
        self.last_query: Optional[str] = None
        
        # Options
        self.verbose = options.get('verbose', False)
        self.show_citations = options.get('show_citations', True)
        self.track_metrics = options.get('track_metrics', True)
        self.enable_feedback = options.get('enable_feedback', True)
        
        # Feedback system
        self.feedback_collector = get_feedback_collector() if self.enable_feedback else None
        self.session_id = str(uuid.uuid4())[:8]
        
        # Set up prompt session
        history_file = Path.home() / '.egeria_advisor_history'
        self.prompt_session = PromptSession(
            history=FileHistory(str(history_file)),
            auto_suggest=AutoSuggestFromHistory(),
            completer=self._create_completer(),
        )
        
        # Formatter
        self.formatter = ResponseFormatter(
            format_type='text',
            show_citations=self.show_citations,
            verbose=self.verbose
        )
    
    def _create_completer(self) -> WordCompleter:
        """Create command completer."""
        words = list(self.COMMANDS.keys()) + [
            'glossary', 'collection', 'asset', 'term', 'category',
            'create', 'find', 'update', 'delete', 'search',
            'how', 'what', 'why', 'when', 'where', 'show', 'example'
        ]
        return WordCompleter(words, ignore_case=True)
    
    def run(self):
        """Run the interactive REPL loop."""
        try:
            while self.running:
                try:
                    # Get user input
                    user_input = self.prompt_session.prompt('egeria> ')
                    
                    # Skip empty input
                    if not user_input.strip():
                        continue
                    
                    # Handle commands
                    if user_input.startswith('/'):
                        self._handle_command(user_input.strip())
                    else:
                        # Handle query
                        self._handle_query(user_input.strip())
                    
                    self.console.print()  # Add spacing
                
                except KeyboardInterrupt:
                    self.console.print("\n[dim]Use /exit or Ctrl+D to quit[/dim]")
                    continue
                except EOFError:
                    # Ctrl+D pressed
                    self.console.print("\n[cyan]Goodbye![/cyan]")
                    break
        
        finally:
            self._cleanup()
    
    def _handle_command(self, command: str):
        """
        Handle special commands.
        
        Parameters
        ----------
        command : str
            Command string starting with /
        """
        cmd = command.lower().split()[0]
        
        if cmd in ['/exit', '/quit']:
            self.console.print("[cyan]Goodbye![/cyan]")
            self.running = False
        
        elif cmd == '/help':
            self._show_help()
        
        elif cmd == '/clear':
            self.context.clear()
            self.console.print("[green]✓[/green] Conversation context cleared")
        
        elif cmd == '/history':
            self._show_history()
        
        elif cmd == '/verbose':
            self.verbose = not self.verbose
            self.formatter.verbose = self.verbose
            status = "enabled" if self.verbose else "disabled"
            self.console.print(f"[green]✓[/green] Verbose mode {status}")
        
        elif cmd == '/citations':
            self.show_citations = not self.show_citations
            self.formatter.show_citations = self.show_citations
            status = "enabled" if self.show_citations else "disabled"
            self.console.print(f"[green]✓[/green] Citations {status}")
        
        elif cmd == '/feedback':
            self._handle_feedback_command()
        
        elif cmd == '/stats':
            self._show_feedback_stats()
        
        else:
            self.console.print(f"[yellow]Unknown command:[/yellow] {cmd}")
            self.console.print("[dim]Type /help for available commands[/dim]")
    
    def _handle_query(self, query: str):
        """
        Handle user query.
        
        Parameters
        ----------
        query : str
            User's query
        """
        # Show processing indicator
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
            transient=True
        ) as progress:
            progress.add_task("Processing...", total=None)
            
            try:
                # Build context from recent history
                context_str = self._build_context()
                
                # Execute query
                result = self.rag.query(
                    user_query=query,
                    include_context=True,
                    track_metrics=self.track_metrics
                )
                
                # Store last query and response for feedback
                self.last_query = query
                self.last_response = result
                
                # Add to history
                self.history.append({
                    'query': query,
                    'response': result.get('response', ''),
                    'sources': result.get('sources', [])
                })
                
                # Update context
                self.context.append({
                    'query': query,
                    'response': result.get('response', '')
                })
                
                # Keep only last 5 exchanges
                if len(self.context) > 5:
                    self.context = self.context[-5:]
                
                # Display result
                self.formatter.display(result, self.console)
                
                # Optionally prompt for feedback
                if self.enable_feedback and self.feedback_collector:
                    self._prompt_for_feedback()
            
            except Exception as e:
                self.console.print(f"[red]✗ Error:[/red] {e}")
                if self.verbose:
                    self.console.print_exception()
    
    def _build_context(self) -> Optional[str]:
        """
        Build context string from recent conversation.
        
        Returns
        -------
        str or None
            Context string or None if no context
        """
        if not self.context:
            return None
        
        context_parts = []
        for exchange in self.context[-3:]:  # Last 3 exchanges
            context_parts.append(f"Q: {exchange['query']}")
            context_parts.append(f"A: {exchange['response'][:200]}...")  # Truncate
        
        return "\n".join(context_parts)
    
    def _show_help(self):
        """Show help message."""
        help_text = "[bold cyan]Available Commands:[/bold cyan]\n\n"
        
        for cmd, desc in self.COMMANDS.items():
            help_text += f"  [cyan]{cmd:12}[/cyan] - {desc}\n"
        
        help_text += "\n[bold cyan]Tips:[/bold cyan]\n"
        help_text += "  • Ask questions in natural language\n"
        help_text += "  • Request code examples: 'Show me how to create a glossary'\n"
        help_text += "  • Context is preserved across queries in the session\n"
        help_text += "  • Use arrow keys to navigate history\n"
        
        self.console.print(Panel(help_text, border_style="cyan", padding=(1, 2)))
    
    def _show_history(self):
        """Show query history."""
    def _prompt_for_feedback(self):
        """Prompt user for feedback on the last response."""
        if not self.last_response or not self.last_query:
            return
        
        self.console.print()
        self.console.print("[dim]─[/dim]" * 70)
        
        # Ask if they want to provide feedback
        provide_feedback = Confirm.ask(
            "[cyan]Would you like to provide feedback on this response?[/cyan]",
            default=False
        )
        
        if not provide_feedback:
            return
        
        # Ask for rating
        self.console.print("\n[cyan]Was this answer helpful?[/cyan]")
        self.console.print("  [green]1[/green] - Yes, very helpful 👍")
        self.console.print("  [yellow]2[/yellow] - Somewhat helpful")
        self.console.print("  [red]3[/red] - Not helpful 👎")
        
        rating_input = Prompt.ask("Your rating", choices=["1", "2", "3"], default="1")
        
        # Map to rating
        rating_map = {"1": "positive", "2": "neutral", "3": "negative"}
        rating = rating_map[rating_input]
        
        # Collect additional feedback for negative ratings
        feedback_text = None
        suggested_collection = None
        user_comment = None
        
        if rating == "negative":
            self.console.print("\n[yellow]What was the problem?[/yellow]")
            self.console.print("  [cyan]1[/cyan] - Wrong information")
            self.console.print("  [cyan]2[/cyan] - Incomplete answer")
            self.console.print("  [cyan]3[/cyan] - Wrong collection searched")
            self.console.print("  [cyan]4[/cyan] - Poor code example")
            self.console.print("  [cyan]5[/cyan] - Other")
            
            problem_choice = Prompt.ask("Choose", choices=["1", "2", "3", "4", "5"], default="5")
            
            problem_map = {
                "1": "Wrong information provided",
                "2": "Answer was incomplete",
                "3": "Searched wrong collection",
                "4": "Code example was poor quality",
                "5": "Other issue"
            }
            feedback_text = problem_map[problem_choice]
            
            # Ask for suggested collection if routing issue
            if problem_choice == "3":
                self.console.print("\n[cyan]Which collection should have been searched?[/cyan]")
                self.console.print("[dim]Available: pyegeria, pyegeria_cli, pyegeria_drE,[/dim]")
                self.console.print("[dim]           egeria_java, egeria_docs, egeria_workspaces[/dim]")
                suggested = Prompt.ask("Suggested collection", default="")
                if suggested:
                    suggested_collection = suggested
        
        # Ask for optional comment
        if rating in ["negative", "neutral"]:
            self.console.print("\n[cyan]Any additional comments?[/cyan] [dim](optional)[/dim]")
            comment = Prompt.ask("Comment", default="")
            if comment:
                user_comment = comment
        
        # Record feedback
        if not self.feedback_collector:
            self.console.print("[yellow]Feedback collection is disabled[/yellow]")
            return
        
        try:
            self.feedback_collector.record_feedback(
                query=self.last_query,
                query_type=self.last_response.get('query_type', 'unknown'),
                collections_searched=self.last_response.get('collections_searched', []),
                response_length=len(self.last_response.get('response', '')),
                rating=rating,
                feedback_text=feedback_text,
                suggested_collection=suggested_collection,
                user_comment=user_comment,
                session_id=self.session_id
            )
            self.console.print("[green]✓[/green] Thank you for your feedback!")
        except Exception as e:
            self.console.print(f"[red]✗[/red] Failed to record feedback: {e}")
    
    def _handle_feedback_command(self):
        """Handle /feedback command to provide feedback on last response."""
        if not self.feedback_collector:
            self.console.print("[yellow]Feedback collection is disabled[/yellow]")
            return
        
        if not self.last_response or not self.last_query:
            self.console.print("[yellow]No previous response to provide feedback on[/yellow]")
            return
        
        # Show last query and response summary
        self.console.print("\n[bold cyan]Last Query:[/bold cyan]")
        self.console.print(f"  {self.last_query}")
        self.console.print(f"\n[bold cyan]Response:[/bold cyan]")
        response_preview = self.last_response.get('response', '')[:200]
        self.console.print(f"  {response_preview}...")
        self.console.print()
        
        # Prompt for feedback
        self._prompt_for_feedback()
    
    def _show_feedback_stats(self):
        """Show feedback statistics."""
        if not self.feedback_collector:
            self.console.print("[yellow]Feedback collection is disabled[/yellow]")
            return
        
        try:
            stats = self.feedback_collector.get_feedback_stats()
            
            if stats['total'] == 0:
                self.console.print("[dim]No feedback recorded yet[/dim]")
                return
            
            # Create statistics table
            table = Table(title="Feedback Statistics", show_header=True, header_style="bold cyan")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", justify="right")
            
            table.add_row("Total Feedback", str(stats['total']))
            table.add_row("Positive", f"[green]{stats['positive']}[/green]")
            table.add_row("Negative", f"[red]{stats['negative']}[/red]")
            table.add_row("Neutral", f"[yellow]{stats.get('neutral', 0)}[/yellow]")
            table.add_row("Satisfaction Rate", f"{stats['satisfaction_rate']:.1%}")
            
            self.console.print()
            self.console.print(table)
            
            # Show by query type if available
            if stats.get('by_query_type'):
                self.console.print("\n[bold cyan]By Query Type:[/bold cyan]")
                for qtype, data in stats['by_query_type'].items():
                    satisfaction = data.get('positive', 0) / data['total'] if data['total'] > 0 else 0
                    self.console.print(f"  {qtype:20} - {data['total']:3} queries ({satisfaction:.1%} positive)")
            
            # Show routing corrections if any
            if stats.get('routing_corrections'):
                self.console.print(f"\n[bold yellow]Routing Corrections:[/bold yellow] {len(stats['routing_corrections'])}")
                for correction in stats['routing_corrections'][:5]:  # Show first 5
                    self.console.print(f"  • {correction['query'][:50]}...")
                    self.console.print(f"    [dim]Searched: {', '.join(correction['searched'])}[/dim]")
                    self.console.print(f"    [dim]Suggested: {correction['suggested']}[/dim]")
        
        except Exception as e:
            self.console.print(f"[red]✗[/red] Failed to get feedback stats: {e}")
    
        if not self.history:
            self.console.print("[dim]No queries in history[/dim]")
            return
        
        self.console.print("[bold cyan]Query History:[/bold cyan]\n")
        
        for i, entry in enumerate(self.history[-10:], 1):  # Last 10 queries
            query = entry['query']
            num_sources = len(entry.get('sources', []))
            
            self.console.print(f"  [cyan]{i}.[/cyan] {query}")
            if self.verbose:
                self.console.print(f"     [dim]({num_sources} sources)[/dim]")
    
    def _cleanup(self):
        """Clean up session resources."""
        # Save any session data if needed
        pass


class SessionManager:
    """Manage session state and persistence."""
    
    def __init__(self, session_file: Optional[Path] = None):
        """
        Initialize session manager.
        
        Parameters
        ----------
        session_file : Path, optional
            Path to session file
        """
        if session_file is None:
            session_file = Path.home() / '.egeria_advisor_session.json'
        
        self.session_file = session_file
        self.session_data = {}
    
    def save_session(self, context: List[Dict], history: List[Dict]):
        """
        Save session to file.
        
        Parameters
        ----------
        context : list
            Conversation context
        history : list
            Query history
        """
        import json
        
        self.session_data = {
            'context': context,
            'history': history
        }
        
        try:
            with open(self.session_file, 'w') as f:
                json.dump(self.session_data, f, indent=2)
        except Exception:
            pass  # Silently fail if can't save
    
    def load_session(self) -> Dict[str, List]:
        """
        Load session from file.
        
        Returns
        -------
        dict
            Session data with 'context' and 'history' keys
        """
        import json
        
        if not self.session_file.exists():
            return {'context': [], 'history': []}
        
        try:
            with open(self.session_file, 'r') as f:
                return json.load(f)
        except Exception:
            return {'context': [], 'history': []}