"""
Query pattern definitions for query type detection.

This module provides a centralized, extensible configuration for query patterns.
Patterns are organized by query type and priority for easy maintenance and extension.
"""

from typing import Dict, List
from enum import Enum


class QueryType(Enum):
    """Types of queries the system can handle."""
    CODE_SEARCH = "code_search"
    EXPLANATION = "explanation"
    EXAMPLE = "example"
    COMPARISON = "comparison"
    BEST_PRACTICE = "best_practice"
    DEBUGGING = "debugging"
    QUANTITATIVE = "quantitative"
    RELATIONSHIP = "relationship"
    REPORT = "report"  # MCP report generation
    COMMAND = "command"  # MCP command execution
    GENERAL = "general"


class PatternPriority(Enum):
    """Priority levels for pattern matching."""
    CRITICAL = 1    # Must match first (very specific)
    HIGH = 2        # High priority (specific multi-word)
    MEDIUM = 3      # Medium priority (action-oriented)
    LOW = 4         # Low priority (general patterns)
    FALLBACK = 5    # Last resort (catch-all)


# Pattern definitions organized by priority and query type
QUERY_PATTERNS = {
    # CRITICAL PRIORITY - Most specific patterns that must match first
    PatternPriority.CRITICAL: {
        QueryType.QUANTITATIVE: [
            "how many lines of code",
            "lines of code",
            "what is the average",
            "what's the average",
        ],
        QueryType.DEBUGGING: [
            "why isn't this working",
            "why isn't my",
            "i'm getting an error when",
            "getting an error when",
        ],
        QueryType.BEST_PRACTICE: [
            "what is the best practice",
            "what are the best practices",
            "recommended approach for",
        ],
        QueryType.COMPARISON: [
            "how does x differ from",
            "how does x compare to",
            "differ from",
        ],
    },
    
    # HIGH PRIORITY - Specific multi-word patterns
    PatternPriority.HIGH: {
        QueryType.REPORT: [
            "generate report", "create report", "run report", "show report",
            "report on", "get report", "produce report", "make report",
            "list reports", "available reports", "what reports"
        ],
        QueryType.COMMAND: [
            "run command", "execute command", "invoke", "call",
            "run the", "execute the", "perform", "do"
        ],
        QueryType.QUANTITATIVE: [
            "how many", "how much", "number of", "count",
            "total", "statistics", "metrics", "size",
            "summary", "overview", "average"
        ],
        QueryType.BEST_PRACTICE: [
            "best practice", "best way", "recommended", "should i",
            "proper way", "correct way", "standard"
        ],
        QueryType.COMPARISON: [
            "difference between", "compare", "versus", "vs",
            "differ from", "better", "which", "choose between"
        ],
        QueryType.DEBUGGING: [
            "why isn't", "isn't working", "not working",
            "getting an error", "how do i fix", "troubleshoot",
            "fix", "debug"
        ],
    },
    
    # MEDIUM PRIORITY - Action-oriented patterns
    PatternPriority.MEDIUM: {
        QueryType.CODE_SEARCH: [
            "show me how", "give me an example of", "how do i",
            "how to", "find examples", "find", "search",
            "locate", "where is", "get", "retrieve", "fetch"
        ],
        QueryType.EXAMPLE: [
            "show me examples", "give me examples", "show examples",
            "give me example", "examples of", "example of",
            "sample", "demo", "some examples"
        ],
        QueryType.RELATIONSHIP: [
            "what functions", "show me the", "what does",
            "what calls", "what imports", "what uses",
            "what are the dependencies", "related to",
            "relationship", "connected", "belong to",
            "methods of", "inherits", "extends", "depends on",
            "class hierarchy", "inheritance"
        ],
        QueryType.EXPLANATION: [
            "how does", "explain", "describe",
            "what is a", "what is the"
        ],
    },
    
    # LOW PRIORITY - General patterns
    PatternPriority.LOW: {
        QueryType.GENERAL: [
            "tell me about", "what is", "what are"
        ],
    },
}


