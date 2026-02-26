# Phase 7: Query Understanding & Response Generation - Prompt Improvements

## Status: ✅ Critical Improvements Applied

**Completed**: 2026-02-17  
**Focus**: Dramatically improved prompts for better answer quality

---

## Problem Identified

The original prompts were too generic and didn't enforce strict use of the provided context, leading to:
- ❌ Generic, unhelpful answers
- ❌ Hallucinated information
- ❌ Missing technical details
- ❌ No source citations
- ❌ Answers not using the retrieved context

## Solution: Strict Context-Only Prompts

### Key Changes

#### 1. System Prompt - Before vs After

**BEFORE** (Generic):
```
You are an expert code advisor for the Egeria project. Your role is to:
1. Provide accurate, helpful information about the codebase
2. Explain code functionality clearly and concisely
...
When code context is provided, use it to give specific, accurate answers.
```

**AFTER** (Strict):
```
You are an expert assistant for the Egeria Python library (pyegeria).

CRITICAL RULES - FOLLOW EXACTLY:
1. ONLY use information from the provided code context
2. If the context doesn't contain the answer, say: "I don't have enough information..."
3. ALWAYS cite specific files, classes, and methods from the context
4. Be technical and specific - include class names, method signatures, parameters
5. When showing code, make it complete and runnable
6. Do NOT make up or infer information not in the context
7. Do NOT use general knowledge about Python or other libraries
```

#### 2. User Prompt - Before vs After

**BEFORE** (Vague):
```
Based on the following code from the Egeria project, please answer the user's question.

# Relevant Code Context
{context}

# User Question
{user_query}

# Instructions
Please provide a helpful, accurate response based on the code context above.
```

**AFTER** (Explicit with Example):
```
# CODE CONTEXT FROM EGERIA PYTHON LIBRARY
{context}

# USER QUESTION
{user_query}

# YOUR TASK
Answer the question using ONLY the code context above. Follow these rules:
1. Use ONLY information from the context - do not add external knowledge
2. Cite specific files, classes, and methods
3. If showing code, make it complete with imports
4. If the context doesn't answer the question, say so explicitly
5. Be specific and technical - include parameter names, types, return values

Example good response:
"To create a glossary, use the GlossaryManager class from pyegeria.glossary_manager.py:

```python
from pyegeria import GlossaryManager

glossary_mgr = GlossaryManager(
    server_name="view-server",
    platform_url="https://localhost:9443",
    user_id="garygeeke"
)

glossary = glossary_mgr.create_glossary(
    display_name="My Glossary",
    description="Business vocabulary"
)
```

Source: pyegeria/glossary_manager.py - GlossaryManager.create_glossary()"

Now answer the user's question following this format.
```

### Why These Changes Matter

1. **Explicit Instructions**: The LLM now has clear, unambiguous rules
2. **Example Format**: Shows exactly what a good answer looks like
3. **Strict Context Usage**: Prevents hallucination and generic answers
4. **Citation Requirements**: Forces specific file/class/method references
5. **Fallback Behavior**: Clear instructions when context is insufficient

---

## Expected Improvements

### Before (Generic Answers)
```
Query: "What is a glossary?"
Answer: "A glossary is a collection of terms and definitions used in a specific domain..."
[Generic, could be from anywhere, no code, no citations]
```

### After (Specific, Technical Answers)
```
Query: "What is a glossary?"
Answer: "In Egeria, a glossary is managed by the GlossaryManager class from 
pyegeria/glossary_manager.py. It's a collection of glossary terms that define 
business vocabulary.

To create a glossary:

```python
from pyegeria import GlossaryManager

glossary_mgr = GlossaryManager(
    server_name="view-server",
    platform_url="https://localhost:9443",
    user_id="garygeeke"
)

glossary = glossary_mgr.create_glossary(
    display_name="My Glossary",
    description="Business vocabulary"
)
```

The create_glossary() method returns a Glossary object with a GUID that you can 
use to add terms.

Source: pyegeria/glossary_manager.py - GlossaryManager.create_glossary()"
[Specific, technical, with code, with citations]
```

---

## Testing the Improvements

### Test Commands

```bash
cd /home/dwolfson/localGit/egeria-v6/egeria-advisor
source .venv/bin/activate

# Test basic queries
egeria-advisor "What is a glossary?" --verbose
egeria-advisor "How do I create a collection?" --verbose
egeria-advisor "What is EgeriaClient?" --verbose
egeria-advisor "Show me how to find assets" --verbose
```

### What to Look For

**Good Signs** ✅:
- Specific class and method names
- Complete code examples with imports
- File path citations
- Technical parameter details
- "I don't have enough information..." when context is insufficient

