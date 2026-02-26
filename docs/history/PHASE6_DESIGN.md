# Phase 6: CLI Advisor Interface - Design Document

## Overview

Phase 6 implements a command-line interface for the Egeria Advisor, providing users with an easy way to query the system and get AI-powered assistance.

## Goals

1. **Standalone CLI**: Work independently as `egeria-advisor` command
2. **Direct Queries**: Support one-shot questions
3. **Interactive Mode**: REPL-style interface for conversations
4. **Rich Output**: Beautiful, readable formatting with syntax highlighting
5. **Integration Ready**: Designed to integrate with hey_egeria later

## Command Structure

### Standalone Usage

```bash
# Direct query
egeria-advisor "How do I create a glossary?"

# Interactive mode
egeria-advisor --interactive
egeria-advisor -i

# With options
egeria-advisor "Show me examples" --context=glossary --verbose
egeria-advisor "Create a collection" --format=json --no-citations
```

### Command Options

```
egeria-advisor [OPTIONS] [QUERY]

Options:
  -i, --interactive          Start interactive mode
  -c, --context TEXT         Provide context for the query
  -f, --format [text|json|markdown]  Output format (default: text)
  --no-citations            Hide source citations
  --no-color                Disable colored output
  -v, --verbose             Show detailed information
  --track/--no-track        Enable/disable MLflow tracking (default: on)
  --help                    Show this message and exit
```

## Architecture

```
advisor/cli/
├── __init__.py           # Package initialization
├── main.py               # Main CLI entry point
├── interactive.py        # Interactive REPL mode
├── formatters.py         # Output formatting utilities
├── session.py            # Session and context management
└── commands.py           # Command implementations
```

## Component Details

### 1. Main CLI (`advisor/cli/main.py`)

**Responsibilities:**
- Parse command-line arguments
- Route to appropriate handler (direct query vs interactive)
- Initialize RAG system
- Handle errors gracefully

**Key Functions:**
```python
def cli(query, interactive, context, format, citations, color, verbose, track):
    """Main CLI entry point"""
    
def direct_query(query, options):
    """Handle single query and exit"""
    
def start_interactive(options):
    """Start interactive REPL mode"""
```

### 2. Interactive Mode (`advisor/cli/interactive.py`)

**Responsibilities:**
- REPL loop with prompt
- Command history (up/down arrows)
- Multi-line input support
- Context preservation across queries
- Special commands (/help, /clear, /exit, etc.)

**Features:**
- Prompt: `egeria> `
- History: Saved to `~/.egeria_advisor_history`
- Multi-line: End with `\` for continuation
- Commands:
  - `/help` - Show help
  - `/clear` - Clear context
  - `/history` - Show query history
  - `/exit` or `Ctrl+D` - Exit

**Key Class:**
```python
class InteractiveSession:
    def __init__(self, rag_system, options):
        self.rag = rag_system
        self.context = []
        self.history = []
        
    def run(self):
        """Main REPL loop"""
        
    def handle_query(self, query):
        """Process user query"""
        
    def handle_command(self, command):
        """Process special commands"""
```

### 3. Output Formatters (`advisor/cli/formatters.py`)

**Responsibilities:**
- Format responses beautifully
- Syntax highlighting for code
- Citation formatting
- Progress indicators
- Error messages

**Formatters:**
```python
class TextFormatter:
    """Rich text formatting with colors"""
    
class JSONFormatter:
    """JSON output for programmatic use"""
    
class MarkdownFormatter:
    """Markdown output for documentation"""
    
class CodeFormatter:
    """Syntax highlighting for code blocks"""
    
class CitationFormatter:
    """Format source citations"""
```

**Output Structure:**
```
╭─────────────────────────────────────────────────────────╮
│ Query: How do I create a glossary?                      │
╰─────────────────────────────────────────────────────────╯

Answer:
To create a glossary in Egeria, you use the GlossaryManager class...

Code Example:
┌─────────────────────────────────────────────────────────┐
│ from pyegeria import GlossaryManager                    │
│                                                          │
│ glossary_mgr = GlossaryManager(                         │
│     server_name="view-server",                          │
│     platform_url="https://localhost:9443",              │
│     user_id="garygeeke"                                 │
│ )                                                        │
│                                                          │
│ glossary = glossary_mgr.create_glossary(                │
│     display_name="My Glossary",                         │
│     description="A sample glossary"                     │
│ )                                                        │
└─────────────────────────────────────────────────────────┘

Sources:
  • pyegeria/glossary_manager.py:123 - GlossaryManager.create_glossary()
  • examples/glossary_example.py:45 - Example usage
  • docs/glossary-guide.md - Glossary documentation

