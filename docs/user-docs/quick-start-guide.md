# Quick Start Guide - Egeria Advisor

## Getting Started with Phase 2

This guide will help you quickly set up and begin implementing Phase 2 of the Egeria Advisor project.

---

## Prerequisites Checklist

- [x] Docker containers running:
  - [x] Milvus @ localhost:19530
  - [x] MLflow @ localhost:5000
  - [x] Egeria quickstart @ localhost:9443
- [ ] Ollama @ localhost:11434 (will set up in Step 1)
- [ ] Python 3.12+ installed
- [ ] Access to egeria-python repository at `/home/dwolfson/localGit/egeria-v6/egeria-python`

---

## Step 1: Set Up Ollama (Local LLM)

### Option A: Docker (Recommended)

```bash
# Pull and run Ollama in Docker
docker run -d \
  --name ollama \
  -p 11434:11434 \
  -v ollama:/root/.ollama \
  --restart unless-stopped \
  ollama/ollama

# Pull recommended models
docker exec ollama ollama pull llama3.1:8b      # Fast, good for queries
docker exec ollama ollama pull codellama:13b    # Better for code generation
docker exec ollama ollama pull mistral:7b       # Alternative general model

# Test Ollama
curl http://localhost:11434/api/tags
```

### Option B: Native Installation

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Start Ollama service
ollama serve &

# Pull models
ollama pull llama3.1:8b
ollama pull codellama:13b
ollama pull mistral:7b

# Test
curl http://localhost:11434/api/tags
```

### Verify Ollama Setup

```bash
# Test generation
curl http://localhost:11434/api/generate -d '{
  "model": "llama3.1:8b",
  "prompt": "What is Egeria?",
  "stream": false
}'
```

---

## Step 2: Create Project Repository

```bash
# Navigate to project directory
cd /home/dwolfson/localGit/egeria-v6

# Create new repository
mkdir egeria-advisor
cd egeria-advisor

# Initialize git
git init
git branch -M main

# Create initial structure
mkdir -p advisor/{data_prep,vector_store,rag,agents,observability,cli}
mkdir -p config data tests docs examples scripts
touch advisor/__init__.py
touch advisor/data_prep/__init__.py
touch advisor/vector_store/__init__.py
touch advisor/rag/__init__.py
touch advisor/agents/__init__.py
touch advisor/observability/__init__.py
touch advisor/cli/__init__.py
```

---

## Step 3: Create pyproject.toml

```bash
cat > pyproject.toml << 'EOF'
[project]
name = "egeria-advisor"
version = "0.1.0"
description = "AI-powered advisor for egeria-python using local LLMs"
requires-python = ">=3.12"
authors = [
    {name = "Your Name", email = "your.email@example.com"}
]

dependencies = [
    "pymilvus>=2.4.0",
    "docling>=1.0.0",
    "data-prep-kit>=0.2.0",
    "bee-agent-framework>=0.1.0",
    "agentstack>=0.1.0",
    "langchain>=0.1.0",
    "langchain-community>=0.1.0",
    "ollama>=0.1.0",
    "click>=8.0.0",
    "rich>=13.0.0",
    "pydantic>=2.0.0",
    "python-dotenv>=1.0.0",
    "mlflow>=2.10.0",
    "arize-phoenix>=3.0.0",
    "opentelemetry-api>=1.20.0",
    "opentelemetry-sdk>=1.20.0",
    "sentence-transformers>=2.2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "black>=24.0.0",
    "ruff>=0.1.0",
    "mypy>=1.8.0",
]

[project.scripts]
egeria-advisor = "advisor.cli.advisor_cli:main"

[build-system]
requires = ["setuptools>=68.0.0", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["advisor", "advisor.*"]

[tool.black]
line-length = 100
target-version = ['py312']

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.mypy]
python_version = "3.12"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
EOF
```

---

## Step 4: Create Configuration Files

### Create .env file

```bash
cat > .env << 'EOF'
# Milvus Configuration
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_USER=
MILVUS_PASSWORD=

# Egeria Configuration
EGERIA_PLATFORM_URL=https://localhost:9443
EGERIA_VIEW_SERVER=view-server
EGERIA_USER=garygeeke
EGERIA_PASSWORD=secret

# Ollama Configuration (Local LLM)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b
OLLAMA_CODE_MODEL=codellama:13b
OLLAMA_TEMPERATURE=0.7

# Embedding Model (Local)
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_DEVICE=cpu

# MLflow Configuration
MLFLOW_TRACKING_URI=http://localhost:5000
MLFLOW_EXPERIMENT_NAME=egeria-advisor
MLFLOW_ENABLE_TRACKING=true

