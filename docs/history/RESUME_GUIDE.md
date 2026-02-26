# Egeria Advisor - Resume Guide

**Last Updated:** February 14, 2026  
**Current Phase:** Phase 4 - RAG System Testing

## Quick Status Check

### 1. Check System Health

```bash
# Navigate to project
cd /home/dwolfson/localGit/egeria-v6/egeria-advisor

# Activate virtual environment
source .venv/bin/activate

# Check Ollama status
ollama list

# Check Milvus connection
python -c "from pymilvus import connections, utility; connections.connect(host='localhost', port='19530'); print(f'Collections: {utility.list_collections()}')"

# Check MLflow (mapped to port 5025 on host)
curl -s http://localhost:5025/health
```

### 2. Verify Services Running

```bash
# Check Ollama service
systemctl status ollama

# Check if Ollama is responding
curl http://localhost:11434/api/tags

# Check Milvus (Docker)
docker ps | grep milvus

# Check MLflow (Docker)
docker ps | grep mlflow
```

## Current State (Phase 4)

### ✅ Completed
1. **Phase 1-2:** Data preparation pipeline (4,601 code elements extracted)
2. **Phase 3:** Vector store integration with Milvus
3. **Ollama Setup:** AMD ROCm GPU acceleration configured
   - Model: llama3.2:3b (2.0 GB)
   - GPU: AMD Radeon 890M (gfx1100)
   - All 29 layers on GPU
4. **RAG Components:** All modules implemented
   - `advisor/llm_client.py` - Ollama integration
   - `advisor/rag_retrieval.py` - Vector retrieval
   - `advisor/query_processor.py` - Query understanding
   - `advisor/rag_system.py` - Complete RAG pipeline

### 🔄 In Progress
- **Phase 4 Testing:** RAG system integration tests

### ⏭️ Next Steps
- Document Phase 4 completion
- Begin Phase 5 (Agent Framework) or Phase 6 (CLI Interface)

## How to Resume Testing

### If Test Was Interrupted

```bash
# Navigate to project
cd /home/dwolfson/localGit/egeria-v6/egeria-advisor

# Activate environment
source .venv/bin/activate

# Run full test suite
python scripts/test_rag_system.py

# Or run with output logging
python scripts/test_rag_system.py 2>&1 | tee test_output.log

# Check if test is running
ps aux | grep test_rag_system
```

### Individual Component Tests

```bash
# Test just the health check
python -c "
from advisor.rag_system import get_rag_system
rag = get_rag_system()
print(rag.health_check())
"

# Test a simple query
python -c "
from advisor.rag_system import get_rag_system
rag = get_rag_system()
result = rag.query('What is EgeriaClient?', track_metrics=False)
print(result['response'])
"

# Test vector search
python scripts/test_vector_search.py
```

### Check Test Results

```bash
# View test output log
cat test_output.log

# Check MLflow for tracked experiments
# Open browser to: http://localhost:5025
# Note: Docker container port 5000 is mapped to host port 5025

# Check Ollama logs
journalctl -u ollama -n 100 --no-pager
```

## Troubleshooting

### Ollama Not Responding

```bash
# Check service status
systemctl status ollama

# Restart if needed
sudo systemctl restart ollama

# Check logs
journalctl -u ollama -n 50 --no-pager

# Verify model is loaded
ollama list
```

### Milvus Connection Issues

```bash
# Check Milvus container
docker ps | grep milvus

# Restart if needed
docker restart milvus-standalone

# Test connection
python -c "from pymilvus import connections; connections.connect(host='localhost', port='19530'); print('Connected!')"
```

### Embedding Generation Issues

```bash
# Check GPU availability
python -c "import torch; print(f'CUDA: {torch.cuda.is_available()}'); print(f'ROCm: {torch.version.hip}')"

# Test embedding generation
python -c "
from advisor.embeddings import get_embedding_generator
gen = get_embedding_generator()
emb = gen.generate_embedding('test')
print(f'Embedding shape: {len(emb)}')
"
```

### MLflow Not Accessible

```bash
# Check MLflow container
docker ps | grep mlflow

# Restart if needed
docker restart mlflow

# Access UI
# Open browser to: http://localhost:5025
# Note: Docker container port 5000 is mapped to host port 5025
```

## Next Phase Options

### Option A: Phase 5 - Agent Framework

**Goal:** Implement specialized agents for different query types

**Steps:**
1. Set up BeeAI Framework or LangChain agents
2. Implement Query Agent (factual questions)
3. Implement Code Example Agent (code generation)
4. Implement Conversation Agent (multi-turn)
5. Create agent orchestration

**Start Command:**
```bash
cd /home/dwolfson/localGit/egeria-v6/egeria-advisor
source .venv/bin/activate
# Begin agent implementation
```

### Option B: Phase 6 - CLI Interface

**Goal:** Create command-line interface for the advisor

**Steps:**
1. Design CLI commands
2. Integrate with hey_egeria
3. Implement interactive mode
4. Add output formatting
5. Create help system

**Start Command:**
```bash
cd /home/dwolfson/localGit/egeria-v6/egeria-advisor
source .venv/bin/activate
# Begin CLI implementation
```

## Quick Reference Commands

### Start Everything

```bash
# 1. Ensure Ollama is running
systemctl status ollama

# 2. Ensure Milvus is running
docker ps | grep milvus

# 3. Ensure MLflow is running
docker ps | grep mlflow

# 4. Activate environment
cd /home/dwolfson/localGit/egeria-v6/egeria-advisor
source .venv/bin/activate

# 5. Run tests
python scripts/test_rag_system.py
```

### Interactive Testing

```bash
# Start Python REPL
cd /home/dwolfson/localGit/egeria-v6/egeria-advisor
source .venv/bin/activate
python

# Then in Python:
from advisor.rag_system import get_rag_system
rag = get_rag_system()

# Test health
print(rag.health_check())

# Ask a question
result = rag.query("How do I create a glossary?")
print(result['response'])

# Check sources
for source in result['sources']:
    print(f"- {source['file_path']}: {source['name']}")
```

### View Logs

```bash
# Ollama logs
journalctl -u ollama -f

# Milvus logs
docker logs -f milvus-standalone

# MLflow logs
docker logs -f mlflow

# Application logs (if running)
tail -f test_output.log
```

## File Locations

- **Project Root:** `/home/dwolfson/localGit/egeria-v6/egeria-advisor`
- **Virtual Environment:** `.venv/`
- **Configuration:** `config/advisor.yaml`
- **Cache Data:** `data/cache/`
- **Test Scripts:** `scripts/`
- **Core Modules:** `advisor/`
- **Ollama Service:** `/etc/systemd/system/ollama.service`
- **Ollama Models:** `/usr/share/ollama/.ollama/models/`

## Important Notes

1. **GPU Acceleration:** Ollama is using AMD Radeon 890M with ROCm
2. **Model:** llama3.2:3b (2.0 GB, all layers on GPU)
3. **Vector Store:** 4,601 code elements indexed in Milvus
4. **Embeddings:** sentence-transformers/all-MiniLM-L6-v2 (384 dimensions)
5. **MLflow:** Tracking experiments at http://localhost:5025 (Docker port 5000→5025)

## Contact Points

- **Milvus:** localhost:19530
- **MLflow:** http://localhost:5025 (Docker container port 5000 mapped to host port 5025)
- **Ollama:** http://localhost:11434

---

**To Resume:** Run the commands in the "Quick Status Check" section to verify all services, then proceed with testing or next phase implementation.