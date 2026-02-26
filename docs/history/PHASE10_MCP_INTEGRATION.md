# Phase 10: MCP Integration Design

**Version:** 1.0  
**Date:** 2026-02-20  
**Status:** Design Phase

## Overview

This phase integrates Model Context Protocol (MCP) capabilities into the Egeria Advisor, enabling it to invoke tools from MCP servers like the pyegeria MCP server for reports and Dr. Egeria markdown command construction/invocation.

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────────┐
│                    Egeria Advisor                            │
│                                                              │
│  ┌────────────────┐      ┌──────────────────┐              │
│  │  RAG System    │      │   MCP Agent      │              │
│  │                │      │                  │              │
│  │  - Query       │◄────►│  - Tool Discovery│              │
│  │  - Routing     │      │  - Tool Invocation│             │
│  │  - Response    │      │  - Result Handling│             │
│  └────────────────┘      └──────────────────┘              │
│         │                         │                         │
│         │                         │                         │
│         ▼                         ▼                         │
│  ┌────────────────────────────────────────┐                │
│  │         LLM Client                      │                │
│  │  - Prompt Construction                  │                │
│  │  - Tool Call Detection                  │                │
│  │  - Response Generation                  │                │
│  └────────────────────────────────────────┘                │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ MCP Protocol
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                  MCP Servers                                 │
│                                                              │
│  ┌──────────────────┐      ┌──────────────────┐            │
│  │  pyegeria MCP    │      │  Future MCP      │            │
│  │                  │      │  Servers         │            │
│  │  - Reports       │      │                  │            │
│  │  - Dr. Egeria    │      │  - File System   │            │
│  │  - Commands      │      │  - Database      │            │
│  └──────────────────┘      └──────────────────┘            │
└─────────────────────────────────────────────────────────────┘
```

## MCP Configuration

### Configuration File Format

The advisor will support MCP server configuration in `config/mcp_servers.json`:

```json
{
  "mcpServers": {
    "pyegeria": {
      "command": "/Users/dwolfson/localGit/egeria-python/.venv/bin/python",
      "args": [
        "/Users/dwolfson/localGit/egeria-python/pyegeria/core/mcp_server.py"
      ],
      "env": {
        "EGERIA_USER": "erinoverview",
        "EGERIA_VIEW_SERVER": "qs-view-server",
        "EGERIA_PASSWORD": "secret",
        "EGERIA_VIEW_SERVER_URL": "https://localhost:9443"
      },
      "enabled": true,
      "description": "PyEgeria MCP server for reports and Dr. Egeria commands"
    }
  },
  "settings": {
    "auto_discover_tools": true,
    "tool_timeout": 30,
    "max_concurrent_tools": 5,
    "enable_tool_caching": true
  }
}
```

### Environment-Based Configuration

Support environment variables for sensitive data:

```bash
export EGERIA_USER="erinoverview"
export EGERIA_PASSWORD="secret"
export EGERIA_VIEW_SERVER_URL="https://localhost:9443"
```

## MCP Client Implementation

### Core Classes

#### 1. MCPClient

```python
class MCPClient:
    """Client for communicating with MCP servers."""
    
    def __init__(self, server_config: Dict[str, Any]):
        self.server_config = server_config
        self.process = None
        self.tools = {}
        
    async def connect(self) -> bool:
        """Start MCP server process and establish connection."""
        
    async def disconnect(self) -> None:
        """Stop MCP server process."""
        
    async def discover_tools(self) -> List[MCPTool]:
        """Discover available tools from the MCP server."""
        
    async def invoke_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Invoke a tool with given arguments."""
        
    async def list_resources(self) -> List[MCPResource]:
        """List available resources from the MCP server."""
```

#### 2. MCPAgent

```python
class MCPAgent:
    """High-level agent for managing multiple MCP servers."""
    
    def __init__(self, config_path: str = "config/mcp_servers.json"):
        self.config = self._load_config(config_path)
        self.clients: Dict[str, MCPClient] = {}
        self.tools: Dict[str, MCPTool] = {}
        
    async def initialize(self) -> None:
        """Initialize all configured MCP servers."""
        
    async def shutdown(self) -> None:
        """Shutdown all MCP servers."""
        
    def get_available_tools(self) -> List[MCPTool]:
        """Get all available tools from all servers."""
        
    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Execute a tool by name."""
        
    def get_tool_descriptions(self) -> List[Dict[str, Any]]:
        """Get tool descriptions for LLM function calling."""
