"""Configuration management for Egeria Advisor."""
import os
from pathlib import Path
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import yaml
from loguru import logger


class DataSourceConfig(BaseModel):
    """Data source configuration."""
    egeria_python_path: Path
    include_patterns: list[str] = ["*.py", "*.md"]
    exclude_patterns: list[str] = ["**/__pycache__/**", "**/deprecated/**"]


class VectorStoreConfig(BaseModel):
    """Vector store configuration."""
    host: str = "localhost"
    port: int = 19530
    collections: list[str] = ["code_elements", "examples", "documentation"]


class LLMModelConfig(BaseModel):
    """LLM model configuration."""
    query: str = "llama3.1:8b"
    code: str = "codellama:13b"
    conversation: str = "llama3.1:8b"
    maintenance: str = "codellama:13b"


class LLMParametersConfig(BaseModel):
    """LLM parameters configuration."""
    temperature: float = 0.7
    max_tokens: int = 2000
    top_p: float = 0.9
    top_k: int = 40
    repeat_penalty: float = 1.1
    timeout: int = 60


class LLMConfig(BaseModel):
    """LLM configuration for Ollama."""
    provider: str = "ollama"
    base_url: str = "http://localhost:11434"
    models: LLMModelConfig = Field(default_factory=LLMModelConfig)
    parameters: LLMParametersConfig = Field(default_factory=LLMParametersConfig)
    model_overrides: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class EmbeddingConfig(BaseModel):
    """Embedding model configuration."""
    model: str = "sentence-transformers/all-MiniLM-L6-v2"
    device: str = "cpu"
    batch_size: int = 32
    normalize: bool = True
    max_length: int = 512


class RAGRetrievalConfig(BaseModel):
    """RAG retrieval configuration."""
    top_k: int = 5
    min_score: float = 0.7
    rerank: bool = False


class RAGContextConfig(BaseModel):
    """RAG context configuration."""
    max_length: int = 4000
    format_style: str = "detailed"
    include_metadata: bool = True


class RAGGenerationConfig(BaseModel):
    """RAG generation configuration."""
    temperature: float = 0.7
    max_tokens: int = 2000
    stream: bool = False


class RAGConfig(BaseModel):
    """RAG system configuration."""
    chunk_size: int = 512
    chunk_overlap: int = 50
    retrieval: RAGRetrievalConfig = Field(default_factory=RAGRetrievalConfig)
    context: RAGContextConfig = Field(default_factory=RAGContextConfig)
    generation: RAGGenerationConfig = Field(default_factory=RAGGenerationConfig)


class AgentConfig(BaseModel):
    """Individual agent configuration."""
    enabled: bool = True
    model: str
    temperature: float
    max_iterations: int = 5
    memory_window: Optional[int] = None


class AgentsConfig(BaseModel):
    """All agents configuration."""
    query_agent: AgentConfig = Field(
        default_factory=lambda: AgentConfig(
            model="llama3.1:8b",
            temperature=0.3,
            max_iterations=3
        )
    )
    code_agent: AgentConfig = Field(
        default_factory=lambda: AgentConfig(
            model="codellama:13b",
            temperature=0.5,
            max_iterations=5
        )
    )
    conversation_agent: AgentConfig = Field(
        default_factory=lambda: AgentConfig(
            model="llama3.1:8b",
            temperature=0.7,
            max_iterations=10,
            memory_window=10
        )
    )
    maintenance_agent: AgentConfig = Field(
        default_factory=lambda: AgentConfig(
            model="codellama:13b",
            temperature=0.4,
            max_iterations=5
        )
    )


class CLIConfig(BaseModel):
    """CLI configuration."""
    default_agent: str = "auto"
    interactive_mode: bool = True
    output_format: str = "rich"
    show_citations: bool = True
    show_confidence: bool = True
    max_response_length: int = 5000


class MLflowConfig(BaseModel):
    """MLflow configuration."""
    enabled: bool = True
    tracking_uri: str = "http://localhost:5000"
    experiment_name: str = "egeria-advisor"
    log_system_metrics: bool = True
    log_query_metrics: bool = True
    auto_log: bool = True


class PhoenixConfig(BaseModel):
    """Phoenix Arize configuration."""
    enabled: bool = False
    collector_endpoint: str = "http://localhost:6006"
    trace_all_queries: bool = False


class ObservabilityConfig(BaseModel):
    """Observability configuration."""
    mlflow: MLflowConfig = Field(default_factory=MLflowConfig)
    phoenix: PhoenixConfig = Field(default_factory=PhoenixConfig)


class LoggingConfig(BaseModel):
    """Logging configuration."""
    level: str = "INFO"
    format: str = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )
    file: str = "logs/advisor.log"
    rotation: str = "10 MB"
    retention: str = "1 week"


