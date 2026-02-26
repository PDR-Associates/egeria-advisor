# Phase 8 Improvements Plan

## Overview

This document outlines the plan to fix the two main quality issues identified during testing:
1. Query type detection accuracy (currently 66%, target 90%+)
2. Query scoping for path-filtered queries (not implemented)

---

## Issue 1: Query Type Detection

### Current State
- **Test Pass Rate**: 21/32 (66%)
- **Failing Tests**: 11 tests
  - 8 query type detection failures
  - 2 context extraction failures
  - 1 relationship query failure

### Root Causes

#### 1. Pattern Ambiguity
**Problem**: EXPLANATION patterns are too broad and match before specific patterns.

**Examples**:
```python
"Give me examples" → Detected as CODE_SEARCH, should be EXAMPLE
"Why isn't working?" → Detected as EXPLANATION, should be DEBUGGING
"What is average?" → Detected as EXPLANATION, should be QUANTITATIVE
"What does X import?" → Detected as EXPLANATION, should be RELATIONSHIP
```

**Cause**: Pattern matching is first-match, not best-match.

#### 2. No Confidence Scores
**Problem**: System doesn't know when detection is uncertain.

**Impact**: Can't identify ambiguous queries for fallback handling.

#### 3. No Context Awareness
**Problem**: Doesn't consider surrounding words or query structure.

**Example**: "What is" could be EXPLANATION or QUANTITATIVE depending on what follows.

### Solution Approach

#### Step 1: Add Pattern Exclusions
Add negative patterns to prevent false matches:

```python
QUANTITATIVE_INDICATORS = ["how many", "how much", "count", "number of", "total"]
RELATIONSHIP_INDICATORS = ["import", "depend", "use", "call", "inherit"]

# In detect_query_type:
if "what is" in query:
    # Check for quantitative indicators
    if any(ind in query for ind in QUANTITATIVE_INDICATORS):
        return QueryType.QUANTITATIVE
    # Check for relationship indicators
    elif any(ind in query for ind in RELATIONSHIP_INDICATORS):
        return QueryType.RELATIONSHIP
    else:
        return QueryType.EXPLANATION
```

#### Step 2: Add Confidence Scores
Return confidence with detection:

```python
def detect_query_type_with_confidence(self, query: str) -> Tuple[QueryType, float]:
    """
    Detect query type and return confidence score.
    
    Returns:
        Tuple of (QueryType, confidence_score)
        confidence_score: 0.0-1.0, where 1.0 is certain
    """
    matches = []
    
    for query_type, patterns in self.query_patterns.items():
        for pattern in patterns:
            if pattern in query:
                # Calculate confidence based on pattern specificity
                confidence = self._calculate_confidence(pattern, query)
                matches.append((query_type, confidence, pattern))
    
    if not matches:
        return (QueryType.GENERAL, 0.5)
    
    # Sort by confidence, return highest
    matches.sort(key=lambda x: x[1], reverse=True)
    return (matches[0][0], matches[0][1])
```

#### Step 3: Improve Pattern Ordering
Reorganize patterns by specificity:

```python
def _build_query_patterns(self):
    return {
        # Tier 1: Highly specific multi-word patterns
        QueryType.QUANTITATIVE: [
            "how many", "how much", "number of", "count of",
            "total number", "how large", "size of"
        ],
        QueryType.BEST_PRACTICE: [
            "best practice", "best way", "recommended way",
            "should i", "is it better"
        ],
        
        # Tier 2: Specific single patterns with context
        QueryType.DEBUGGING: [
            "why isn't", "why doesn't", "not working",
            "error", "fails", "broken"
        ],
        QueryType.RELATIONSHIP: [
            "what imports", "what depends", "what uses",
            "who calls", "inheritance"
        ],
        
        # Tier 3: General patterns (check last)
        QueryType.EXPLANATION: [
            "what is", "what does", "explain", "describe"
        ],
    }
```

### Implementation Tasks

1. ✅ **Add confidence scoring** (2 hours)
   - Implement `_calculate_confidence()` method
   - Update `detect_query_type()` to return confidence
   - Log confidence to MLflow

2. ✅ **Add pattern exclusions** (1 hour)
   - Create indicator lists
   - Add context-aware detection
   - Update pattern matching logic