```

#### 3. MCPTool

```python
@dataclass
class MCPTool:
    """Represents an MCP tool."""
    
    name: str
    description: str
    server: str
    input_schema: Dict[str, Any]
    output_schema: Optional[Dict[str, Any]] = None
    
    def to_function_definition(self) -> Dict[str, Any]:
        """Convert to OpenAI function calling format."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_schema
        }
```

## Integration with RAG System

### Tool-Augmented RAG

```python
class ToolAugmentedRAG:
    """RAG system with MCP tool invocation capabilities."""
    
    def __init__(self, rag_system: RAGSystem, mcp_agent: MCPAgent):
        self.rag_system = rag_system
        self.mcp_agent = mcp_agent
        
    async def query_with_tools(
        self,
        query: str,
        enable_tools: bool = True,
        max_tool_iterations: int = 3
    ) -> Dict[str, Any]:
        """
        Process query with optional tool invocation.
        
        Flow:
        1. Analyze query to determine if tools are needed
        2. Perform RAG search for context
        3. Generate response with tool descriptions
        4. If LLM requests tool use, invoke tool
        5. Add tool results to context
        6. Generate final response
        """
```

### Query Analysis for Tool Selection

```python
def should_use_tools(query: str, query_type: str) -> bool:
    """Determine if query would benefit from tool use."""
    
    tool_indicators = {
        "report": ["generate report", "create report", "show report"],
        "command": ["run command", "execute", "invoke"],
        "data": ["get data", "fetch", "retrieve", "list"],
        "action": ["create", "update", "delete", "modify"]
    }
    
    query_lower = query.lower()
    for category, indicators in tool_indicators.items():
        if any(indicator in query_lower for indicator in indicators):
            return True
    return False
```

## LLM Integration

### Function Calling Format

The MCP tools will be provided to the LLM in OpenAI function calling format:

```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "generate_egeria_report",
            "description": "Generate an Egeria report using pyegeria",
            "parameters": {
                "type": "object",
                "properties": {
                    "report_type": {
                        "type": "string",
                        "enum": ["asset", "glossary", "lineage"],
                        "description": "Type of report to generate"
                    },
                    "guid": {
                        "type": "string",
                        "description": "GUID of the entity to report on"
                    }
                },
                "required": ["report_type", "guid"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_dr_egeria_command",
            "description": "Execute a Dr. Egeria markdown command",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The Dr. Egeria markdown command to execute"
                    }
                },
                "required": ["command"]
            }
        }
    }
]
```

### Tool Call Detection and Execution

```python
async def process_llm_response(response: Dict[str, Any]) -> str:
    """Process LLM response and handle tool calls."""
    
    if "tool_calls" in response:
        results = []
        for tool_call in response["tool_calls"]:
            tool_name = tool_call["function"]["name"]
            arguments = json.loads(tool_call["function"]["arguments"])
            
            # Execute tool
            result = await mcp_agent.execute_tool(tool_name, arguments)
            results.append({
                "tool_call_id": tool_call["id"],
                "role": "tool",
                "name": tool_name,
                "content": json.dumps(result)
            })
        
        # Send tool results back to LLM for final response
        final_response = await llm_client.chat_completion(
            messages=[...original_messages, response, *results]
        )
        return final_response["choices"][0]["message"]["content"]
    
    return response["choices"][0]["message"]["content"]
```

## CLI Integration

### MCP-Enabled CLI Commands

```bash
# Query with MCP tools enabled (default)
egeria-advisor query "Generate a report for asset xyz-123"

# Query with MCP tools disabled
egeria-advisor query "What is OMAS?" --no-tools

# List available MCP tools
egeria-advisor mcp list-tools

# Test MCP server connection
egeria-advisor mcp test-connection pyegeria

# Execute tool directly
egeria-advisor mcp execute generate_egeria_report \
  --report-type asset \
  --guid xyz-123
```

### Interactive Mode with Tools

```python
# examples/cli_with_mcp.py
async def interactive_mode():
    """Interactive CLI with MCP tool support."""
    
    mcp_agent = MCPAgent()
    await mcp_agent.initialize()
    
    print("Available tools:")
    for tool in mcp_agent.get_available_tools():
        print(f"  - {tool.name}: {tool.description}")
    
    while True:
        query = input("\nQuery: ")
        if query.lower() in ["exit", "quit"]:
            break
            
        # Process with tools
        result = await tool_augmented_rag.query_with_tools(query)
        print(f"\nResponse: {result['response']}")
        
        if result.get('tools_used'):
            print(f"\nTools used: {', '.join(result['tools_used'])}")
    
    await mcp_agent.shutdown()
```

## Configuration Management

### Config Class

```python
@dataclass
class MCPConfig:
    """MCP configuration."""
    
    servers: Dict[str, MCPServerConfig]
    auto_discover_tools: bool = True
    tool_timeout: int = 30
    max_concurrent_tools: int = 5
    enable_tool_caching: bool = True
    
    @classmethod
    def from_file(cls, path: str) -> 'MCPConfig':
        """Load configuration from JSON file."""
        
    def to_file(self, path: str) -> None:
        """Save configuration to JSON file."""
        
    def get_enabled_servers(self) -> List[str]:
        """Get list of enabled server names."""

@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""
    
    command: str
    args: List[str]
    env: Dict[str, str]
    enabled: bool = True
    description: str = ""
    
    def get_env_with_defaults(self) -> Dict[str, str]:
        """Get environment variables with system env as fallback."""
        env = os.environ.copy()
        env.update(self.env)
        return env
```

## Error Handling

### MCP-Specific Exceptions

```python
class MCPError(Exception):
    """Base exception for MCP errors."""
    pass

class MCPConnectionError(MCPError):
    """Failed to connect to MCP server."""
    pass

class MCPToolNotFoundError(MCPError):
    """Requested tool not found."""
    pass

class MCPToolExecutionError(MCPError):
    """Tool execution failed."""
    pass

class MCPTimeoutError(MCPError):
    """Tool execution timed out."""
    pass
```

### Graceful Degradation

```python
async def query_with_fallback(query: str) -> Dict[str, Any]:
    """Query with graceful fallback if MCP fails."""
    
    try:
        # Try with tools
        return await tool_augmented_rag.query_with_tools(query)
    except MCPError as e:
        logger.warning(f"MCP error: {e}. Falling back to RAG-only.")
        # Fall back to regular RAG
        return await rag_system.query(query)
```

## Testing Strategy

### Unit Tests

```python
# tests/test_mcp_client.py
@pytest.mark.asyncio
async def test_mcp_client_connection():
    """Test MCP client can connect to server."""
    
@pytest.mark.asyncio
async def test_tool_discovery():
    """Test tool discovery from MCP server."""
    
@pytest.mark.asyncio
async def test_tool_invocation():
    """Test tool invocation with arguments."""
```

### Integration Tests

```python
# tests/test_mcp_integration.py
@pytest.mark.asyncio
async def test_rag_with_tools():
    """Test RAG system with MCP tools."""
    
@pytest.mark.asyncio
async def test_tool_augmented_query():
    """Test end-to-end query with tool invocation."""
```

### Mock MCP Server

```python
# tests/mock_mcp_server.py
class MockMCPServer:
    """Mock MCP server for testing."""
    
    def __init__(self):
        self.tools = {
            "test_tool": {
                "name": "test_tool",
                "description": "A test tool",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "input": {"type": "string"}
                    }
                }
            }
        }
    
    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP protocol request."""