**Bad Signs** ❌:
- Generic descriptions
- No code examples
- No citations
- Vague answers
- Hallucinated information

### Compare with MLflow

1. **Before improvements**: Check metrics from earlier queries
2. **After improvements**: Run new queries
3. **Compare**:
   - Response quality (subjective but obvious)
   - Context usage (should be higher)
   - Citation presence (should be in every answer)

---

## Additional Improvements Needed (Future)

### 1. Query-Type Specific Prompts

Different prompts for different query types:
- **Explanation queries**: Focus on "what" and "why"
- **How-to queries**: Focus on step-by-step code
- **Comparison queries**: Focus on differences
- **Debugging queries**: Focus on error analysis

### 2. Egeria-Specific Term Mapping

Map common terms to Egeria concepts:
```python
TERM_MAPPING = {
    "glossary": ["GlossaryManager", "glossary_manager", "create_glossary"],
    "collection": ["CollectionManager", "collection_manager"],
    "asset": ["AssetManager", "asset_manager", "Asset"],
    "term": ["GlossaryTerm", "create_term"],
}
```

### 3. Query Expansion

Expand queries to include related terms:
- "glossary" → also search for "GlossaryManager", "glossary_manager"
- "create" → also search for "add", "new", "initialize"

### 4. Response Post-Processing

- Extract code blocks and format them
- Add syntax highlighting markers
- Validate code syntax
- Add "Related Topics" section

### 5. Confidence Scoring

Rate answer quality based on:
- Number of sources used
- Relevance scores
- Presence of code examples
- Citation completeness

---

## Configuration Changes

No configuration changes needed - the improvements are in the code.

The existing config settings work well with the new prompts:
```yaml
rag:
  retrieval:
    top_k: 10              # Good - retrieves enough sources
    min_score: 0.5         # Good - not too strict
  generation:
    temperature: 0.3       # Good - focused answers
    max_tokens: 3000       # Good - allows detailed responses
```

---

## Measuring Success

### Quantitative Metrics (MLflow)

Track these in MLflow:
- `num_sources`: Should be 5-10 per query
- `avg_relevance_score`: Should be >0.6
- `context_length`: Should be >2000 chars
- `response_length`: Should be >500 chars (more detailed)

### Qualitative Metrics (Manual Review)

For each test query, rate 1-5:
- **Accuracy**: Is the information correct?
- **Specificity**: Are class/method names included?
- **Completeness**: Is the code example complete?
- **Citations**: Are sources cited?
- **Usefulness**: Would this help a user?

**Target**: Average score >4/5 across all metrics

---

## Next Steps

### Immediate (Test Now)

1. **Run test queries** with the new prompts
2. **Compare quality** with previous answers
3. **Check MLflow** for metrics
4. **Iterate if needed**

### Short Term (This Week)

1. **Create test dataset** of common queries
2. **Measure baseline** quality scores
3. **Implement query expansion** for better retrieval
4. **Add Egeria term mapping**

### Medium Term (Next Week)

1. **Implement query-type specific prompts**
2. **Add response post-processing**
3. **Implement confidence scoring**
4. **Create quality dashboard** in MLflow

---

## Files Modified

- `advisor/rag_system.py`:
  - `_get_system_prompt()`: Completely rewritten with strict rules
  - `_build_prompt()`: Enhanced with explicit instructions and examples

**Lines Changed**: ~60 lines
**Impact**: High - should dramatically improve answer quality

---

## Troubleshooting

### If Answers Are Still Poor

1. **Check retrieval**: Are relevant sources being found?
   ```bash
   egeria-advisor "query" --verbose
   # Look at Sources section
   ```

2. **Check context**: Is enough context being provided?
   ```python
   # Check in MLflow: context_length should be >2000
   ```

3. **Check model**: Is the model following instructions?
   ```bash
   # Try with explicit test
   egeria-advisor "What is a glossary? Be specific and cite sources."
   ```

4. **Check data**: Is the indexed data good quality?
   ```bash
   python scripts/test_vector_search.py
   ```

### If Model Ignores Instructions

Some models are better at following instructions than others:
- **llama3.1:8b**: Good instruction following ✓
- **llama3.2:3b**: Weaker instruction following
- **codellama:13b**: Excellent for code-related queries ✓

Consider upgrading if the model consistently ignores the strict rules.

---

## Success Criteria

Phase 7 is successful when:
- ✅ Answers include specific class/method names
- ✅ Code examples are complete and runnable
- ✅ Sources are cited in every answer
- ✅ No hallucinated information
- ✅ "I don't know" when context is insufficient
- ✅ User satisfaction >4/5

---

**Status**: Prompts improved, ready for testing
**Next**: Test with real queries and measure improvements with MLflow