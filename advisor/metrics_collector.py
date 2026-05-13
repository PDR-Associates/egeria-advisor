"""
Metrics collection framework for monitoring system performance.

Collects and stores metrics about queries, collections, and system resources.
"""

import sqlite3
import time
import psutil
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from contextlib import contextmanager
from loguru import logger

from advisor.config import get_full_config


@dataclass
class QueryMetric:
    """Metrics for a single query."""
    timestamp: float
    query_text: str
    collection_name: Optional[str]
    latency_ms: float
    cache_hit: bool
    success: bool
    query_type: Optional[str] = None
    error_message: Optional[str] = None
    result_count: Optional[int] = None
    embedding_time_ms: Optional[float] = None
    search_time_ms: Optional[float] = None
    llm_time_ms: Optional[float] = None
    avg_relevance_score: Optional[float] = None
    sources_json: Optional[str] = None  # JSON string of source metadata


@dataclass
class CollectionHealth:
    """Health metrics for a collection."""
    collection_name: str
    last_check: float
    entity_count: int
    health_score: float
    storage_size_mb: float
    last_update: float
    status: str  # 'healthy', 'degraded', 'critical'


@dataclass
class SystemMetric:
    """System resource metrics."""
    timestamp: float
    cpu_percent: float
    memory_percent: float
    gpu_percent: Optional[float]
    disk_io_read_mb: float
    disk_io_write_mb: float
    network_sent_mb: float
    network_recv_mb: float