3. ✅ **Reorganize patterns** (1 hour)
   - Group by specificity
   - Add more specific patterns
   - Test pattern ordering

4. ✅ **Update tests** (1 hour)
   - Add confidence assertions
   - Test ambiguous queries
   - Verify improvements

### Success Criteria
- Test pass rate: 90%+ (29/32 tests)
- Confidence scores logged to MLflow
- Ambiguous queries identified (confidence < 0.7)

---

## Issue 2: Query Scoping

### Current State
- **Status**: Not implemented
- **Impact**: "How many classes in pyegeria folder?" returns repo-wide count
- **User Experience**: Confusing and incorrect results

### Root Causes

#### 1. No Path Extraction
**Problem**: Query processor doesn't extract path/scope from queries.

**Missing**: Pattern matching for path indicators like:
- "in the X folder"
- "in X directory"
- "in X module"
- "under X"

#### 2. No Scope Filtering in Analytics
**Problem**: Analytics module only has repo-wide statistics.

**Missing**:
- Per-directory statistics
- Path filtering logic
- Scope parameter in methods

#### 3. No Per-Directory Statistics
**Problem**: `pipeline_summary.json` only contains repo-wide aggregates.

**Missing**: Statistics broken down by directory/module.

### Solution Approach

#### Step 1: Add Path Extraction to Query Processor

```python
def extract_path(self, query: str) -> Optional[str]:
    """
    Extract path/scope from query.
    
    Examples:
        "classes in pyegeria folder" → "pyegeria"
        "functions in the utils module" → "utils"
        "code under src/main" → "src/main"
    
    Returns:
        Path string or None if no path specified
    """
    patterns = [
        r'in (?:the )?([a-zA-Z0-9_/\-]+) (?:folder|directory|module|package)',
        r'(?:folder|directory|module|package) ([a-zA-Z0-9_/\-]+)',
        r'under ([a-zA-Z0-9_/\-]+)',
        r'within ([a-zA-Z0-9_/\-]+)',
    ]
    
    query_lower = query.lower()
    for pattern in patterns:
        match = re.search(pattern, query_lower)
        if match:
            return match.group(1)
    
    return None
```

#### Step 2: Generate Per-Directory Statistics

Create a new script to generate directory-level statistics:

```python
# scripts/generate_directory_stats.py

def generate_directory_stats(base_path: Path) -> Dict[str, Dict]:
    """
    Generate statistics for each directory.
    
    Returns:
        {
            "pyegeria": {
                "classes": 45,
                "functions": 120,
                "methods": 380,
                ...
            },
            "pyegeria/admin_services": {
                "classes": 12,
                ...
            }
        }
    """
    stats = {}
    
    for dir_path in base_path.rglob("*"):
        if dir_path.is_dir() and not dir_path.name.startswith('.'):
            rel_path = str(dir_path.relative_to(base_path))
            stats[rel_path] = analyze_directory(dir_path)
    
    return stats
```

#### Step 3: Add Scope Filtering to Analytics

```python
# In advisor/analytics.py

def get_classes_in_path(self, path_filter: Optional[str] = None) -> int:
    """
    Get number of classes, optionally filtered by path.
    
    Args:
        path_filter: Path to filter by (e.g., "pyegeria", "pyegeria/admin_services")
    
    Returns:
        Count of classes in specified path or entire repo
    """
    if path_filter is None:
        # Return repo-wide count
        return self.stats.get("code", {}).get("by_type", {}).get("class", 0)
    
    # Get directory-specific stats
    dir_stats = self.stats.get("by_directory", {})
    
    # Find matching directories (support partial paths)
    matching_dirs = [
        dir_path for dir_path in dir_stats.keys()
        if path_filter in dir_path or dir_path.startswith(path_filter)
    ]
    
    # Sum classes across matching directories
    total = 0
    for dir_path in matching_dirs:
        total += dir_stats[dir_path].get("classes", 0)
    
    return total

def answer_quantitative_query(self, query: str, path_filter: Optional[str] = None) -> str:
    """
    Answer quantitative query with optional path filtering.
    
    Args:
        query: User's question
        path_filter: Optional path to filter results
    """
    query_lower = query.lower()
    
    if "how many class" in query_lower:
        count = self.get_classes_in_path(path_filter)
        
        if path_filter:
            return f"There are **{count:,} classes** in the {path_filter} directory."
        else:
            return f"There are **{count:,} classes** in the egeria-python codebase."
    
    # ... other query types
```

