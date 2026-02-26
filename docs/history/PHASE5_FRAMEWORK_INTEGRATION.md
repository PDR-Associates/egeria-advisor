# Phase 5: BeeAI & AgentStack Integration Plan

## Overview

Integrate BeeAI (Python) for agent orchestration and AgentStack for observability while keeping our optimized RAG retrieval layer.

## Architecture Strategy

```
┌─────────────────────────────────────────────────────────┐
│                    User Interface                        │
│                  (CLI / API / Web)                       │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│              BeeAI Agent Framework                       │
│  - Agent orchestration & lifecycle                       │
│  - Tool management & function calling                    │
│  - Conversation memory                                   │
│  - Multi-step reasoning                                  │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│            AgentStack Observability                      │
│  - Performance monitoring                                │
│  - Agent behavior tracking                               │
│  - Cost tracking                                         │
│  - Error logging & debugging                             │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│         Custom RAG Tools (Our Implementation)            │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Multi-Collection Search Tool                    │   │
│  │  - Intelligent routing                           │   │
│  │  - Parallel search                               │   │
│  │  - Query caching (17,997x speedup)              │   │
│  │  - Result reranking                              │   │
│  └─────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Code Analysis Tool                              │   │
│  │  - Element type filtering                        │   │
│  │  - Syntax highlighting                           │   │
│  └─────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Documentation Tool                              │   │
│  │  - API reference lookup                          │   │
│  │  - Example retrieval                             │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│              Data Layer (Existing)                       │
│  - Milvus (6 collections, 99,822 entities)              │
│  - Ollama (llama3.1:8b)                                  │
│  - MLflow (experiment tracking)                          │
└──────────────────────────────────────────────────────────┘
```

## Integration Steps

### Step 1: Install Dependencies

```bash
# BeeAI Python SDK
pip install bee-agent-framework

# AgentStack
pip install agentstack

# Additional dependencies
pip install pydantic>=2.0  # For data validation
```

### Step 2: Wrap Our RAG Retrieval as BeeAI Tools

Create `advisor/tools/rag_tools.py`:

```python
"""BeeAI tools wrapping our optimized RAG retrieval."""

from typing import Optional, List
from pydantic import BaseModel, Field
from bee_agent import Tool, ToolInput, ToolOutput

from advisor.rag_retrieval import RAGRetriever
from advisor.multi_collection_store import get_multi_collection_store


class SearchInput(BaseModel):
    """Input schema for search tool."""
    query: str = Field(description="The search query")
    top_k: int = Field(default=5, description="Number of results to return")
    collections: Optional[List[str]] = Field(
        default=None,
        description="Specific collections to search (optional)"
    )


class SearchOutput(BaseModel):
    """Output schema for search tool."""
    results: List[dict]
    num_results: int
    collections_searched: List[str]
    cache_hit: bool


class MultiCollectionSearchTool(Tool):
    """
    BeeAI tool for multi-collection semantic search.
    
    Uses our optimized RAG retrieval with:
    - Intelligent routing
    - Parallel search
    - Query caching (17,997x speedup)
    - Result reranking
    """
    
    name = "multi_collection_search"
    description = """
    Search across multiple Egeria code collections using semantic similarity.
    Automatically routes queries to relevant collections and returns ranked results.
    Supports: pyegeria, pyegeria_cli, pyegeria_drE, egeria_java, egeria_docs, egeria_workspaces.
    """
    
    def __init__(self):
        super().__init__()
        self.retriever = RAGRetriever(
            use_multi_collection=True,
            enable_cache=True
        )
    
    async def execute(self, input: SearchInput) -> SearchOutput:
        """Execute the search."""
        results = self.retriever.retrieve(
            query=input.query,
            top_k=input.top_k
        )
        
        # Convert to dict format
        result_dicts = [
            {
                "content": r.content,
                "score": r.score,
                "metadata": r.metadata,
                "collection": r.collection_name
            }
            for r in results
        ]
        
        # Get collections searched
        collections = list(set(r.collection_name for r in results))
        
        return SearchOutput(
            results=result_dicts,
            num_results=len(results),
            collections_searched=collections,
            cache_hit=False  # TODO: Get from cache stats
        )


class CodeAnalysisTool(Tool):
    """Tool for analyzing specific code elements."""
    
    name = "code_analysis"
    description = """
    Analyze specific code elements (classes, functions, methods) from Egeria.
    Filters by element type and provides detailed code context.
    """
    
    def __init__(self):
        super().__init__()
        self.retriever = RAGRetriever(use_multi_collection=True)
    
    async def execute(self, input: dict) -> dict:
        """Execute code analysis."""
        query = input.get("query")
        element_types = input.get("element_types", [])
        
        results = self.retriever.retrieve(
            query=query,
            top_k=10,
            element_types=element_types if element_types else None
        )
        
        return {
            "elements": [
                {
                    "name": r.metadata.get("name"),
                    "type": r.metadata.get("element_type"),
                    "code": r.content,
                    "file": r.metadata.get("file_path"),
                    "score": r.score
                }
                for r in results
            ]
        }
```