class MetricsCollector:
    """
    Collect and store system metrics.
    
    Provides methods to record query metrics, collection health,
    and system resource usage.
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize metrics collector.
        
        Args:
            db_path: Path to SQLite database for metrics storage
        """
        if db_path is None:
            config = get_full_config()
            data_dir = Path(config.get("data_dir", "data"))
            db_path = data_dir / "metrics.db"
        
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
        
        # Track disk I/O baseline
        self._disk_io_baseline = psutil.disk_io_counters()
        self._network_baseline = psutil.net_io_counters()
        
        logger.info(f"Initialized MetricsCollector with database: {db_path}")
    
    def _init_database(self):
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            # Query metrics table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS query_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    query_text TEXT NOT NULL,
                    collection_name TEXT,
                    latency_ms REAL NOT NULL,
                    query_type TEXT,
                    cache_hit BOOLEAN NOT NULL,
                    success BOOLEAN NOT NULL,
                    error_message TEXT,
                    result_count INTEGER,
                    embedding_time_ms REAL,
                    search_time_ms REAL,
                    llm_time_ms REAL,
                    avg_relevance_score REAL,
                    sources_json TEXT
                )
            """)
            
            # Collection health table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS collection_health (
                    collection_name TEXT PRIMARY KEY,
                    last_check REAL NOT NULL,
                    entity_count INTEGER NOT NULL,
                    health_score REAL NOT NULL,
                    storage_size_mb REAL NOT NULL,
                    last_update REAL NOT NULL,
                    status TEXT NOT NULL
                )
            """)
            
            # System metrics table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS system_metrics (
                    timestamp REAL PRIMARY KEY,
                    cpu_percent REAL NOT NULL,
                    memory_percent REAL NOT NULL,
                    gpu_percent REAL,
                    disk_io_read_mb REAL NOT NULL,
                    disk_io_write_mb REAL NOT NULL,
                    network_sent_mb REAL NOT NULL,
                    network_recv_mb REAL NOT NULL
                )
            """)
            
            # Error log table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS error_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    error_type TEXT NOT NULL,
                    error_message TEXT NOT NULL,
                    stack_trace TEXT,
                    context TEXT
                )
            """)
            
            # Create indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_query_timestamp ON query_metrics(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_query_collection ON query_metrics(collection_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_system_timestamp ON system_metrics(timestamp)")
            
            conn.commit()
    
    def record_query(self, metric: QueryMetric):
        """
        Record a query metric.
        
        Args:
            metric: QueryMetric instance
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO query_metrics
                (timestamp, query_text, collection_name, latency_ms, query_type,
                 cache_hit, success, error_message, result_count, embedding_time_ms,
                 search_time_ms, llm_time_ms, avg_relevance_score, sources_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                metric.timestamp,
                metric.query_text,
                metric.collection_name,
                metric.latency_ms,
                metric.query_type,
                metric.cache_hit,
                metric.success,
                metric.error_message,
                metric.result_count,
                metric.embedding_time_ms,
                metric.search_time_ms,
                metric.llm_time_ms,
                metric.avg_relevance_score,
                metric.sources_json
            ))
            conn.commit()
    
    def record_collection_health(self, health: CollectionHealth):
        """
        Record collection health metrics.
        
        Args:
            health: CollectionHealth instance
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO collection_health
                (collection_name, last_check, entity_count, health_score,
                 storage_size_mb, last_update, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                health.collection_name,
                health.last_check,
                health.entity_count,
                health.health_score,
                health.storage_size_mb,
                health.last_update,
                health.status
            ))
            conn.commit()
    
    def record_system_metrics(self):
        """Record current system resource metrics."""
        metric = self.collect_system_metrics()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO system_metrics
                (timestamp, cpu_percent, memory_percent, gpu_percent,
                 disk_io_read_mb, disk_io_write_mb, network_sent_mb, network_recv_mb)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                metric.timestamp,
                metric.cpu_percent,
                metric.memory_percent,
                metric.gpu_percent,
                metric.disk_io_read_mb,
                metric.disk_io_write_mb,
                metric.network_sent_mb,
                metric.network_recv_mb
            ))
            conn.commit()
    
    def collect_system_metrics(self) -> SystemMetric:
        """
        Collect current system resource metrics.
        
        Returns:
            SystemMetric instance
        """
        # CPU and memory
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        
        # GPU (if available)
        gpu_percent = None
        try:
            import torch
            if torch.cuda.is_available():
                gpu_percent = torch.cuda.utilization()
            elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                # On macOS, getting exact MPS utilization is hard without powermetrics
                # We'll use 0.0 to indicate it's available/being used (but percentage unknown)
                gpu_percent = 0.0
        except:
            pass
        
        # Disk I/O
        disk_io = psutil.disk_io_counters()
        disk_read_mb = (disk_io.read_bytes - self._disk_io_baseline.read_bytes) / (1024 * 1024)
        disk_write_mb = (disk_io.write_bytes - self._disk_io_baseline.write_bytes) / (1024 * 1024)
        
        # Network I/O
        net_io = psutil.net_io_counters()
        net_sent_mb = (net_io.bytes_sent - self._network_baseline.bytes_sent) / (1024 * 1024)
        net_recv_mb = (net_io.bytes_recv - self._network_baseline.bytes_recv) / (1024 * 1024)
        
        return SystemMetric(
            timestamp=time.time(),
            cpu_percent=cpu_percent,
            memory_percent=memory.percent,
            gpu_percent=gpu_percent,
            disk_io_read_mb=disk_read_mb,
            disk_io_write_mb=disk_write_mb,
            network_sent_mb=net_sent_mb,
            network_recv_mb=net_recv_mb
        )
    
    def record_error(self, error_type: str, error_message: str, 
                    stack_trace: Optional[str] = None, context: Optional[str] = None):
        """
        Record an error.
        
        Args:
            error_type: Type of error
            error_message: Error message
            stack_trace: Optional stack trace
            context: Optional context information
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO error_log
                (timestamp, error_type, error_message, stack_trace, context)
                VALUES (?, ?, ?, ?, ?)
            """, (time.time(), error_type, error_message, stack_trace, context))
            conn.commit()
    
    def get_recent_queries(self, limit: int = 100) -> List[Dict]:
        """
        Get recent query metrics.
        
        Args:
            limit: Maximum number of queries to return
            
        Returns:
            List of query metric dicts
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM query_metrics
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_collection_health(self, collection_name: Optional[str] = None) -> List[Dict]:
        """
        Get collection health metrics.
        
        Args:
            collection_name: Optional collection name filter
            
        Returns:
            List of collection health dicts
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if collection_name:
                cursor = conn.execute(
                    "SELECT * FROM collection_health WHERE collection_name = ?",
                    (collection_name,)
                )
            else:
                cursor = conn.execute("SELECT * FROM collection_health")
            return [dict(row) for row in cursor.fetchall()]
    
    def get_query_stats(self, hours: int = 24) -> Dict[str, Any]:
        """
        Get aggregated query statistics.
        
        Args:
            hours: Number of hours to look back
            
        Returns:
            Dict with statistics
        """
        cutoff = time.time() - (hours * 3600)
        
        with sqlite3.connect(self.db_path) as conn:
            # Total queries
            cursor = conn.execute(
                "SELECT COUNT(*) FROM query_metrics WHERE timestamp > ?",
                (cutoff,)
            )
            total_queries = cursor.fetchone()[0]
            
            # Success rate
            cursor = conn.execute(
                "SELECT COUNT(*) FROM query_metrics WHERE timestamp > ? AND success = 1",
                (cutoff,)
            )
            successful_queries = cursor.fetchone()[0]
            success_rate = successful_queries / total_queries if total_queries > 0 else 0
            
            # Cache hit rate
            cursor = conn.execute(
                "SELECT COUNT(*) FROM query_metrics WHERE timestamp > ? AND cache_hit = 1",
                (cutoff,)
            )
            cache_hits = cursor.fetchone()[0]
            cache_hit_rate = cache_hits / total_queries if total_queries > 0 else 0
            
            # Average latency
            cursor = conn.execute(
                "SELECT AVG(latency_ms) FROM query_metrics WHERE timestamp > ? AND success = 1",
                (cutoff,)
            )
            avg_latency = cursor.fetchone()[0] or 0
            
            # Percentiles
            cursor = conn.execute("""
                SELECT latency_ms FROM query_metrics 
                WHERE timestamp > ? AND success = 1
                ORDER BY latency_ms
            """, (cutoff,))
            latencies = [row[0] for row in cursor.fetchall()]
            
            p50 = latencies[len(latencies) // 2] if latencies else 0
            p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0
            p99 = latencies[int(len(latencies) * 0.99)] if latencies else 0
            
            return {
                "total_queries": total_queries,
                "successful_queries": successful_queries,
                "success_rate": success_rate,
                "cache_hits": cache_hits,
                "cache_hit_rate": cache_hit_rate,
                "avg_latency_ms": avg_latency,
                "p50_latency_ms": p50,
                "p95_latency_ms": p95,
                "p99_latency_ms": p99
            }
    
    def cleanup_old_metrics(self, days: int = 30):
        """
        Remove metrics older than specified days.
        
        Args:
            days: Number of days to retain
        """
        cutoff = time.time() - (days * 86400)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM query_metrics WHERE timestamp < ?", (cutoff,))
            conn.execute("DELETE FROM system_metrics WHERE timestamp < ?", (cutoff,))
            conn.execute("DELETE FROM error_log WHERE timestamp < ?", (cutoff,))
            conn.commit()
        
        logger.info(f"Cleaned up metrics older than {days} days")


@contextmanager
def track_query(collector: MetricsCollector, query_text: str, 
                collection_name: Optional[str] = None):
    """
    Context manager to track query metrics.
    
    Usage:
        with track_query(collector, "What is Egeria?") as tracker:
            result = perform_query()
            tracker.set_result(result)
    
    Args:
        collector: MetricsCollector instance
        query_text: Query text
        collection_name: Optional collection name
    """
    class QueryTracker:
        def __init__(self):
            self.start_time = time.time()
            self.cache_hit = False
            self.success = True
            self.error_message = None
            self.query_type = None
            self.result_count = None
            self.embedding_time_ms = None
            self.search_time_ms = None
            self.llm_time_ms = None
        
        def set_cache_hit(self, hit: bool):
            self.cache_hit = hit
        
        def set_result(self, result):
            if hasattr(result, '__len__'):
                self.result_count = len(result)
        
        def set_error(self, error: Exception):
            self.success = False
            self.error_message = str(error)
        
        def set_timing(self, embedding_ms=None, search_ms=None, llm_ms=None):
            if embedding_ms is not None:
                self.embedding_time_ms = embedding_ms
            if search_ms is not None:
                self.search_time_ms = search_ms
            if llm_ms is not None:
                self.llm_time_ms = llm_ms
    
    tracker = QueryTracker()
    
    try:
        yield tracker
    except Exception as e:
        tracker.set_error(e)
        raise
    finally:
        latency_ms = (time.time() - tracker.start_time) * 1000
        
        metric = QueryMetric(
            timestamp=time.time(),
            query_text=query_text,
            collection_name=collection_name,
            latency_ms=latency_ms,
            query_type=tracker.query_type,
            cache_hit=tracker.cache_hit,
            success=tracker.success,
            error_message=tracker.error_message,
            result_count=tracker.result_count,
            embedding_time_ms=tracker.embedding_time_ms,
            search_time_ms=tracker.search_time_ms,
            llm_time_ms=tracker.llm_time_ms
        )
        
        collector.record_query(metric)


# Global metrics collector instance
_metrics_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """Get or create global metrics collector instance."""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


def sync_collection_health(retriever, collector):
    """
    Sync entity counts and health status for all enabled collections.
    
    Parameters
    ----------
    retriever : RAGRetriever or similar
        Object with access to vector_store
    collector : MetricsCollector
        Collector instance for recording health
    """
    try:
        from advisor.collection_config import get_enabled_collections
        from advisor.metrics_collector import CollectionHealth
        
        for collection in get_enabled_collections():
            try:
                # Use retriever's vector store to get actual count
                stats = retriever.vector_store.get_collection_stats(collection.name)
                count = stats.get("num_entities", 0)
                
                # Record health
                health = CollectionHealth(
                    collection_name=collection.name,
                    last_check=time.time(),
                    entity_count=count,
                    health_score=1.0 if count > 0 else 0.0,
                    storage_size_mb=0.0,  # Could be estimated if needed
                    last_update=time.time(),
                    status='healthy' if count > 0 else 'empty'
                )
                collector.record_collection_health(health)
            except Exception as e:
                # Only log as debug to avoid noise if Milvus isn't fully ready
                logger.debug(f"Could not get stats for collection {collection.name}: {e}")
                
        logger.debug("Successfully synced collection health metrics")
    except Exception as e:
        logger.warning(f"Failed to sync collection health: {e}")