# Phoenix Arize Configuration (optional)
PHOENIX_ENABLE=false
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006

# Advisor Configuration
ADVISOR_DATA_PATH=/home/dwolfson/localGit/egeria-v6/egeria-python
ADVISOR_CACHE_DIR=./data/cache
ADVISOR_LOG_LEVEL=INFO
EOF
```

### Create config/advisor.yaml

```bash
cat > config/advisor.yaml << 'EOF'
data_sources:
  egeria_python_path: /home/dwolfson/localGit/egeria-v6/egeria-python
  include_patterns:
    - "*.py"
    - "*.md"
  exclude_patterns:
    - "**/__pycache__/**"
    - "**/deprecated/**"
    - "**/.git/**"

vector_store:
  host: localhost
  port: 19530
  collections:
    - code_snippets
    - examples
    - documentation
    - api_signatures

llm:
  provider: ollama
  base_url: http://localhost:11434
  models:
    query: llama3.1:8b          # Fast model for queries
    code: codellama:13b          # Code-specialized model
    conversation: llama3.1:8b    # General conversation
    maintenance: codellama:13b   # Code analysis
  temperature: 0.7
  max_tokens: 2000
  timeout: 60

embeddings:
  model: sentence-transformers/all-MiniLM-L6-v2
  device: cpu
  batch_size: 32
  normalize: true

rag:
  chunk_size: 512
  chunk_overlap: 50
  top_k: 5
  similarity_threshold: 0.7
  rerank: false

agents:
  query_agent:
    enabled: true
    model: llama3.1:8b
    temperature: 0.3
  code_agent:
    enabled: true
    model: codellama:13b
    temperature: 0.5
  conversation_agent:
    enabled: true
    model: llama3.1:8b
    temperature: 0.7
  maintenance_agent:
    enabled: true
    model: codellama:13b
    temperature: 0.4

cli:
  default_agent: auto
  interactive_mode: true
  output_format: rich
  show_citations: true

observability:
  mlflow:
    enabled: true
    tracking_uri: http://localhost:5000
    experiment_name: egeria-advisor
    log_system_metrics: true
    log_query_metrics: true
  phoenix:
    enabled: false
    collector_endpoint: http://localhost:6006
    trace_all_queries: false
EOF
```

---

## Step 5: Set Up Python Environment

```bash
# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install uv for faster dependency management
pip install uv

# Install project in development mode
uv pip install -e ".[dev]"
```

---

## Step 6: Create Initial Files for Phase 2

### Create advisor/config.py

```bash
cat > advisor/config.py << 'EOF'
"""Configuration management for Egeria Advisor."""
import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
import yaml


class DataSourceConfig(BaseModel):
    """Data source configuration."""
    egeria_python_path: Path
    include_patterns: list[str] = ["*.py", "*.md"]
    exclude_patterns: list[str] = ["**/__pycache__/**", "**/deprecated/**"]


class VectorStoreConfig(BaseModel):
    """Vector store configuration."""
    host: str = "localhost"
    port: int = 19530
    collections: list[str] = ["code_snippets", "examples", "documentation"]


class LLMConfig(BaseModel):
    """LLM configuration for Ollama."""
    provider: str = "ollama"
    base_url: str = "http://localhost:11434"
    models: dict[str, str] = {
        "query": "llama3.1:8b",
        "code": "codellama:13b",
        "conversation": "llama3.1:8b",
        "maintenance": "codellama:13b"
    }
    temperature: float = 0.7
    max_tokens: int = 2000


class EmbeddingConfig(BaseModel):
    """Embedding model configuration."""
    model: str = "sentence-transformers/all-MiniLM-L6-v2"
    device: str = "cpu"
    batch_size: int = 32
    normalize: bool = True


class RAGConfig(BaseModel):
    """RAG system configuration."""
    chunk_size: int = 512
    chunk_overlap: int = 50
    top_k: int = 5
    similarity_threshold: float = 0.7


class AdvisorSettings(BaseSettings):
    """Main settings loaded from environment and config file."""
    
    # Milvus
    milvus_host: str = Field(default="localhost", alias="MILVUS_HOST")
    milvus_port: int = Field(default=19530, alias="MILVUS_PORT")
    
    # Egeria
    egeria_platform_url: str = Field(default="https://localhost:9443", alias="EGERIA_PLATFORM_URL")
    egeria_view_server: str = Field(default="view-server", alias="EGERIA_VIEW_SERVER")
    
    # Ollama
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="llama3.1:8b", alias="OLLAMA_MODEL")
    
    # Embeddings
    embedding_model: str = Field(default="sentence-transformers/all-MiniLM-L6-v2", alias="EMBEDDING_MODEL")
    
    # MLflow
    mlflow_tracking_uri: str = Field(default="http://localhost:5000", alias="MLFLOW_TRACKING_URI")
    
    # Advisor
    advisor_data_path: Path = Field(alias="ADVISOR_DATA_PATH")
    advisor_cache_dir: Path = Field(default=Path("./data/cache"), alias="ADVISOR_CACHE_DIR")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