### Step 3: Create BeeAI Agent

Create `advisor/agents/egeria_agent.py`:

```python
"""BeeAI agent for Egeria assistance."""

from bee_agent import Agent, AgentConfig
from bee_agent.llm import OllamaLLM
from bee_agent.memory import ConversationMemory

from advisor.tools.rag_tools import (
    MultiCollectionSearchTool,
    CodeAnalysisTool
)


class EgeriaAgent:
    """
    BeeAI-powered agent for Egeria assistance.
    
    Combines:
    - BeeAI agent orchestration
    - Our optimized RAG tools
    - AgentStack observability
    """
    
    def __init__(
        self,
        model_name: str = "llama3.1:8b",
        ollama_url: str = "http://localhost:11434"
    ):
        # Initialize LLM
        self.llm = OllamaLLM(
            model=model_name,
            base_url=ollama_url
        )
        
        # Initialize tools
        self.tools = [
            MultiCollectionSearchTool(),
            CodeAnalysisTool()
        ]
        
        # Initialize memory
        self.memory = ConversationMemory(max_tokens=4000)
        
        # Create agent
        self.agent = Agent(
            llm=self.llm,
            tools=self.tools,
            memory=self.memory,
            config=AgentConfig(
                max_iterations=5,
                verbose=True
            )
        )
    
    async def chat(self, message: str) -> str:
        """Chat with the agent."""
        response = await self.agent.run(message)
        return response.text
    
    async def reset(self):
        """Reset conversation memory."""
        self.memory.clear()
```

### Step 4: Add AgentStack Observability

Create `advisor/observability/agentstack_config.py`:

```python
"""AgentStack observability configuration."""

import agentstack
from agentstack import track_agent, track_llm, track_tool


def init_observability(project_name: str = "egeria-advisor"):
    """Initialize AgentStack observability."""
    agentstack.init(
        project_name=project_name,
        api_key=None,  # Use environment variable
        tags=["production", "rag", "multi-collection"]
    )


@track_agent
async def tracked_agent_run(agent, message: str):
    """Wrapper for tracking agent runs."""
    return await agent.chat(message)


@track_tool
async def tracked_tool_execution(tool, input_data):
    """Wrapper for tracking tool executions."""
    return await tool.execute(input_data)


@track_llm
async def tracked_llm_call(llm, prompt: str):
    """Wrapper for tracking LLM calls."""
    return await llm.generate(prompt)
```

### Step 5: Update CLI to Use BeeAI Agent

Create `advisor/cli/agent_mode.py`:

