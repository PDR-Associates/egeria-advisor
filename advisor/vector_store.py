"""
Vector store management for Egeria Advisor using Milvus.

This module handles all interactions with the Milvus vector database,
including collection management, data ingestion, and similarity search.
"""

from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import json
from dataclasses import dataclass
from loguru import logger

from pymilvus import (
    connections,
    Collection,
    CollectionSchema,
    FieldSchema,
    DataType,
    utility
)

from advisor.config import settings
from advisor.embeddings import get_embedding_generator
import numpy as np


@dataclass
class SearchResult:
    """Result from a vector similarity search."""
    id: str
    score: float
    text: str
    metadata: Dict[str, Any]


class VectorStoreManager:
    """Manage Milvus vector store collections."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None
    ):
        """
        Initialize vector store manager.

        Args:
            host: Milvus host
            port: Milvus port
            user: Milvus user (optional)
            password: Milvus password (optional)
        """
        self.host = host or settings.milvus_host
        self.port = port or settings.milvus_port
        self.user = user or (settings.milvus_user if hasattr(settings, 'milvus_user') else None)
        self.password = password or (settings.milvus_password if hasattr(settings, 'milvus_password') else None)

        self.embedding_generator = get_embedding_generator()
        self.embedding_dim = self.embedding_generator.get_embedding_dim()

        self._connected = False
        self._collections: Dict[str, Collection] = {}

        logger.info(f"Initialized VectorStoreManager for {self.host}:{self.port}")

    def connect(self):
        """Connect to Milvus server."""
        if self._connected:
            logger.debug("Already connected to Milvus")
            return

        try:
            logger.info(f"Connecting to Milvus at {self.host}:{self.port}")

            conn_params = {
                "host": self.host,
                "port": str(self.port)
            }

            if self.user:
                conn_params["user"] = self.user
            if self.password:
                conn_params["password"] = self.password

            connections.connect(alias="default", **conn_params)

            version = utility.get_server_version()
            logger.info(f"✓ Connected to Milvus v{version}")
            self._connected = True

        except Exception as e:
            logger.error(f"Failed to connect to Milvus: {e}")
            raise

    def is_connected(self) -> bool:
        """Check if connected to Milvus server."""
        return self._connected

    def disconnect(self):
        """Disconnect from Milvus server."""
        if self._connected:
            connections.disconnect("default")
            self._connected = False
            self._collections.clear()
            logger.info("Disconnected from Milvus")

    def create_collection(
        self,
        collection_name: str,
        description: str = "",
        drop_if_exists: bool = False,
        extra_fields: Optional[List[FieldSchema]] = None
    ) -> Collection:
        """
        Create a new Milvus collection for storing embeddings.

        Args:
            collection_name: Name of the collection
            description: Description of the collection
            drop_if_exists: Drop existing collection if it exists
            extra_fields: Additional scalar fields for metadata filtering

        Returns:
            Created Collection object
        """
        self.connect()

        # Check if collection exists
        if utility.has_collection(collection_name):
            if drop_if_exists:
                logger.warning(f"Dropping existing collection: {collection_name}")
                utility.drop_collection(collection_name)
            else:
                logger.info(f"Collection already exists: {collection_name}")
                collection = Collection(collection_name)
                self._collections[collection_name] = collection
                return collection

        logger.info(f"Creating collection: {collection_name}")

        # Define base schema
        fields = [
            FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=256),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.embedding_dim),
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
        ]
        
        # Add collection-specific scalar fields for filtering
        if collection_name == "pyegeria":
            logger.info("Adding PyEgeria-specific scalar fields for metadata filtering")
            fields.extend([
                FieldSchema(name="element_type", dtype=DataType.VARCHAR, max_length=50, default_value=""),
                FieldSchema(name="class_name", dtype=DataType.VARCHAR, max_length=200, default_value=""),
                FieldSchema(name="method_name", dtype=DataType.VARCHAR, max_length=200, default_value=""),
                FieldSchema(name="module_path", dtype=DataType.VARCHAR, max_length=500, default_value=""),
                FieldSchema(name="is_async", dtype=DataType.BOOL, default_value=False),
                FieldSchema(name="is_private", dtype=DataType.BOOL, default_value=False),
            ])
        elif collection_name == "cli_commands":
            logger.info("Adding CLI commands-specific scalar fields for metadata filtering")
            fields.extend([
                FieldSchema(name="main_command", dtype=DataType.VARCHAR, max_length=100, default_value=""),
                FieldSchema(name="subcommand", dtype=DataType.VARCHAR, max_length=200, default_value=""),
                FieldSchema(name="full_command", dtype=DataType.VARCHAR, max_length=500, default_value=""),
            ])
        elif extra_fields:
            logger.info(f"Adding {len(extra_fields)} custom scalar fields")
            fields.extend(extra_fields)
        
        # Always include JSON metadata for additional fields
        fields.append(FieldSchema(name="metadata", dtype=DataType.JSON))

        schema = CollectionSchema(
            fields=fields,
            description=description or f"Egeria Advisor - {collection_name}"
        )

        # Create collection
        collection = Collection(
            name=collection_name,
            schema=schema,
            using="default"
        )

        logger.info(f"✓ Created collection: {collection_name} with {len(fields)} fields")
        self._collections[collection_name] = collection

        return collection

    def create_index(
        self,
        collection_name: str,
        index_type: str = "IVF_FLAT",
        metric_type: str = "L2",
        params: Optional[Dict[str, Any]] = None
    ):
        """
        Create an index on the embedding field for fast similarity search.

        Args:
            collection_name: Name of the collection
            index_type: Type of index (IVF_FLAT, IVF_SQ8, HNSW, etc.)
            metric_type: Distance metric (L2, IP, COSINE)
            params: Index parameters
        """
        self.connect()

        collection = self.get_collection(collection_name)

        # Default parameters for different index types
        if params is None:
            if index_type == "IVF_FLAT":
                params = {"nlist": 1024}
            elif index_type == "HNSW":
                params = {"M": 16, "efConstruction": 256}
            else:
                params = {}

        logger.info(f"Creating {index_type} index on {collection_name}")

        index_params = {
            "index_type": index_type,
            "metric_type": metric_type,
            "params": params
        }

        collection.create_index(
            field_name="embedding",
            index_params=index_params
        )

        logger.info(f"✓ Created index on {collection_name}")

    def get_collection(self, collection_name: str) -> Collection:
        """Get a collection by name."""
        self.connect()

        # DISABLED: Collection caching to avoid stale query plans
        # if collection_name in self._collections:
        #     return self._collections[collection_name]

        if not utility.has_collection(collection_name):
            raise ValueError(f"Collection does not exist: {collection_name}")

        # Always create fresh Collection object
        collection = Collection(collection_name)
        # Don't cache it
        # self._collections[collection_name] = collection
        return collection

    def insert_data(
        self,
        collection_name: str,
        texts: List[str],
        ids: Optional[List[str]] = None,
        metadata: Optional[List[Dict[str, Any]]] = None,
        batch_size: int = 1000
    ) -> int:
        """
        Insert text data into a collection with automatic embedding generation.

        Args:
            collection_name: Name of the collection
            texts: List of texts to insert
            ids: Optional list of IDs (auto-generated if not provided)
            metadata: Optional list of metadata dicts
            batch_size: Batch size for insertion

        Returns:
            Number of entities inserted
        """
        self.connect()
        collection = self.get_collection(collection_name)

        # Generate IDs if not provided
        if ids is None:
            ids = [f"{collection_name}_{i}" for i in range(len(texts))]

        # Generate empty metadata if not provided
        if metadata is None:
            metadata = [{} for _ in range(len(texts))]

        if len(texts) != len(ids) or len(texts) != len(metadata):
            raise ValueError("texts, ids, and metadata must have the same length")

        logger.info(f"Inserting {len(texts)} entities into {collection_name}")

        # Generate embeddings
        logger.info("Generating embeddings...")
        embeddings = self.embedding_generator.encode_batch(
            texts,
            show_progress=True
        )

        # Get collection schema to determine which fields exist
        schema_fields = {field.name for field in collection.schema.fields}
        
        # Insert in batches
        total_inserted = 0
        for i in range(0, len(texts), batch_size):
            batch_end = min(i + batch_size, len(texts))

            # Base fields (always present)
            batch_data = [
                ids[i:batch_end],
                embeddings[i:batch_end].tolist(),
                texts[i:batch_end],
            ]
            
            # Extract scalar fields from metadata if they exist in schema
            if collection_name == "pyegeria" and "element_type" in schema_fields:
                # PyEgeria scalar fields
                batch_data.extend([
                    [m.get("element_type", "") for m in metadata[i:batch_end]],
                    [m.get("class_name", "") for m in metadata[i:batch_end]],
                    [m.get("method_name", "") for m in metadata[i:batch_end]],
                    [m.get("module_path", "") for m in metadata[i:batch_end]],
                    [m.get("is_async", False) for m in metadata[i:batch_end]],
                    [m.get("is_private", False) for m in metadata[i:batch_end]],
                ])
            elif collection_name == "cli_commands" and "main_command" in schema_fields:
                # CLI commands scalar fields
                batch_data.extend([
                    [m.get("main_command", "") for m in metadata[i:batch_end]],
                    [m.get("subcommand", "") for m in metadata[i:batch_end]],
                    [m.get("full_command", "") for m in metadata[i:batch_end]],
                ])
            
            # Always include full metadata as JSON
            batch_data.append(metadata[i:batch_end])

            collection.insert(batch_data)
            total_inserted += batch_end - i

            logger.debug(f"Inserted batch {i//batch_size + 1}: {batch_end - i} entities")

        # Flush to ensure data is persisted
        collection.flush()

        logger.info(f"✓ Inserted {total_inserted} entities into {collection_name}")
        return total_inserted

    def search(
        self,
        collection_name: str = "code_elements",
        query_text: Optional[str] = None,
        query_embedding: Optional[np.ndarray] = None,
        top_k: int = 5,
        filter_expr: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        output_fields: Optional[List[str]] = None
    ) -> List[SearchResult]:
        """
        Search for similar texts in a collection.

        Args:
            collection_name: Name of the collection
            query_text: Query text (will generate embedding)
            query_embedding: Pre-computed query embedding
            top_k: Number of results to return
            filter_expr: Optional filter expression
            filters: Optional metadata filters (dict)
            output_fields: Fields to include in results

        Returns:
            List of result dictionaries
        """
        if query_text is None and query_embedding is None:
            raise ValueError("Either query_text or query_embedding must be provided")

        self.connect()
        collection = self.get_collection(collection_name)

        # Release and reload collection to ensure fresh state
        try:
            collection.release()
        except:
            pass  # Collection might not be loaded yet
        collection.load()

        # Generate query embedding if text provided
        if query_embedding is None:
            query_embedding = self.embedding_generator.encode(query_text)

        # Convert to list of Python floats (Milvus requires native Python floats, not numpy.float64)
        # Handle both 1D and 2D arrays
        if hasattr(query_embedding, 'flatten'):
            # Flatten in case it's 2D, then convert each element to Python float
            flat_array = query_embedding.flatten()
            query_vector = [float(x) for x in flat_array]
        else:
            query_vector = [float(x) for x in query_embedding]

        # Default output fields
        if output_fields is None:
            output_fields = ["text", "metadata"]

        # Build filter expression from filters dict if provided
        if filters and not filter_expr:
            # Simple filter building - can be enhanced
            filter_parts = []
            for key, value in filters.items():
                if isinstance(value, str):
                    filter_parts.append(f'{key} == "{value}"')
                else:
                    filter_parts.append(f'{key} == {value}')
            filter_expr = " and ".join(filter_parts) if filter_parts else None

        # Search parameters
        # For IVF_FLAT with nlist=1024, use higher nprobe for better recall
        search_params = {
            "metric_type": "L2",
            "params": {"nprobe": 128}  # Search 128 out of 1024 clusters (~12.5%)
        }

        query_preview = query_text[:50] if query_text else "embedding"
        logger.debug(f"Searching {collection_name} for: {query_preview}...")
        logger.debug(f"Search params: limit={top_k}, nprobe={search_params['params']['nprobe']}, filter={filter_expr}")

        # Perform search
        results = collection.search(
            data=[query_vector],
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            expr=filter_expr,
            output_fields=output_fields
        )
        
        logger.debug(f"Milvus returned {len(results[0]) if results else 0} hits")

        # Parse results into SearchResult objects
        search_results = []
        for hits in results:
            for hit in hits:
                # Convert L2 distance to similarity score
                # L2 distance ranges from 0 (identical) to ~2.0 (very different) for normalized embeddings
                # Use exponential decay: score = exp(-distance)
                # This maps: distance=0 → score=1.0, distance=1.0 → score=0.37, distance=2.0 → score=0.14
                import math
                score = math.exp(-hit.distance)

                result = SearchResult(
                    id=hit.id,
                    score=score,
                    text=hit.entity.get("text", ""),
                    metadata=hit.entity.get("metadata", {})
                )
                search_results.append(result)

        logger.debug(f"Found {len(search_results)} results")
        return search_results

    def get_collection_stats(self, collection_name: str) -> Dict[str, Any]:
        """Get statistics about a collection."""
        self.connect()
        collection = self.get_collection(collection_name)

        stats = {
            "name": collection_name,
            "num_entities": collection.num_entities,
            "schema": {
                "description": collection.schema.description,
                "fields": [
                    {
                        "name": field.name,
                        "type": str(field.dtype),
                        "is_primary": field.is_primary
                    }
                    for field in collection.schema.fields
                ]
            }
        }

        return stats

    def list_collections(self) -> List[str]:
        """List all collections in the database."""
        self.connect()
        return utility.list_collections()

    def delete_collection(self, collection_name: str):
        """Delete a collection."""
        self.connect()

        if collection_name in self._collections:
            del self._collections[collection_name]

        if utility.has_collection(collection_name):
            utility.drop_collection(collection_name)
            logger.info(f"Deleted collection: {collection_name}")
        else:
            logger.warning(f"Collection does not exist: {collection_name}")


# Global instance - DISABLED to avoid caching issues
_vector_store: Optional[VectorStoreManager] = None


def get_vector_store() -> VectorStoreManager:
    """Get or create the global vector store manager instance."""
    # Always create a fresh instance to avoid caching issues
    # TODO: Re-enable singleton after resolving Milvus caching
    return VectorStoreManager()