class AdvisorSettings(BaseSettings):
    """Main settings loaded from environment and config file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Milvus
    milvus_host: str = Field(default="localhost", alias="MILVUS_HOST")
    milvus_port: int = Field(default=19530, alias="MILVUS_PORT")
    milvus_user: str = Field(default="", alias="MILVUS_USER")
    milvus_password: str = Field(default="", alias="MILVUS_PASSWORD")

    # Egeria
    egeria_platform_url: str = Field(
        default="https://localhost:9443",
        alias="EGERIA_PLATFORM_URL"
    )
    egeria_view_server: str = Field(default="view-server", alias="EGERIA_VIEW_SERVER")
    egeria_user: str = Field(default="garygeeke", alias="EGERIA_USER")
    egeria_password: str = Field(default="secret", alias="EGERIA_PASSWORD")

    # Ollama
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        alias="OLLAMA_BASE_URL"
    )
    ollama_model: str = Field(default="llama3.1:8b", alias="OLLAMA_MODEL")
    ollama_code_model: str = Field(default="codellama:13b", alias="OLLAMA_CODE_MODEL")
    ollama_temperature: float = Field(default=0.7, alias="OLLAMA_TEMPERATURE")

    # Embeddings
    embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        alias="EMBEDDING_MODEL"
    )
    embedding_device: str = Field(default="cpu", alias="EMBEDDING_DEVICE")

    # MLflow
    mlflow_tracking_uri: str = Field(
        default="http://localhost:5000",
        alias="MLFLOW_TRACKING_URI"
    )
    mlflow_experiment_name: str = Field(
        default="egeria-advisor",
        alias="MLFLOW_EXPERIMENT_NAME"
    )
    mlflow_enable_tracking: bool = Field(default=True, alias="MLFLOW_ENABLE_TRACKING")

    # Phoenix
    phoenix_enable: bool = Field(default=False, alias="PHOENIX_ENABLE")
    phoenix_collector_endpoint: str = Field(
        default="http://localhost:6006",
        alias="PHOENIX_COLLECTOR_ENDPOINT"
    )

    # Advisor
    advisor_data_path: Path = Field(alias="ADVISOR_DATA_PATH")
    advisor_cache_dir: Path = Field(
        default=Path("./data/cache"),
        alias="ADVISOR_CACHE_DIR"
    )
    advisor_log_level: str = Field(default="INFO", alias="ADVISOR_LOG_LEVEL")


def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load configuration from YAML file.

    Parameters
    ----------
    config_path : Path, optional
        Path to configuration file. If None, uses default location.

    Returns
    -------
    dict
        Configuration dictionary
    """
    if config_path is None:
        config_path = Path("config/advisor.yaml")

    if not config_path.exists():
        logger.warning(f"Config file not found: {config_path}, using defaults")
        return {}

    with open(config_path) as f:
        config = yaml.safe_load(f)

    logger.info(f"Loaded configuration from {config_path}")
    return config


def get_full_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Get full configuration including all nested configs.

    Parameters
    ----------
    config_path : Path, optional
        Path to configuration file

    Returns
    -------
    dict
        Full configuration with all sections
    """
    config = load_config(config_path)

    # Parse nested configurations
    full_config = {
        "data_sources": DataSourceConfig(**config.get("data_sources", {})),
        "vector_store": VectorStoreConfig(**config.get("vector_store", {})),
        "llm": LLMConfig(**config.get("llm", {})),
        "embeddings": EmbeddingConfig(**config.get("embeddings", {})),
        "rag": RAGConfig(**config.get("rag", {})),
        "agents": AgentsConfig(**config.get("agents", {})),
        "cli": CLIConfig(**config.get("cli", {})),
        "observability": ObservabilityConfig(**config.get("observability", {})),
        "logging": LoggingConfig(**config.get("logging", {})),
    }

    return full_config


# Global settings instance
try:
    settings = AdvisorSettings()
    logger.info("Settings loaded successfully")
except Exception as e:
    logger.warning(f"Could not load settings from environment: {e}")
    logger.info("Using default settings")
    # Create settings with defaults
    settings = AdvisorSettings(
        advisor_data_path=Path("/Users/dwolfson/localGit/egeria-v6/egeria-python")
    )


__all__ = [
    "settings",
    "load_config",
    "get_full_config",
    "DataSourceConfig",
    "VectorStoreConfig",
    "LLMConfig",
    "EmbeddingConfig",
    "RAGConfig",
    "RAGRetrievalConfig",
    "RAGContextConfig",
    "RAGGenerationConfig",
    "AgentsConfig",
    "CLIConfig",
    "ObservabilityConfig",
    "LoggingConfig",
]