───────────────────────────────────────────────────────────
Response time: 1.23s | Confidence: 0.92 | Sources: 3
```

### 4. Session Management (`advisor/cli/session.py`)

**Responsibilities:**
- Track conversation context
- Manage query history
- Store user preferences
- Handle session state

**Key Class:**
```python
class Session:
    def __init__(self):
        self.context = []
        self.history = []
        self.preferences = {}
        
    def add_query(self, query, response):
        """Add to history and context"""
        
    def get_context(self, max_turns=5):
        """Get recent context for RAG"""
        
    def save(self):
        """Save session to disk"""
        
    def load(self):
        """Load previous session"""
```

## Integration with RAG System

The CLI will use the existing RAG system:

```python
from advisor.rag_system import get_rag_system

# Initialize
rag = get_rag_system()

# Query
result = rag.query(
    query="How do I create a glossary?",
    context=session.get_context(),
    track_metrics=True
)

# Format and display
formatter.display_response(result)
```

## Error Handling

### User-Friendly Errors

```python
try:
    result = rag.query(query)
except ConnectionError:
    console.print("[red]✗[/red] Cannot connect to services")
    console.print("  Please check that Milvus and Ollama are running")
except TimeoutError:
    console.print("[yellow]⚠[/yellow] Query timed out")
    console.print("  Try a simpler query or check system load")
except Exception as e:
    console.print(f"[red]✗[/red] Error: {e}")
    if verbose:
        console.print_exception()
```

## Configuration

CLI-specific settings in `config/advisor.yaml`:

```yaml
cli:
  # Output settings
  default_format: text
  show_citations: true
  use_color: true
  
  # Interactive mode
  prompt: "egeria> "
  history_file: "~/.egeria_advisor_history"
  max_history: 1000
  
  # Context management
  max_context_turns: 5
  preserve_context: true
  
  # Display settings
  max_response_length: 2000
  code_theme: monokai
  show_progress: true
  
  # Performance
  timeout: 30
  stream_response: false
```

## Dependencies

Add to `pyproject.toml`:

```toml
dependencies = [
    # ... existing dependencies ...
    "click>=8.1.0",           # CLI framework
    "rich>=13.7.0",           # Rich text formatting
    "prompt-toolkit>=3.0.0",  # Interactive prompts
    "pygments>=2.17.0",       # Syntax highlighting
]
```

## Testing Strategy

### Unit Tests

```python
# tests/cli/test_formatters.py
def test_text_formatter():
    formatter = TextFormatter()
    output = formatter.format_response(sample_response)
    assert "Answer:" in output
    assert "Sources:" in output

# tests/cli/test_interactive.py
def test_interactive_session():
    session = InteractiveSession(mock_rag, options)
    session.handle_query("test query")
    assert len(session.history) == 1
```

### Integration Tests

```bash
# Test direct query
egeria-advisor "What is a glossary?" --format=json

# Test interactive mode (automated)
echo -e "What is a glossary?\n/exit" | egeria-advisor -i
```

## Implementation Plan

### Step 1: Core CLI (Day 1)
- [x] Create directory structure
- [ ] Implement main.py with Click
- [ ] Add direct query support
- [ ] Basic text output

### Step 2: Formatters (Day 1-2)
- [ ] Implement TextFormatter with Rich
- [ ] Add code syntax highlighting
- [ ] Create citation formatter
- [ ] Add progress indicators

### Step 3: Interactive Mode (Day 2)
- [ ] Implement REPL with prompt-toolkit
- [ ] Add command history
- [ ] Implement special commands
- [ ] Add context preservation

### Step 4: Polish & Testing (Day 3)
- [ ] Error handling
- [ ] Configuration options
- [ ] Write tests
- [ ] Create documentation

### Step 5: Integration (Day 3-4)
- [ ] MLflow tracking integration
- [ ] Session management
- [ ] Performance optimization
- [ ] User documentation

## Success Criteria

- [ ] Can run standalone: `egeria-advisor "query"`
- [ ] Interactive mode works smoothly
- [ ] Beautiful, readable output
- [ ] Code examples are syntax highlighted
- [ ] Citations are clear and helpful
- [ ] Error messages are user-friendly
- [ ] Response time < 3 seconds
- [ ] Works with existing RAG system
- [ ] MLflow tracking captures CLI usage
- [ ] Documentation is complete

## Future Enhancements (Post-Phase 6)

- Tab completion for commands
- Query suggestions based on history
- Export conversation to file
- Integration with hey_egeria
- Web-based UI option
- Voice input support

---

**Status**: Design Complete, Ready for Implementation  
**Next**: Create directory structure and implement main.py