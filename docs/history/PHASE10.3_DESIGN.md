# Phase 10.3: Agent CLI Integration - Design

**Version:** 1.0  
**Date:** 2026-02-20  
**Status:** 🚧 In Progress

## Overview

Integrate MCP tool execution capabilities into the main agent CLI (`egeria-advisor --agent --interactive`), providing a unified conversational interface with tool invocation.

## Goals

1. **Seamless Integration**: Add MCP tools to existing agent CLI without breaking current functionality
2. **Unified Experience**: Single CLI for conversation + tool execution
3. **Context Awareness**: Tools invoked within conversation context
4. **User-Friendly**: Intuitive commands and helpful feedback
5. **Backward Compatible**: Existing agent features continue to work

## Current State

### What Works Now

**Agent CLI** (`advisor/cli/agent_session.py`):
- ✅ Conversational agent with memory
- ✅ RAG-enhanced responses
- ✅ Response caching
- ✅ Commands: `/help`, `/clear`, `/history`, `/stats`, `/verbose`, `/citations`, `/exit`

**MCP Tools** (in example CLIs only):
- ✅ Tool discovery and listing
- ✅ Tool execution with parameter input
- ✅ Pretty printing for results
- ✅ Metrics tracking
- ✅ Command abbreviations

### What's Missing

❌ MCP agent initialization in agent CLI  
❌ Tool-related commands in agent CLI  
❌ Tool execution within conversation  
❌ Pretty printing for tool results in agent CLI  
❌ Tool metrics in agent CLI

## Design

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│              Agent CLI (agent_session.py)                    │
│                                                              │
│  ┌────────────────┐      ┌──────────────────┐              │
│  │ Conversation   │      │   MCP Agent      │              │
│  │ Agent          │      │                  │              │
│  │                │      │  - Tool Discovery│              │
│  │ - Memory       │◄────►│  - Tool Execution│              │
│  │ - RAG          │      │  - Metrics       │              │
│  │ - Cache        │      │  - Cache         │              │
│  └────────────────┘      └──────────────────┘              │
│         │                         │                         │
│         │                         │                         │
│         ▼                         ▼                         │
│  ┌────────────────────────────────────────┐                │
│  │         User Commands                   │                │
│  │                                         │                │
│  │  Conversation:  Regular queries         │                │
│  │  Tools:         /tools, /execute        │                │
│  │  Metrics:       /metrics, /stats        │                │
│  │  Management:    /clear, /history        │                │
│  └────────────────────────────────────────┘                │
└─────────────────────────────────────────────────────────────┘
```

### New Commands

Add to `AgentInteractiveSession.COMMANDS`:

```python
COMMANDS = {
    # Existing commands
    '/help': 'Show help message',
    '/clear': 'Clear conversation history',
    '/history': 'Show conversation history',
    '/stats': 'Show agent statistics',
    '/exit': 'Exit interactive mode',
    '/quit': 'Exit interactive mode',
    '/verbose': 'Toggle verbose mode',
    '/citations': 'Toggle citation display',
    
    # New MCP tool commands
    '/tools': 'List available MCP tools',
    '/execute': 'Execute an MCP tool',
    '/exec': 'Execute an MCP tool (alias)',
    '/e': 'Execute an MCP tool (short alias)',
    '/metrics': 'Show MCP tool metrics',
    '/clear-cache': 'Clear MCP tool cache',
    '/cc': 'Clear MCP tool cache (alias)',
}
```

### Command Implementations

#### 1. `/tools` - List Available Tools

```python
def _show_tools(self):
    """Show available MCP tools."""
    if not self.mcp_agent:
        self.console.print("[yellow]MCP tools not available[/yellow]")
        return
    
    tools = self.mcp_agent.get_available_tools()
    
    if not tools:
        self.console.print("[dim]No MCP tools available[/dim]")
        return
    
    table = Table(title="Available MCP Tools", show_header=True)
    table.add_column("Tool", style="cyan")
    table.add_column("Description")
    table.add_column("Server", style="dim")
    
    for tool in tools:
        table.add_row(
            tool.name,
            tool.description or "No description",
            tool.server_name
        )
    
    self.console.print(table)
