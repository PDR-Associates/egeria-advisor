"""
Milvus vector store backend for Egeria Advisor.
"""

import math
import re
from typing import List, Dict, Any, Optional

import numpy as np
from loguru import logger
from pymilvus import (
    connections,
    Collection,
    CollectionSchema,
    FieldSchema,
    DataType,
    utility,
)

from advisor.config import settings
from advisor.embeddings import get_embedding_generator
from advisor.vector_store_base import BaseVectorStore, SearchResult


class MilvusVectorStore(BaseVectorStore):
    """Milvus implementation of BaseVectorStore."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.host = host or settings.milvus_host
        self.port = port or settings.milvus_port
        self.user = user or (settings.milvus_user if hasattr(settings, "milvus_user") else None)
        self.password = password or (settings.milvus_password if hasattr(settings, "milvus_password") else None)

        self.embedding_generator = get_embedding_generator()
        self.embedding_dim = self.embedding_generator.get_embedding_dim()

        self._connected = False
        self._collections: Dict[str, Collection] = {}

        logger.info(f"Initialized MilvusVectorStore for {self.host}:{self.port}")

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> None:
        if self._connected:
            return

        try:
            logger.info(f"Connecting to Milvus at {self.host}:{self.port}")
            conn_params: Dict[str, Any] = {"host": self.host, "port": str(self.port)}
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

    def disconnect(self) -> None:
        if self._connected:
            connections.disconnect("default")
            self._connected = False
            self._collections.clear()
            logger.info("Disconnected from Milvus")

    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------

    def create_collection(
        self,
        collection_name: str,
        description: str = "",
        drop_if_exists: bool = False,
        extra_fields: Optional[List[FieldSchema]] = None,
    ) -> Collection:
        self.connect()

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

        fields = [
            FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=256),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.embedding_dim),
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
        ]

        if collection_name == "pyegeria":
            fields.extend([
                FieldSchema(name="element_type", dtype=DataType.VARCHAR, max_length=50, default_value=""),
                FieldSchema(name="class_name", dtype=DataType.VARCHAR, max_length=200, default_value=""),
                FieldSchema(name="method_name", dtype=DataType.VARCHAR, max_length=200, default_value=""),
                FieldSchema(name="module_path", dtype=DataType.VARCHAR, max_length=500, default_value=""),
                FieldSchema(name="is_async", dtype=DataType.BOOL, default_value=False),
                FieldSchema(name="is_private", dtype=DataType.BOOL, default_value=False),
            ])
        elif collection_name in ("pyegeria_cli", "cli_commands"):
            fields.extend([
                FieldSchema(name="main_command", dtype=DataType.VARCHAR, max_length=100, default_value=""),
                FieldSchema(name="subcommand", dtype=DataType.VARCHAR, max_length=200, default_value=""),
                FieldSchema(name="full_command", dtype=DataType.VARCHAR, max_length=500, default_value=""),
            ])
        elif extra_fields:
            fields.extend(extra_fields)

        fields.append(FieldSchema(name="metadata", dtype=DataType.JSON))

        schema = CollectionSchema(
            fields=fields,
            description=description or f"Egeria Advisor - {collection_name}",
        )
        collection = Collection(name=collection_name, schema=schema, using="default")
        logger.info(f"✓ Created collection: {collection_name} with {len(fields)} fields")
        self._collections[collection_name] = collection
        return collection

    def create_index(
        self,
        collection_name: str,
        index_type: str = "IVF_FLAT",
        metric_type: str = "L2",
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.connect()
        collection = self.get_collection(collection_name)

        if params is None:
            if index_type == "IVF_FLAT":
                params = {"nlist": 1024}
            elif index_type == "HNSW":
                params = {"M": 16, "efConstruction": 256}
            else:
                params = {}

        logger.info(f"Creating {index_type} index on {collection_name}")
        collection.create_index(
            field_name="embedding",
            index_params={"index_type": index_type, "metric_type": metric_type, "params": params},
        )
        logger.info(f"✓ Created index on {collection_name}")

    def get_collection(self, collection_name: str) -> Collection:
        self.connect()
        if not utility.has_collection(collection_name):
            raise ValueError(f"Collection does not exist: {collection_name}")
        return Collection(collection_name)

    # ------------------------------------------------------------------
    # Data insertion
    # ------------------------------------------------------------------

    def insert_data(
        self,
        collection_name: str,
        texts: List[str],
        ids: Optional[List[str]] = None,
        metadata: Optional[List[Dict[str, Any]]] = None,
        batch_size: int = 1000,
    ) -> int:
        self.connect()
        collection = self.get_collection(collection_name)

        if ids is None:
            ids = [f"{collection_name}_{i}" for i in range(len(texts))]
        if metadata is None:
            metadata = [{} for _ in range(len(texts))]

        if len(texts) != len(ids) or len(texts) != len(metadata):
            raise ValueError("texts, ids, and metadata must have the same length")

        logger.info(f"Inserting {len(texts)} entities into {collection_name}")
        embeddings = self.embedding_generator.encode_batch(texts, show_progress=True)

        schema_fields = {field.name for field in collection.schema.fields}
        total_inserted = 0

        for i in range(0, len(texts), batch_size):
            end = min(i + batch_size, len(texts))
            batch_data = [
                ids[i:end],
                embeddings[i:end].tolist(),
                texts[i:end],
            ]

            if collection_name == "pyegeria" and "element_type" in schema_fields:
                batch_data.extend([
                    [m.get("element_type", "") for m in metadata[i:end]],
                    [m.get("class_name", "") for m in metadata[i:end]],
                    [m.get("method_name", "") for m in metadata[i:end]],
                    [m.get("module_path", "") for m in metadata[i:end]],
                    [m.get("is_async", False) for m in metadata[i:end]],
                    [m.get("is_private", False) for m in metadata[i:end]],
                ])
            elif collection_name in ("pyegeria_cli", "cli_commands") and "main_command" in schema_fields:
                batch_data.extend([
                    [m.get("main_command", "") for m in metadata[i:end]],
                    [m.get("subcommand", "") for m in metadata[i:end]],
                    [m.get("full_command", "") for m in metadata[i:end]],
                ])

            batch_data.append(metadata[i:end])
            collection.insert(batch_data)
            total_inserted += end - i
            logger.debug(f"Inserted batch {i // batch_size + 1}: {end - i} entities")

        collection.flush()
        logger.info(f"✓ Inserted {total_inserted} entities into {collection_name}")
        return total_inserted

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        collection_name: str = "code_elements",
        query_text: Optional[str] = None,
        query_embedding: Optional[np.ndarray] = None,
        top_k: int = 5,
        filter_expr: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        output_fields: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        if query_text is None and query_embedding is None:
            raise ValueError("Either query_text or query_embedding must be provided")

        self.connect()
        collection = self.get_collection(collection_name)

        try:
            collection.release()
        except Exception:
            pass
        collection.load()

        if query_embedding is None:
            query_embedding = self.embedding_generator.encode(query_text)

        if hasattr(query_embedding, "flatten"):
            query_vector = [float(x) for x in query_embedding.flatten()]
        else:
            query_vector = [float(x) for x in query_embedding]

        if output_fields is None:
            output_fields = ["text", "metadata"]

        if filters and not filter_expr:
            parts = []
            for key, value in filters.items():
                if isinstance(value, str):
                    parts.append(f'{key} == "{value}"')
                else:
                    parts.append(f"{key} == {value}")
            filter_expr = " and ".join(parts) if parts else None

        search_params = {"metric_type": "L2", "params": {"nprobe": 128}}

        logger.debug(f"Searching {collection_name}: limit={top_k}, filter={filter_expr}")

        results = collection.search(
            data=[query_vector],
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            expr=filter_expr,
            output_fields=output_fields,
        )

        search_results = []
        for hits in results:
            for hit in hits:
                score = math.exp(-hit.distance)
                search_results.append(SearchResult(
                    id=hit.id,
                    score=score,
                    text=hit.entity.get("text", ""),
                    metadata=hit.entity.get("metadata", {}),
                ))

        logger.debug(f"Found {len(search_results)} results in {collection_name}")
        return search_results

    # ------------------------------------------------------------------
    # Filter-only query (no vector search)
    # ------------------------------------------------------------------

    def query_by_filter(
        self,
        collection_name: str,
        filter_expr: str,
        output_fields: List[str],
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """Retrieve rows matching a scalar filter without a vector search."""
        self.connect()
        collection = self.get_collection(collection_name)
        try:
            collection.release()
        except Exception:
            pass
        collection.load()

        results = collection.query(
            expr=filter_expr,
            output_fields=output_fields,
            limit=limit,
        )
        return results  # already a list of dicts from pymilvus

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_entities(self, collection_name: str, ids: List[str]) -> int:
        """Delete entities by ID. Returns number of deleted entities."""
        if not ids:
            return 0

        self.connect()
        collection = self.get_collection(collection_name)

        # Milvus delete expression: id in ["a", "b", ...]
        id_list = ", ".join(f'"{id_}"' for id_ in ids)
        expr = f"id in [{id_list}]"

        collection.delete(expr)
        collection.flush()
        logger.info(f"Deleted {len(ids)} entities from {collection_name}")
        return len(ids)

    # ------------------------------------------------------------------
    # Stats / admin
    # ------------------------------------------------------------------

    def get_collection_stats(self, collection_name: str) -> Dict[str, Any]:
        self.connect()
        collection = self.get_collection(collection_name)
        return {
            "name": collection_name,
            "num_entities": collection.num_entities,
            "schema": {
                "description": collection.schema.description,
                "fields": [
                    {
                        "name": field.name,
                        "type": str(field.dtype),
                        "is_primary": field.is_primary,
                    }
                    for field in collection.schema.fields
                ],
            },
        }

    def list_collections(self) -> List[str]:
        self.connect()
        return utility.list_collections()

    def delete_collection(self, collection_name: str) -> None:
        self.connect()
        self._collections.pop(collection_name, None)
        if utility.has_collection(collection_name):
            utility.drop_collection(collection_name)
            logger.info(f"Deleted collection: {collection_name}")
        else:
            logger.warning(f"Collection does not exist: {collection_name}")


# ---------------------------------------------------------------------------
# Backwards-compatibility alias — all existing imports stay unchanged
# ---------------------------------------------------------------------------
VectorStoreManager = MilvusVectorStore


def get_vector_store() -> BaseVectorStore:
    """
    Factory: return the active vector store backend.

    Checks config/advisor.yaml first (vector_store_backend key), then falls
    back to the VECTOR_STORE_BACKEND environment variable, then defaults to
    'milvus' so existing deployments are unaffected until the YAML is changed.
    """
    from advisor.config import load_config
    cfg = load_config()
    backend = cfg.get(
        "vector_store_backend",
        getattr(settings, "vector_store_backend", "milvus"),
    ).lower()

    if backend == "pgvector":
        from advisor.vector_store_pg import PgVectorStore
        pg_cfg = cfg.get("pgvector", {})
        return PgVectorStore(
            host=pg_cfg.get("host", settings.pgvector_host),
            port=int(pg_cfg.get("port", settings.pgvector_port)),
            dbname=pg_cfg.get("dbname", settings.pgvector_dbname),
            user=pg_cfg.get("user", settings.pgvector_user),
            password=pg_cfg.get("password", settings.pgvector_password),
            max_connections=int(pg_cfg.get("max_connections", settings.pgvector_max_connections)),
            ef_search=int(pg_cfg.get("ef_search", settings.pgvector_ef_search)),
        )

    return MilvusVectorStore()