def load_config(config_path: Optional[Path] = None) -> dict:
    """Load configuration from YAML file."""
    if config_path is None:
        config_path = Path("config/advisor.yaml")
    
    with open(config_path) as f:
        return yaml.safe_load(f)


# Global settings instance
settings = AdvisorSettings()
EOF
```

### Create advisor/data_prep/code_parser.py

```bash
cat > advisor/data_prep/code_parser.py << 'EOF'
"""Python code parser using AST."""
import ast
from pathlib import Path
from typing import List, Dict, Any
from dataclasses import dataclass


@dataclass
class CodeElement:
    """Represents a parsed code element."""
    type: str  # function, class, method
    name: str
    file_path: str
    line_number: int
    docstring: str | None
    signature: str
    body: str


class CodeParser:
    """Parse Python code files using AST."""
    
    def parse_file(self, file_path: Path) -> List[CodeElement]:
        """Parse a Python file and extract code elements."""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            print(f"Syntax error in {file_path}: {e}")
            return []
        
        elements = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                elements.append(self._parse_function(node, file_path))
            elif isinstance(node, ast.ClassDef):
                elements.append(self._parse_class(node, file_path))
        
        return elements
    
    def _parse_function(self, node: ast.FunctionDef, file_path: Path) -> CodeElement:
        """Parse a function definition."""
        return CodeElement(
            type="function",
            name=node.name,
            file_path=str(file_path),
            line_number=node.lineno,
            docstring=ast.get_docstring(node),
            signature=self._get_signature(node),
            body=ast.unparse(node)
        )
    
    def _parse_class(self, node: ast.ClassDef, file_path: Path) -> CodeElement:
        """Parse a class definition."""
        return CodeElement(
            type="class",
            name=node.name,
            file_path=str(file_path),
            line_number=node.lineno,
            docstring=ast.get_docstring(node),
            signature=f"class {node.name}",
            body=ast.unparse(node)
        )
    
    def _get_signature(self, node: ast.FunctionDef) -> str:
        """Extract function signature."""
        args = []
        for arg in node.args.args:
            args.append(arg.arg)
        return f"{node.name}({', '.join(args)})"


if __name__ == "__main__":
    # Test the parser
    parser = CodeParser()
    test_file = Path("/home/dwolfson/localGit/egeria-v6/egeria-python/pyegeria/__init__.py")
    if test_file.exists():
        elements = parser.parse_file(test_file)
        print(f"Found {len(elements)} code elements in {test_file}")
        for elem in elements[:5]:  # Print first 5
            print(f"  - {elem.type}: {elem.name} at line {elem.line_number}")
EOF
```

---

## Step 7: Test Ollama Integration

```bash
cat > scripts/test_ollama.py << 'EOF'
"""Test Ollama integration."""
import ollama

def test_ollama():
    """Test Ollama connection and generation."""
    print("Testing Ollama connection...")
    
    # List available models
    models = ollama.list()
    print(f"\nAvailable models: {[m['name'] for m in models['models']]}")
    
    # Test generation
    print("\nTesting generation with llama3.1:8b...")
    response = ollama.generate(
        model='llama3.1:8b',
        prompt='What is metadata management? Answer in one sentence.',
    )
    print(f"Response: {response['response']}")
    
    # Test code generation
    print("\nTesting code generation with codellama:13b...")
    response = ollama.generate(
        model='codellama:13b',
        prompt='Write a Python function to connect to a database. Just the function signature.',
    )
    print(f"Response: {response['response']}")

if __name__ == "__main__":
    test_ollama()
EOF

python scripts/test_ollama.py
```

---

## Step 8: Verify Setup

```bash
# Test imports
python -c "from advisor.config import settings; print('Config loaded successfully')"

# Test code parser
python advisor/data_prep/code_parser.py

# Check MLflow connection
python -c "import mlflow; mlflow.set_tracking_uri('http://localhost:5000'); print('MLflow connected')"

# Check Milvus connection
python -c "from pymilvus import connections; connections.connect(host='localhost', port='19530'); print('Milvus connected')"