```

#### 2. `/execute` - Execute a Tool

```python
async def _execute_tool(self, command: str):
    """Execute an MCP tool."""
    if not self.mcp_agent:
        self.console.print("[yellow]MCP tools not available[/yellow]")
        return
    
    # Parse command: /execute tool_name or /e tool_name
    parts = command.split(maxsplit=1)
    if len(parts) < 2:
        self.console.print("[yellow]Usage: /execute <tool_name>[/yellow]")
        return
    
    tool_name = parts[1].strip()
    
    # Get tool info
    tool = self.mcp_agent.get_tool(tool_name)
    if not tool:
        self.console.print(f"[red]Tool not found:[/red] {tool_name}")
        return
    
    # Get parameters interactively
    arguments = self._get_tool_arguments(tool)
    
    # Execute tool
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
            transient=True
        ) as progress:
            progress.add_task(f"Executing {tool_name}...", total=None)
            result = await self.mcp_agent.execute_tool(tool_name, arguments)
        
        # Display result
        self._display_tool_result(result)
    
    except Exception as e:
        self.console.print(f"[red]✗ Tool execution failed:[/red] {e}")
        if self.verbose:
            self.console.print_exception()
```

#### 3. `/metrics` - Show MCP Metrics

```python
def _show_mcp_metrics(self):
    """Show MCP tool metrics."""
    if not self.mcp_agent:
        self.console.print("[yellow]MCP tools not available[/yellow]")
        return
    
    metrics = self.mcp_agent.get_metrics()
    
    table = Table(title="MCP Tool Metrics", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    
    table.add_row("Total Calls", str(metrics.get('total_calls', 0)))
    table.add_row("Successful Calls", str(metrics.get('successful_calls', 0)))
    table.add_row("Failed Calls", str(metrics.get('failed_calls', 0)))
    table.add_row("Success Rate", f"{metrics.get('success_rate', 0):.1%}")
    table.add_row("Cache Hits", str(metrics.get('cache_hits', 0)))
    table.add_row("Cache Misses", str(metrics.get('cache_misses', 0)))
    table.add_row("Avg Execution Time", f"{metrics.get('avg_execution_time', 0):.2f}s")
    
    self.console.print(table)
```

### Helper Functions

#### Get Tool Arguments Interactively

```python
def _get_tool_arguments(self, tool: MCPTool) -> dict:
    """Get tool arguments from user input."""
    arguments = {}
    schema = tool.input_schema
    
    if not schema or 'properties' not in schema:
        return arguments
    
    properties = schema['properties']
    required = schema.get('required', [])
    
    self.console.print(f"\n[bold]Parameters for {tool.name}:[/bold]")
    
    for param_name, param_info in properties.items():
        param_type = param_info.get('type', 'string')
        description = param_info.get('description', '')
        default = param_info.get('default')
        enum_values = param_info.get('enum')
        
        # Show parameter info
        required_marker = "[red]*[/red]" if param_name in required else ""
        self.console.print(f"\n{required_marker} [cyan]{param_name}[/cyan] ({param_type})")
        
        if description:
            self.console.print(f"  [dim]{description}[/dim]")
        
        if enum_values:
            self.console.print(f"  [dim]Valid values: {', '.join(map(str, enum_values))}[/dim]")
        
        if default is not None:
            self.console.print(f"  [dim]Default: {default}[/dim]")
        
        # Get input
        prompt = f"  Value: "
        value = input(prompt).strip()
        
        # Use default if empty and not required
        if not value:
            if param_name in required:
                self.console.print(f"[red]Error: {param_name} is required[/red]")
                return self._get_tool_arguments(tool)  # Retry
            elif default is not None:
                value = default
            else:
                continue
        
        # Type conversion
        try:
            if param_type == 'integer':
                value = int(value)
            elif param_type == 'number':
                value = float(value)
            elif param_type == 'boolean':
                value = value.lower() in ('true', 'yes', '1', 'y')
        except ValueError:
            self.console.print(f"[red]Invalid {param_type} value[/red]")
            return self._get_tool_arguments(tool)  # Retry
        
        arguments[param_name] = value
    
    return arguments
```

#### Display Tool Result

```python
def _display_tool_result(self, result):
    """Display tool execution result with pretty printing."""
    self.console.print("\n[bold green]✓ Tool Result:[/bold green]\n")
    
    # Handle MCP content format
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict):
                content_type = item.get('type', 'text')
                
                if content_type == 'text':
                    text = item.get('text', '')
                    # Try to parse as JSON for pretty printing
                    try:
                        parsed = json.loads(text)
                        self.console.print(json.dumps(parsed, indent=2))
                    except:
                        # Display as-is (could be markdown)
                        self.console.print(text)
                
                elif content_type == 'image':
                    self.console.print(f"[dim]Image: {item.get('data', 'N/A')}[/dim]")
                
                elif content_type == 'resource':
                    self.console.print(f"[dim]Resource: {item.get('uri', 'N/A')}[/dim]")
    else:
        # Fallback for non-MCP format
        self.console.print(str(result))