#### Step 4: Integrate Path Extraction with RAG System

```python
# In advisor/rag_system.py

def _process_query(self, user_query: str, include_context: bool) -> Dict[str, Any]:
    # Process query
    query_analysis = self.query_processor.process(user_query)
    
    # Extract path if present
    path_filter = self.query_processor.extract_path(user_query)
    
    # Handle quantitative queries with path filtering
    if query_analysis['query_type'] == 'quantitative':
        response = self.analytics.answer_quantitative_query(
            user_query,
            path_filter=path_filter  # Pass path filter
        )
        return {
            "query": user_query,
            "response": response,
            "query_type": "quantitative",
            "path_filter": path_filter,  # Include in result
            ...
        }
```

### Implementation Tasks

1. ✅ **Add path extraction** (2 hours)
   - Implement `extract_path()` method
   - Add regex patterns
   - Test with various queries
   - Update `extract_context()` to include path

2. ✅ **Generate directory statistics** (3 hours)
   - Create `generate_directory_stats.py` script
   - Analyze each directory
   - Save to `directory_stats.json`
   - Update `pipeline_summary.json` format

3. ✅ **Add scope filtering to analytics** (2 hours)
   - Add `path_filter` parameter to methods
   - Implement filtering logic
   - Handle partial path matches
   - Update all query handlers

4. ✅ **Integrate with RAG system** (1 hour)
   - Pass path filter to analytics
   - Include path in results
   - Log path to MLflow
   - Update response formatting

5. ✅ **Test scoped queries** (1 hour)
   - Test "classes in pyegeria"
   - Test "functions in admin_services"
   - Test partial paths
   - Verify accuracy

### Success Criteria
- "How many classes in pyegeria?" returns pyegeria-only count
- Partial paths work ("admin" matches "pyegeria/admin_services")
- Path logged to MLflow for analysis
- Accurate results for all scoped queries

---

## Implementation Timeline

### Phase 1: Query Type Detection (5 hours)
- Day 1 Morning: Confidence scoring (2h)
- Day 1 Afternoon: Pattern exclusions + reorganization (2h)
- Day 1 Evening: Testing and validation (1h)

### Phase 2: Query Scoping (9 hours)
- Day 2 Morning: Path extraction (2h)
- Day 2 Afternoon: Directory statistics generation (3h)
- Day 3 Morning: Scope filtering in analytics (2h)
- Day 3 Afternoon: Integration + testing (2h)

### Total: 14 hours (2-3 days)

---

## Testing Strategy

### Unit Tests
- Test confidence scoring
- Test path extraction
- Test scope filtering
- Test pattern matching

### Integration Tests
- Test end-to-end scoped queries
- Test confidence logging to MLflow
- Test error handling

### Validation
- Run full test suite
- Verify 90%+ pass rate
- Check MLflow metrics
- Manual testing of edge cases

---

## Rollback Plan

If issues arise:
1. Revert to previous version (git)
2. Disable new features via config
3. Fall back to repo-wide statistics
4. Log issues for future fix

---

## Success Metrics

### Query Type Detection
- ✅ Test pass rate: 90%+ (currently 66%)
- ✅ Confidence scores logged
- ✅ Ambiguous queries identified
- ✅ No regression in working queries

### Query Scoping
- ✅ Scoped queries work correctly
- ✅ Path extraction accurate
- ✅ Directory stats generated
- ✅ Results match expectations

### Overall
- ✅ User satisfaction improved
- ✅ Query accuracy increased
- ✅ System more reliable
- ✅ Better monitoring and debugging

---

## Next Steps

1. Review and approve plan
2. Start with query type detection (lower risk)
3. Test thoroughly before moving to scoping
4. Deploy scoping incrementally
5. Monitor metrics in MLflow
6. Iterate based on feedback

---

*Created: 2026-02-18*
*Status: Ready for implementation*