```python
"""CLI agent mode using BeeAI."""

import asyncio
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from advisor.agents.egeria_agent import EgeriaAgent
from advisor.observability.agentstack_config import (
    init_observability,
    tracked_agent_run
)

console = Console()


async def agent_chat_loop():
    """Interactive chat loop with BeeAI agent."""
    
    # Initialize observability
    init_observability()
    
    # Create agent
    console.print("[cyan]Initializing Egeria Agent...[/cyan]")
    agent = EgeriaAgent()
    
    console.print(Panel.fit(
        "[bold green]Egeria Agent Ready![/bold green]\n"
        "Powered by BeeAI + Custom RAG\n"
        "Type 'exit' to quit, 'reset' to clear history",
        border_style="green"
    ))
    
    while True:
        try:
            # Get user input
            user_input = console.input("\n[bold cyan]You:[/bold cyan] ")
            
            if user_input.lower() == "exit":
                break
            
            if user_input.lower() == "reset":
                await agent.reset()
                console.print("[yellow]Conversation reset[/yellow]")
                continue
            
            # Get agent response (with tracking)
            console.print("\n[bold green]Agent:[/bold green] ", end="")
            response = await tracked_agent_run(agent, user_input)
            
            # Display response
            console.print(Markdown(response))
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
    
    console.print("\n[cyan]Goodbye![/cyan]")


def run_agent_mode():
    """Run agent mode."""
    asyncio.run(agent_chat_loop())
```

### Step 6: Update Main CLI

Update `advisor/cli/__init__.py` to add agent mode:

```python
@click.command()
@click.option('--mode', type=click.Choice(['search', 'agent']), default='search')
def main(mode: str):
    """Egeria Advisor CLI."""
    if mode == 'agent':
        from advisor.cli.agent_mode import run_agent_mode
        run_agent_mode()
    else:
        # Existing search mode
        run_search_mode()
```

## Testing Plan

### Test 1: Basic Agent Functionality
```bash
cd ../egeria-v6/egeria-advisor
python -m advisor.cli --mode agent
```

Test queries:
- "How do I connect to an OMAG server?"
- "Show me examples of creating assets"
- "What are the main classes in pyegeria?"

### Test 2: Tool Integration
Verify that:
- Multi-collection search tool is called correctly
- Results are cached (check for speedup)
- Routing works as expected

### Test 3: Observability
Check AgentStack dashboard for:
- Agent execution traces
- Tool call statistics
- LLM token usage
- Performance metrics

### Test 4: Multi-Step Reasoning
Test complex queries requiring multiple tool calls:
- "Compare how pyegeria and egeria_java handle server connections"
- "Find all methods related to glossary terms and explain their differences"

## Benefits of This Integration

### From BeeAI:
✅ Agent orchestration and lifecycle management
✅ Tool management and function calling
✅ Conversation memory and context
✅ Multi-step reasoning capabilities
✅ Streaming responses

### From AgentStack:
✅ Performance monitoring and profiling
✅ Agent behavior tracking
✅ Cost tracking (LLM tokens)
✅ Error logging and debugging
✅ Production-ready observability

### We Keep:
✅ Our optimized RAG retrieval (17,997x speedup)
✅ Multi-collection routing
✅ Parallel search
✅ Query caching
✅ Result reranking
✅ Domain-specific optimizations

## Migration Path

1. **Phase 5a** (Current): Install dependencies and create tool wrappers
2. **Phase 5b**: Implement BeeAI agent with basic tools
3. **Phase 5c**: Add AgentStack observability
4. **Phase 5d**: Update CLI to support agent mode
5. **Phase 5e**: Test and validate performance
6. **Phase 5f**: Deploy to production

## Next Immediate Steps

1. Install BeeAI and AgentStack: `pip install bee-agent-framework agentstack`
2. Create `advisor/tools/rag_tools.py` with tool wrappers
3. Create `advisor/agents/egeria_agent.py` with BeeAI agent
4. Test basic agent functionality
5. Add AgentStack observability
6. Update CLI with agent mode

## Success Criteria

- [ ] BeeAI agent successfully orchestrates tool calls
- [ ] Our RAG tools integrate seamlessly with BeeAI
- [ ] AgentStack provides useful observability metrics
- [ ] Performance remains high (cache still provides 17,997x speedup)
- [ ] Multi-step reasoning works correctly
- [ ] CLI supports both search and agent modes
- [ ] All existing functionality preserved