```

### Integration Points

#### 1. Initialization

```python
class AgentInteractiveSession:
    def __init__(self, options: Dict[str, Any], console: Console):
        # Existing initialization
        self.options = options
        self.console = console
        self.agent = None
        
        # New: MCP agent
        self.mcp_agent = None
        self.mcp_enabled = options.get('enable_mcp', True)
```

#### 2. Startup

```python
def run(self):
    """Run the interactive REPL loop."""
    # Initialize conversation agent
    try:
        with Progress(...) as progress:
            progress.add_task("Initializing agent...", total=None)
            self.agent = create_agent(...)
    except Exception as e:
        # Handle error
        pass
    
    # Initialize MCP agent (optional)
    if self.mcp_enabled:
        try:
            with Progress(...) as progress:
                progress.add_task("Initializing MCP tools...", total=None)
                self.mcp_agent = await initialize_mcp_agent()
            
            tool_count = len(self.mcp_agent.get_available_tools())
            self.console.print(f"[green]✓[/green] MCP tools ready ({tool_count} tools)")
        except Exception as e:
            self.console.print(f"[yellow]⚠ MCP tools unavailable:[/yellow] {e}")
            if self.verbose:
                self.console.print_exception()
    
    # Continue with REPL loop
    ...
```

#### 3. Command Handling

```python
def _handle_command(self, command: str):
    """Handle special commands."""
    cmd = command.lower().split()[0]
    
    # Existing commands
    if cmd in ['/exit', '/quit']:
        ...
    elif cmd == '/help':
        ...
    # ... other existing commands
    
    # New MCP commands
    elif cmd == '/tools':
        self._show_tools()
    
    elif cmd in ['/execute', '/exec', '/e']:
        await self._execute_tool(command)
    
    elif cmd == '/metrics':
        self._show_mcp_metrics()
    
    elif cmd in ['/clear-cache', '/cc']:
        if self.mcp_agent:
            self.mcp_agent.clear_cache()
            self.console.print("[green]✓[/green] MCP tool cache cleared")
        else:
            self.console.print("[yellow]MCP tools not available[/yellow]")
    
    else:
        self.console.print(f"[yellow]Unknown command:[/yellow] {cmd}")
        self.console.print("[dim]Type /help for available commands[/dim]")
```

#### 4. Cleanup

```python
def _cleanup(self):
    """Clean up session resources."""
    # Shutdown MCP agent
    if self.mcp_agent:
        try:
            await shutdown_mcp_agent()
        except Exception as e:
            if self.verbose:
                self.console.print(f"[yellow]Warning: MCP shutdown error:[/yellow] {e}")