# Domain-specific terms for context-aware detection
DOMAIN_TERMS = {
    "egeria_concepts": [
        "glossary", "collection", "asset", "governance zone",
        "lineage", "connection", "term", "category",
        "classification", "entity", "relationship",
        "catalog", "governance", "type", "property", "attribute",
        "connector", "integration", "server", "platform", "cohort",
        "repository", "archive"
    ],
    "egeria_code": [
        "egeria-core", "egeria-server", "egeria-ui", "egeria-connectors",
        "open-metadata", "omas", "omag", "omrs", "ocf", "oif",
        "access-service", "view-service", "integration-service",
        "governance-server", "metadata-server", "repository-proxy"
    ],
    "pyegeria_code": [
        "pyegeria", "python-client", "egeria-python", "py-egeria",
        "python-api", "python-sdk", "egeria-client", "rest-client",
        "async-client", "widget", "jupyter", "notebook"
    ],
    "egeria_workspaces": [
        "egeria-workspaces", "workspace", "project-workspace",
        "developer-workspace", "admin-workspace", "user-workspace",
        "collaboration-space", "team-workspace"
    ],
    "use_cases": [
        "use-case", "scenario", "example", "tutorial", "guide",
        "walkthrough", "demonstration", "sample", "template",
        "pattern", "best-practice", "reference-implementation"
    ],
    "deployment": [
        "deployment", "installation", "setup", "configuration",
        "docker", "kubernetes", "helm", "container", "pod",
        "service", "ingress", "volume", "secret", "configmap",
        "cloud", "aws", "azure", "gcp", "on-premise"
    ],
    "technical_concepts": [
        "class", "function", "method", "module", "package",
        "api", "endpoint", "service", "client", "import",
        "variable", "parameter", "return", "exception", "error",
        "request", "response", "configuration"
    ],
    "general_terms": [
        "system", "platform", "framework", "architecture",
        "design", "implementation", "testing", "documentation",
        "performance", "security", "authentication", "authorization"
    ]
}


# Special case rules for edge cases
SPECIAL_RULES = {
    "how_does_differ": {
        "pattern": "how does",
        "check_terms": ["differ", "compare"],
        "if_match": QueryType.COMPARISON,
        "if_no_match": None  # Continue to next rule
    },
    "tell_me_about_domain": {
        "pattern": "tell me about",
        "check_terms": DOMAIN_TERMS["egeria_concepts"],
        "if_match": QueryType.EXPLANATION,
        "if_no_match": QueryType.GENERAL
    },
    "how_does_system": {
        "pattern": "how does",
        "check_terms": DOMAIN_TERMS["general_terms"],
        "if_match": QueryType.GENERAL,
        "if_no_match": QueryType.EXPLANATION
    }
}


def get_patterns_by_priority() -> Dict[PatternPriority, Dict[QueryType, List[str]]]:
    """
    Get all patterns organized by priority.
    
    Returns:
        Dictionary mapping priority levels to query type patterns
    """
    return QUERY_PATTERNS


def get_domain_terms(category: str = None) -> List[str]:
    """
    Get domain-specific terms for context-aware detection.
    
    Args:
        category: Optional category filter (egeria_concepts, technical_concepts, general_terms)
        
    Returns:
        List of domain terms
    """
    if category:
        return DOMAIN_TERMS.get(category, [])
    
    # Return all terms if no category specified
    all_terms = []
    for terms in DOMAIN_TERMS.values():
        all_terms.extend(terms)
    return all_terms


def get_special_rules() -> Dict[str, Dict]:
    """
    Get special case rules for edge case handling.
    
    Returns:
        Dictionary of special rules
    """
    return SPECIAL_RULES


def add_pattern(query_type: QueryType, pattern: str, priority: PatternPriority = PatternPriority.MEDIUM):
    """
    Add a new pattern to the pattern database.
    
    Args:
        query_type: The query type this pattern should match
        pattern: The pattern string to match
        priority: Priority level for this pattern
    """
    if priority not in QUERY_PATTERNS:
        QUERY_PATTERNS[priority] = {}
    
    if query_type not in QUERY_PATTERNS[priority]:
        QUERY_PATTERNS[priority][query_type] = []
    
    if pattern not in QUERY_PATTERNS[priority][query_type]:
        QUERY_PATTERNS[priority][query_type].append(pattern)


def add_domain_term(term: str, category: str = "egeria_concepts"):
    """
    Add a new domain term for context-aware detection.
    
    Args:
        term: The domain term to add
        category: Category for the term (default: egeria_concepts)
    """
    if category not in DOMAIN_TERMS:
        DOMAIN_TERMS[category] = []
    
    if term not in DOMAIN_TERMS[category]:
        DOMAIN_TERMS[category].append(term)


def remove_pattern(query_type: QueryType, pattern: str, priority: PatternPriority = None):
    """
    Remove a pattern from the pattern database.
    
    Args:
        query_type: The query type to remove pattern from
        pattern: The pattern string to remove
        priority: Optional priority level (if None, searches all priorities)
    """
    if priority:
        priorities = [priority]
    else:
        priorities = list(QUERY_PATTERNS.keys())
    
    for pri in priorities:
        if pri in QUERY_PATTERNS and query_type in QUERY_PATTERNS[pri]:
            if pattern in QUERY_PATTERNS[pri][query_type]:
                QUERY_PATTERNS[pri][query_type].remove(pattern)