# Check Ollama
curl http://localhost:11434/api/tags
```

---

## Step 9: Create First MLflow Experiment

```bash
cat > scripts/setup_mlflow.py << 'EOF'
"""Set up initial MLflow experiments."""
import mlflow

# Set tracking URI
mlflow.set_tracking_uri("http://localhost:5000")

# Create experiments
experiments = [
    "data-preparation",
    "embedding-model-tuning",
    "retrieval-optimization",
    "prompt-optimization",
    "agent-performance",
    "production-queries",
    "ollama-model-comparison"
]

for exp_name in experiments:
    try:
        mlflow.create_experiment(exp_name)
        print(f"✓ Created experiment: {exp_name}")
    except Exception as e:
        print(f"✗ Experiment {exp_name} already exists or error: {e}")

print("\nMLflow UI: http://localhost:5000")
EOF

python scripts/setup_mlflow.py
```

---

## Step 10: Create README

```bash
cat > README.md << 'EOF'
# Egeria Advisor

AI-powered advisor for the egeria-python repository using local LLMs (Ollama).

## Architecture

- **LLM**: Ollama (local) @ localhost:11434
- **Vector Store**: Milvus @ localhost:19530
- **Experiment Tracking**: MLflow @ localhost:5000
- **Metadata Platform**: Egeria @ localhost:9443

## Quick Start

1. Ensure Docker containers are running (Milvus, MLflow, Egeria, Ollama)
2. Set up environment: `source .venv/bin/activate`
3. Configure `.env` file
4. Run data preparation: `python -m advisor.data_prep.pipeline`

## Models

- **Query Agent**: llama3.1:8b (fast, general purpose)
- **Code Agent**: codellama:13b (code-specialized)
- **Embeddings**: sentence-transformers/all-MiniLM-L6-v2 (local)

## Development

- **Architecture**: See `egeria-advisor-plan.md`
- **Roadmap**: See `implementation-roadmap.md`
- **MLflow**: See `mlflow-experiment-tracking-guide.md`
- **Ollama**: See `ollama-setup-guide.md`

## Current Status

- Phase 1: ✅ Complete (Architecture & Design)
- Phase 2: 🚧 In Progress (Data Preparation)

## Links

- MLflow UI: http://localhost:5000
- Ollama API: http://localhost:11434
- Milvus: localhost:19530
- Egeria: https://localhost:9443
EOF
```

---

## Step 11: Initial Git Commit

```bash
# Create .gitignore
cat > .gitignore << 'EOF'
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
.venv/
venv/
ENV/

# IDEs
.vscode/
.idea/
*.swp
*.swo

# Data
data/
mlruns/
*.db

# Secrets
.env
*.key

# OS
.DS_Store
Thumbs.db
EOF

# Add files
git add .

# Initial commit
git commit -m "Initial project setup with Ollama - Phase 1 complete"
```

---

## Next Steps

### Immediate Tasks (Phase 2)

1. **Implement Data Preparation Pipeline**
   ```bash
   # Create pipeline.py
   touch advisor/data_prep/pipeline.py
   
   # Implement doc parser
   touch advisor/data_prep/doc_parser.py
   
   # Implement example extractor
   touch advisor/data_prep/example_extractor.py
   ```

2. **Test Data Parsing**
   ```bash
   # Parse sample files
   python -m advisor.data_prep.code_parser
   ```

3. **Set Up MLflow Tracking**
   ```bash
   # Log first experiment
   python scripts/test_mlflow_logging.py
   ```

### This Week's Goals

- [ ] Complete code parser implementation
- [ ] Implement document parser with Docling
- [ ] Extract examples from test files
- [ ] Generate embeddings for sample data
- [ ] Log experiments to MLflow
- [ ] Compare Ollama models (llama3.1 vs codellama)

---

## Troubleshooting

### Ollama Issues
```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Docker: Check container
docker ps | grep ollama
docker logs ollama

# Native: Restart service
pkill ollama
ollama serve &

# Pull missing models
docker exec ollama ollama pull llama3.1:8b
```

### Milvus Connection Issues
```bash
# Check if Milvus is running
docker ps | grep milvus

# Test connection
python -c "from pymilvus import connections; connections.connect('default', 'localhost', '19530')"
```

### MLflow Connection Issues
```bash
# Check if MLflow is running
curl http://localhost:5000

# Check experiments
python -c "import mlflow; mlflow.set_tracking_uri('http://localhost:5000'); print(mlflow.list_experiments())"
```

---

## Support

- **Project Lead**: dan.wolfson@pdr-associates.com
- **Egeria Community**: http://egeria-project.org/guides/community/

---

**Status**: Ready to begin Phase 2 implementation  
**Last Updated**: 2026-02-13