```

## Security Considerations

### 1. Credential Management

- Store sensitive credentials in environment variables
- Support credential rotation
- Never log credentials
- Use secure credential storage (e.g., keyring)

### 2. Tool Execution Safety

- Validate tool arguments before execution
- Implement timeouts for all tool calls
- Sandbox tool execution if possible
- Rate limit tool invocations

### 3. Input Validation

```python
def validate_tool_arguments(
    tool: MCPTool,
    arguments: Dict[str, Any]
) -> None:
    """Validate tool arguments against schema."""
    
    # Use jsonschema for validation
    from jsonschema import validate, ValidationError
    
    try:
        validate(instance=arguments, schema=tool.input_schema)
    except ValidationError as e:
        raise MCPToolExecutionError(f"Invalid arguments: {e}")
```

## Performance Optimization

### 1. Tool Caching

```python
class ToolCache:
    """Cache for tool results."""
    
    def __init__(self, ttl: int = 300):
        self.cache: Dict[str, Tuple[Any, float]] = {}
        self.ttl = ttl
    
    def get(self, key: str) -> Optional[Any]:
        """Get cached result if not expired."""
        
    def set(self, key: str, value: Any) -> None:
        """Cache a result."""
        
    def _make_key(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Create cache key from tool name and arguments."""
        return f"{tool_name}:{json.dumps(arguments, sort_keys=True)}"
```

### 2. Async Tool Execution

```python
async def execute_tools_parallel(
    tool_calls: List[Dict[str, Any]]
) -> List[Any]:
    """Execute multiple tools in parallel."""
    
    tasks = [
        mcp_agent.execute_tool(call["name"], call["arguments"])
        for call in tool_calls
    ]
    
    return await asyncio.gather(*tasks, return_exceptions=True)
```

## Monitoring and Logging

### Metrics to Track

```python
@dataclass
class MCPMetrics:
    """Metrics for MCP operations."""
    
    tool_invocations: int = 0
    tool_successes: int = 0
    tool_failures: int = 0
    total_execution_time: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    
    def success_rate(self) -> float:
        """Calculate tool success rate."""
        if self.tool_invocations == 0:
            return 0.0
        return self.tool_successes / self.tool_invocations
    
    def average_execution_time(self) -> float:
        """Calculate average tool execution time."""
        if self.tool_invocations == 0:
            return 0.0
        return self.total_execution_time / self.tool_invocations
```

### Logging

```python
import logging

logger = logging.getLogger("egeria_advisor.mcp")

# Log tool invocations
logger.info(f"Invoking tool: {tool_name} with args: {arguments}")

# Log tool results
logger.info(f"Tool {tool_name} completed in {duration:.2f}s")

# Log errors
logger.error(f"Tool {tool_name} failed: {error}", exc_info=True)
```

## Implementation Phases

### Phase 10.1: Core MCP Client (Week 1)
- [ ] Implement MCPClient class
- [ ] Implement MCPAgent class
- [ ] Add configuration management
- [ ] Write unit tests

### Phase 10.2: RAG Integration (Week 2)
- [ ] Implement ToolAugmentedRAG
- [ ] Add query analysis for tool selection
- [ ] Integrate with LLM client
- [ ] Write integration tests

### Phase 10.3: CLI Integration (Week 3)
- [ ] Add MCP commands to CLI
- [ ] Implement interactive mode with tools
- [ ] Add tool execution examples
- [ ] Write CLI tests

### Phase 10.4: Testing & Documentation (Week 4)
- [ ] Create mock MCP server for testing
- [ ] Write comprehensive tests
- [ ] Create user documentation
- [ ] Create developer documentation

## Success Metrics

- **Tool Discovery**: Successfully discover all tools from pyegeria MCP server
- **Tool Execution**: 95%+ success rate for tool invocations
- **Performance**: Tool execution < 5s average
- **Reliability**: Graceful fallback to RAG-only mode on MCP failures
- **User Experience**: Seamless integration, users don't need to know about MCP

## Future Enhancements

### Phase 10.5: Advanced Features
- Multi-step tool orchestration
- Tool result validation and retry logic
- Streaming tool results
- Tool composition (chaining tools)

### Phase 10.6: Additional MCP Servers
- File system MCP server for document access
- Database MCP server for metadata queries
- Custom Egeria MCP servers for governance operations

### Phase 10.7: AI-Powered Tool Selection
- ML model to predict which tools to use
- Learn from user feedback on tool usage
- Optimize tool selection based on query patterns

## References

- MCP Protocol Specification: https://modelcontextprotocol.io/
- PyEgeria MCP Server: (to be implemented)
- OpenAI Function Calling: https://platform.openai.com/docs/guides/function-calling

---

**Status:** Design Complete  
**Next Steps:** Begin Phase 10.1 implementation  
**Dependencies:** PyEgeria MCP server (in development)