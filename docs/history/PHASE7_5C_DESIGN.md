# Phase 7.5c: Report Spec Queries - Design Document

## Overview

Phase 7.5c adds support for queries about available report specifications (output format sets) in the egeria-python library. This enables users to discover and understand the various ways data can be formatted and displayed.

## Background

The egeria-python library uses a sophisticated system of "report specs" (also called "output format sets") that define how data is formatted for different output types (DICT, TABLE, JSON, MD, etc.). These specs include:

- **Column/Attribute definitions**: What fields to display
- **Output type support**: Which formats are available (DICT, TABLE, JSON, etc.)
- **Actions**: Functions that can be called to retrieve data
- **Aliases**: Alternative names for the same spec
- **Families**: Logical groupings of related specs
- **Target types**: The Open Metadata entity type the spec is designed for

## Architecture

### Components

1. **Report Spec Extractor** (`scripts/generate_report_specs.py`)
   - Extracts metadata from pyegeria.base_report_formats.report_specs
   - Generates structured JSON with searchable text
   - Tracks families, target types, and output types

2. **Report Spec Query Handler** (`advisor/report_specs.py`)
   - Loads cached report spec data
   - Answers natural language queries about available specs
   - Provides filtering by family, target type, output type

3. **Integration with RAG System**
   - Early return for report spec queries (bypasses vector search)
   - Direct query processing for fast responses
   - Integration with query processor for detection

## Data Structure

### Extracted Metadata

```json
{
  "total_specs": 150,
  "families": {
    "Collections": ["Collections", "BasicCollections", ...],
    "Glossary": ["Terms", "Glossaries", ...]
  },
  "target_types": {
    "GlossaryTerm": ["Terms", "Basic-Terms"],
    "Collection": ["Collections", "Folders"]
  },
  "output_types": ["DICT", "TABLE", "JSON", "MD", "LIST", "REPORT"],
  "specs": [
    {
      "name": "Collections",
      "heading": "Collections Report",
      "description": "Display collection information",
      "target_type": "Collection",
      "family": "Collections",
      "aliases": ["Collection"],
      "annotations": {
        "wiki": ["https://..."]
      },
      "formats": [
        {
          "types": ["DICT", "TABLE"],
          "columns": [
            {"name": "Display Name", "key": "display_name", "format": false},
            {"name": "Description", "key": "description", "format": true}
          ]
        }
      ],
      "action": {
        "function": "find_collections",
        "required_params": ["search_string"],
        "optional_params": ["start_from", "page_size"],
        "spec_params": {"output_format": "DICT"}
      },
      "searchable_text": "Collections Collection display_name description..."
    }
  ]
}
```

## Query Types

### Supported Queries

1. **List all specs**: "What report specs are available?"
2. **Filter by family**: "Show me all glossary report specs"
3. **Filter by target type**: "What specs work with GlossaryTerm?"
4. **Filter by output type**: "Which specs support TABLE format?"
5. **Find specific spec**: "Tell me about the Collections report spec"
6. **Get spec details**: "What columns are in the Terms spec?"
7. **Find by action**: "Which specs can call find_collections?"

### Query Detection

Queries are detected by keywords:
- "report spec", "format set", "output format"
- "available specs", "list specs"
- "what columns", "what fields"
- "supports TABLE", "supports JSON"
- Family names: "glossary specs", "collection specs"

## Implementation Plan

### Step 1: Report Spec Extractor ✓ (In Progress)
- [x] Create `scripts/generate_report_specs.py`
- [ ] Test extraction with pyegeria installed
- [ ] Verify JSON output structure
- [ ] Add to update_all_analysis.sh

### Step 2: Report Spec Query Handler
- [ ] Create `advisor/report_specs.py`
- [ ] Implement query methods:
  - `list_all_specs()`
  - `filter_by_family(family)`
  - `filter_by_target_type(type)`
  - `filter_by_output_type(type)`
  - `get_spec_details(name)`
  - `search_specs(query)`
- [ ] Add natural language query processing
- [ ] Create singleton accessor

### Step 3: Integration
- [ ] Update `advisor/query_processor.py`:
  - Add REPORT_SPEC query type
  - Add detection patterns
- [ ] Update `advisor/rag_system.py`:
  - Add early return for report spec queries
  - Call report spec handler
- [ ] Test integration

### Step 4: Testing
- [ ] Create `scripts/test_report_specs.py`
- [ ] Test all query types
- [ ] Verify response quality
- [ ] Test edge cases

### Step 5: Documentation
- [ ] Update QUICK_START.md
- [ ] Add examples to README
- [ ] Document query patterns
- [ ] Create PHASE7_5C_COMPLETE.md

## Example Usage

```python
from advisor.report_specs import get_report_spec_handler

handler = get_report_spec_handler()

# List all specs
specs = handler.list_all_specs()

# Filter by family
glossary_specs = handler.filter_by_family("Glossary")

# Get spec details
details = handler.get_spec_details("Collections")

# Natural language query
result = handler.answer_query("What report specs support TABLE format?")
```

## CLI Integration

```bash
# Query report specs
egeria-advisor query "What report specs are available?"
egeria-advisor query "Show me glossary report specs"
egeria-advisor query "What columns are in the Terms spec?"
```

## Benefits

1. **Discoverability**: Users can easily find available report specs
2. **Documentation**: Self-documenting system for output formats
3. **Integration**: Seamless integration with existing query system
4. **Performance**: Fast responses without vector search
5. **Completeness**: Covers all available specs in egeria-python

## Future Enhancements

1. **Spec Recommendations**: Suggest best spec for a given use case
2. **Custom Specs**: Support for user-defined report specs
3. **Spec Validation**: Validate spec definitions
4. **Spec Generation**: Generate new specs from templates
5. **Spec Comparison**: Compare different specs side-by-side

## Dependencies

- pyegeria library (egeria-python)
- Existing RAG system components
- Query processor
- MLflow tracking (optional)

## Timeline

- Extractor: 1 hour (in progress)
- Query Handler: 2 hours
- Integration: 1 hour
- Testing: 1 hour
- Documentation: 1 hour

**Total: ~6 hours**

## Success Criteria

- [x] Report spec extractor creates valid JSON
- [ ] Query handler answers all query types correctly
- [ ] Integration with RAG system works seamlessly
- [ ] All tests pass
- [ ] Documentation is complete and clear
- [ ] Users can discover and use report specs easily