```

### Updated Help Message

```python
def _show_help(self):
    """Show help message."""
    help_text = "[bold cyan]Available Commands:[/bold cyan]\n\n"
    
    help_text += "[bold]Conversation:[/bold]\n"
    help_text += "  [cyan]/help[/cyan]        - Show this help\n"
    help_text += "  [cyan]/clear[/cyan]       - Clear conversation history\n"
    help_text += "  [cyan]/history[/cyan]     - Show conversation history\n"
    help_text += "  [cyan]/stats[/cyan]       - Show agent statistics\n"
    help_text += "  [cyan]/verbose[/cyan]     - Toggle verbose mode\n"
    help_text += "  [cyan]/citations[/cyan]   - Toggle citation display\n"
    
    if self.mcp_agent:
        help_text += "\n[bold]MCP Tools:[/bold]\n"
        help_text += "  [cyan]/tools[/cyan]       - List available tools\n"
        help_text += "  [cyan]/execute[/cyan]     - Execute a tool (aliases: /exec, /e)\n"
        help_text += "  [cyan]/metrics[/cyan]     - Show tool metrics\n"
        help_text += "  [cyan]/clear-cache[/cyan] - Clear tool cache (alias: /cc)\n"
    
    help_text += "\n[bold]System:[/bold]\n"
    help_text += "  [cyan]/exit[/cyan]        - Exit (or Ctrl+D)\n"
    
    help_text += "\n[bold cyan]Agent Features:[/bold cyan]\n"
    help_text += "  • Conversational AI with memory\n"
    help_text += "  • RAG-enhanced responses with source citation\n"
    help_text += "  • Response caching for repeated queries\n"
    
    if self.mcp_agent:
        help_text += "  • MCP tool execution for reports and commands\n"
    
    help_text += "\n[bold cyan]Tips:[/bold cyan]\n"
    help_text += "  • Ask follow-up questions - context is preserved\n"
    help_text += "  • Request code examples: 'Show me how to create a glossary'\n"
    
    if self.mcp_agent:
        help_text += "  • Execute tools: '/execute list_reports'\n"
    
    help_text += "  • Use arrow keys to navigate history\n"
    
    self.console.print(Panel(help_text, border_style="cyan", padding=(1, 2)))
```

## Implementation Plan

### Phase 1: Core Integration (Day 1)
1. ✅ Create design document
2. Add MCP agent initialization to `AgentInteractiveSession.__init__()`
3. Add MCP agent startup in `run()` method
4. Add MCP agent cleanup in `_cleanup()` method
5. Test basic initialization

### Phase 2: Commands (Day 1-2)
1. Implement `/tools` command
2. Implement `/execute` command with parameter input
3. Implement `/metrics` command
4. Implement `/clear-cache` command
5. Update `/help` command
6. Test all commands

### Phase 3: Helper Functions (Day 2)
1. Implement `_get_tool_arguments()` for interactive parameter input
2. Implement `_display_tool_result()` for pretty printing
3. Add enum value display for parameters
4. Test with various tool schemas

### Phase 4: Testing & Polish (Day 2-3)
1. Test with mock MCP server
2. Test with real pyegeria MCP server (when available)
3. Handle edge cases and errors
4. Add more helpful error messages
5. Update documentation

### Phase 5: Documentation (Day 3)
1. Update PHASE10_COMPLETE.md
2. Update MCP_INTEGRATION_GUIDE.md
3. Create usage examples
4. Update CLI help text
5. Commit to git

## Success Criteria

- ✅ Agent CLI starts with MCP tools enabled
- ✅ `/tools` command lists available tools
- ✅ `/execute` command runs tools with parameter input
- ✅ Tool results displayed with pretty printing
- ✅ `/metrics` shows MCP tool metrics
- ✅ All existing agent features still work
- ✅ Graceful degradation if MCP unavailable
- ✅ Comprehensive error handling
- ✅ Updated documentation

## Testing Strategy

### Unit Tests
- Test MCP agent initialization
- Test command parsing
- Test parameter input handling
- Test result display formatting

### Integration Tests
- Test with mock MCP server
- Test with real pyegeria MCP server
- Test error scenarios
- Test graceful degradation

### Manual Tests
- Start agent CLI with MCP enabled
- List tools
- Execute various tools
- Check metrics
- Clear cache
- Test with MCP disabled

## Risks & Mitigation

### Risk 1: Async/Await Complexity
**Mitigation**: Use `asyncio.run()` for async operations in sync context

### Risk 2: MCP Server Unavailable
**Mitigation**: Graceful degradation - agent works without MCP

### Risk 3: Breaking Existing Features
**Mitigation**: Comprehensive testing of existing commands

### Risk 4: User Experience
**Mitigation**: Clear error messages, helpful prompts, good defaults

## Future Enhancements

### Phase 10.4
- Tool result visualization (charts, tables)
- Tool execution history
- Tool favorites/bookmarks
- Batch tool execution

### Phase 10.5
- Remote MCP server support
- Tool authentication
- Tool rate limiting
- Advanced tool filtering

---

**Status:** Design Complete  
**Next:** Implementation  
**Last Updated:** 2026-02-20