"""
Collection configuration and metadata for multi-collection RAG system.

This module defines the metadata for each Milvus collection, including
source repositories, paths, domain terms, and relationships.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum


class ContentType(Enum):
    """Type of content in a collection."""
    CODE = "code"
    DOCUMENTATION = "documentation"
    EXAMPLES = "examples"
    MIXED = "mixed"


class Language(Enum):
    """Primary language of collection content."""
    PYTHON = "python"
    JAVA = "java"
    MARKDOWN = "markdown"
    MIXED = "mixed"


@dataclass
class CollectionMetadata:
    """Metadata for a Milvus collection."""
    
    # Basic info
    name: str
    description: str
    
    # Source information
    source_repo: str
    source_paths: List[str]
    
    # Content classification
    content_type: ContentType
    language: Language
    
    # Routing information
    domain_terms: List[str]
    related_collections: List[str] = field(default_factory=list)
    
    # Indexing configuration
    include_patterns: List[str] = field(default_factory=lambda: ["*.py", "*.md"])
    exclude_patterns: List[str] = field(default_factory=lambda: ["**/__pycache__/**", "**/deprecated/**"])
    
    # Collection settings
    enabled: bool = True
    priority: int = 1  # Higher = search first
    
    # RAG-specific parameters (NEW - Phase 2)
    chunk_size: int = 512  # Tokens per chunk
    chunk_overlap: int = 100  # Token overlap between chunks
    min_score: float = 0.35  # Minimum similarity score threshold
    default_top_k: int = 8  # Default number of results to retrieve
    
    def matches_query(self, query_lower: str, query_terms: List[str]) -> bool:
        """
        Check if this collection is relevant for a query.
        
        Args:
            query_lower: Lowercase query string
            query_terms: List of extracted query terms
            
        Returns:
            True if collection matches query domain
        """
        # Check if any domain terms appear in query
        for term in self.domain_terms:
            if term.lower() in query_lower:
                return True
            if term.lower() in [t.lower() for t in query_terms]:
                return True
        return False


# Phase 1: Python Collections
PYEGERIA_COLLECTION = CollectionMetadata(
    name="pyegeria",
    description="Core PyEgeria Python library for Egeria REST API",
    source_repo="https://github.com/odpi/egeria-python.git",
    source_paths=["pyegeria", "tests"],
    content_type=ContentType.CODE,
    language=Language.PYTHON,
    domain_terms=[
        "pyegeria", "python-client", "rest-client", "async-client",
        "widget", "egeria-client", "python-api", "python-sdk",
        "py-egeria"  # Add hyphenated variant
    ],
    related_collections=["pyegeria_cli", "pyegeria_drE", "egeria_docs"],
    include_patterns=["*.py", "*.md"],
    exclude_patterns=["**/__pycache__/**", "**/deprecated/**", "**/.pytest_cache/**"],
    priority=10,  # High priority for Python queries
    # RAG parameters optimized for Python code
    chunk_size=512,  # Standard for code
    chunk_overlap=100,  # 20% overlap
    min_score=0.35,  # Moderate threshold
    default_top_k=10  # More results for code queries
)

PYEGERIA_CLI_COLLECTION = CollectionMetadata(
    name="pyegeria_cli",
    description="hey_egeria CLI commands and tools",
    source_repo="https://github.com/odpi/egeria-python.git",
    source_paths=["commands"],
    content_type=ContentType.CODE,
    language=Language.PYTHON,
    domain_terms=[
        "hey-egeria", "hey_egeria", "cli", "command", "commands",
        "command-line", "terminal"
    ],
    related_collections=["pyegeria", "egeria_docs"],
    include_patterns=["*.py", "*.md"],
    exclude_patterns=["**/__pycache__/**"],
    priority=9,
    # RAG parameters optimized for CLI code
    chunk_size=512,  # Standard for code
    chunk_overlap=100,  # 20% overlap
    min_score=0.35,  # Moderate threshold
    default_top_k=10  # More results for code queries
)

PYEGERIA_DRE_COLLECTION = CollectionMetadata(
    name="pyegeria_drE",
    description="Dr. Egeria markdown-to-pyegeria translator",
    source_repo="https://github.com/odpi/egeria-python.git",
    source_paths=["md_processing"],
    content_type=ContentType.CODE,
    language=Language.PYTHON,
    domain_terms=[
        "dr-egeria", "dr_egeria", "dr egeria", "dr. egeria",  # Add space and period variants
        "pyegeria dre", "pyegeria-dre", "pyegeria_dre",  # Collection name variants
        "markdown", "document-automation",
        "markdown-translator", "dre", "markdown-to-pyegeria"
    ],
    related_collections=["pyegeria", "egeria_docs"],
    include_patterns=["*.py", "*.md"],
    exclude_patterns=["**/__pycache__/**"],
    priority=8,
    # RAG parameters optimized for markdown processing code
    chunk_size=512,  # Standard for code
    chunk_overlap=100,  # 20% overlap
    min_score=0.35,  # Moderate threshold
    default_top_k=8  # Standard results
)

# Phase 2: Java + Docs + Workspaces Collections
EGERIA_JAVA_COLLECTION = CollectionMetadata(
    name="egeria_java",
    description="Egeria Java codebase - OMAS, OMAG, OMRS services",
    source_repo="https://github.com/odpi/egeria.git",
    source_paths=["."],
    content_type=ContentType.CODE,
    language=Language.JAVA,
    domain_terms=[
        "java", "java-code", "java-implementation",  # More specific Java terms
        "access-service", "view-service", "integration-service",
        "governance-server", "metadata-server", "repository-proxy",
        "egeria-core", "egeria-server", "spring-boot"
    ],
    related_collections=["egeria_docs", "egeria_workspaces"],
    include_patterns=["*.java", "*.md"],
    exclude_patterns=["**/target/**", "**/build/**", "**/.gradle/**"],
    priority=7,
    enabled=True,  # Phase 2 - ENABLED
    # RAG parameters optimized for Java code (larger chunks)
    chunk_size=768,  # Larger for Java methods
    chunk_overlap=150,  # ~20% overlap
    min_score=0.35,  # Moderate threshold
    default_top_k=8  # Standard results
)

EGERIA_DOCS_COLLECTION = CollectionMetadata(
    name="egeria_docs",
    description="Egeria documentation - guides, tutorials, concepts (TO BE SPLIT)",
    source_repo="https://github.com/odpi/egeria-docs.git",
    source_paths=["."],
    content_type=ContentType.DOCUMENTATION,
    language=Language.MARKDOWN,
    domain_terms=[
        "documentation", "guide", "tutorial", "concept",
        "reference", "docs", "manual", "walkthrough",
        "egeria-docs", "egeria-documentation",  # Add specific collection identifiers
        # Add common Egeria concepts that should route to docs
        "omas", "omag", "omrs", "ocf", "oif",  # Architecture terms
        "architecture", "design", "overview",
        "myprofile", "my-profile", "my profile"  # Add myProfile variants
    ],
    related_collections=["pyegeria", "egeria_java", "egeria_workspaces"],
    include_patterns=["*.md", "*.rst"],
    exclude_patterns=["**/node_modules/**", "**/.git/**"],
    priority=11,  # Higher than pyegeria (10) to prioritize docs when mentioned
    enabled=False,  # DISABLED - Replaced by specialized collections
    # RAG parameters - TEMPORARY (will be replaced by split collections)
    chunk_size=1024,  # Mixed content
    chunk_overlap=200,  # ~20% overlap
    min_score=0.38,  # Lower threshold for docs
    default_top_k=8  # Standard results
)

EGERIA_WORKSPACES_COLLECTION = CollectionMetadata(
    name="egeria_workspaces",
    description="Egeria workspaces - Jupyter notebooks, deployment configs, examples",
    source_repo="https://github.com/odpi/egeria-workspaces.git",
    source_paths=["."],
    content_type=ContentType.EXAMPLES,
    language=Language.MIXED,
    domain_terms=[
        "workspace", "notebook", "jupyter", "example", "deployment",
        "docker", "kubernetes", "helm", "sample", "demo"
    ],
    related_collections=["pyegeria", "egeria_java", "egeria_docs"],
    include_patterns=["*.ipynb", "*.py", "*.md", "*.yaml", "*.yml"],
    exclude_patterns=["**/node_modules/**", "**/.git/**", "**/venv/**"],
    priority=5,
    enabled=True,  # Phase 2 - ENABLED
    # RAG parameters optimized for examples and tutorials
    chunk_size=1536,  # Large for complete examples
    chunk_overlap=300,  # ~20% overlap
    min_score=0.38,  # Lower threshold for examples
    default_top_k=6  # Fewer results for examples
)


# Phase 2b: Split egeria_docs into specialized collections
EGERIA_CONCEPTS_COLLECTION = CollectionMetadata(
    name="egeria_concepts",
    description="Egeria core concepts - short definitions and explanations",
    source_repo="https://github.com/odpi/egeria-docs.git",
    source_paths=["site/docs/concepts"],
    content_type=ContentType.DOCUMENTATION,
    language=Language.MARKDOWN,
    domain_terms=[
        "concept", "definition", "what is", "explain",
        "metadata", "governance", "lineage", "catalog",
        "asset", "glossary", "classification", "relationship"
    ],
    related_collections=["egeria_types", "egeria_general", "pyegeria"],
    include_patterns=["*.md"],
    exclude_patterns=["**/node_modules/**", "**/.git/**"],
    priority=12,  # Highest priority for concept queries
    enabled=True,  # ENABLED - Phase 2b
    # RAG parameters optimized for short concept definitions
    chunk_size=768,  # Medium chunks for concepts
    chunk_overlap=150,  # ~20% overlap
    min_score=0.45,  # High threshold for precise concepts
    default_top_k=5  # Fewer, more precise results
)

EGERIA_TYPES_COLLECTION = CollectionMetadata(
    name="egeria_types",
    description="Egeria type system - detailed type definitions and schemas",
    source_repo="https://github.com/odpi/egeria-docs.git",
    source_paths=["site/docs/types"],
    content_type=ContentType.DOCUMENTATION,
    language=Language.MARKDOWN,
    domain_terms=[
        "type", "schema", "attribute", "property",
        "entity", "relationship-type", "classification-type",
        "typedef", "type-definition", "type-system"
    ],
    related_collections=["egeria_concepts", "egeria_general", "egeria_java"],
    include_patterns=["*.md"],
    exclude_patterns=["**/node_modules/**", "**/.git/**"],
    priority=11,  # High priority for type queries
    enabled=True,  # ENABLED - Phase 2b
    # RAG parameters optimized for detailed type definitions
    chunk_size=1024,  # Larger chunks for complete type definitions
    chunk_overlap=200,  # ~20% overlap
    min_score=0.42,  # High threshold for type precision
    default_top_k=6  # Moderate results for types
)

EGERIA_GENERAL_COLLECTION = CollectionMetadata(
    name="egeria_general",
    description="Egeria general docs - tutorials, guides, and how-tos",
    source_repo="https://github.com/odpi/egeria-docs.git",
    source_paths=["site/docs"],  # All docs except concepts/ and types/
    content_type=ContentType.DOCUMENTATION,
    language=Language.MARKDOWN,
    domain_terms=[
        "tutorial", "guide", "how-to", "walkthrough",
        "getting-started", "setup", "configuration",
        "deployment", "installation", "usage"
    ],
    related_collections=["egeria_concepts", "egeria_types", "egeria_workspaces"],
    include_patterns=["*.md"],
    exclude_patterns=[
        "**/node_modules/**", "**/.git/**",
        "**/concepts/**",  # Exclude concepts (separate collection)
        "**/types/**"      # Exclude types (separate collection)
    ],
    priority=9,  # Lower priority than concepts/types
    enabled=True,  # ENABLED - Phase 2b
    # RAG parameters optimized for tutorials and guides
    chunk_size=1536,  # Large chunks for complete tutorials
    chunk_overlap=300,  # ~20% overlap
    min_score=0.38,  # Lower threshold for broader content
    default_top_k=8  # More results for general queries
)


# Collection registry
ALL_COLLECTIONS: Dict[str, CollectionMetadata] = {
    "pyegeria": PYEGERIA_COLLECTION,
    "pyegeria_cli": PYEGERIA_CLI_COLLECTION,
    "pyegeria_drE": PYEGERIA_DRE_COLLECTION,
    "egeria_java": EGERIA_JAVA_COLLECTION,
    "egeria_docs": EGERIA_DOCS_COLLECTION,  # Will be disabled after split
    "egeria_concepts": EGERIA_CONCEPTS_COLLECTION,  # NEW
    "egeria_types": EGERIA_TYPES_COLLECTION,  # NEW
    "egeria_general": EGERIA_GENERAL_COLLECTION,  # NEW
    "egeria_workspaces": EGERIA_WORKSPACES_COLLECTION,
}


def get_collection(name: str) -> Optional[CollectionMetadata]:
    """Get collection metadata by name."""
    return ALL_COLLECTIONS.get(name)


def get_enabled_collections() -> List[CollectionMetadata]:
    """Get all enabled collections."""
    return [c for c in ALL_COLLECTIONS.values() if c.enabled]


def get_collections_by_priority() -> List[CollectionMetadata]:
    """Get enabled collections sorted by priority (highest first)."""
    return sorted(get_enabled_collections(), key=lambda c: c.priority, reverse=True)


def get_phase1_collections() -> List[CollectionMetadata]:
    """Get Phase 1 (Python) collections."""
    return [
        PYEGERIA_COLLECTION,
        PYEGERIA_CLI_COLLECTION,
        PYEGERIA_DRE_COLLECTION,
    ]


def get_phase2_collections() -> List[CollectionMetadata]:
    """Get Phase 2 (Java + Docs + Workspaces) collections."""
    return [
        EGERIA_JAVA_COLLECTION,
        EGERIA_DOCS_COLLECTION,
        EGERIA_WORKSPACES_COLLECTION,
    ]


def enable_collection(name: str) -> bool:
    """
    Enable a collection.
    
    Args:
        name: Collection name
        
    Returns:
        True if collection was enabled, False if not found
    """
    collection = get_collection(name)
    if collection:
        collection.enabled = True
        return True
    return False


def disable_collection(name: str) -> bool:
    """
    Disable a collection.
    
    Args:
        name: Collection name
        
    Returns:
        True if collection was disabled, False if not found
    """
    collection = get_collection(name)
    if collection:
        collection.enabled = False
        return True
    return False


def get_collection_summary() -> Dict[str, Any]:
    """Get summary of all collections."""
    return {
        "total": len(ALL_COLLECTIONS),
        "enabled": len(get_enabled_collections()),
        "phase1": len([c for c in get_phase1_collections() if c.enabled]),
        "phase2": len([c for c in get_phase2_collections() if c.enabled]),
        "collections": {
            name: {
                "enabled": meta.enabled,
                "priority": meta.priority,
                "content_type": meta.content_type.value,
                "language": meta.language.value,
            }
            for name, meta in ALL_COLLECTIONS.items()
        }
    }