"""
Query Agent using BeeAI Framework.
"""

from typing import Dict, Any, Optional
from loguru import logger
import time

from beeai_framework.agents.react.agent import ReActAgent
from beeai_framework.memory import UnconstrainedMemory
from advisor.agents.backend import BeeAIBackend
from advisor.tools.rag_tool import RAGTool
from advisor.mlflow_tracking import get_mlflow_tracker
from advisor.metrics_collector import get_metrics_collector, QueryMetric


class QueryAgent:
    """
    Agent specialized in answering general queries using BeeAI ReAct.
    """

    def __init__(self):
        """Initialize Query Agent."""
        self.name = "query"
        self.model = BeeAIBackend.get_chat_model("llama3.1:8b")
        self.memory = UnconstrainedMemory()
        self.tools = [RAGTool()]

        self.agent = ReActAgent(
            llm=self.model,
            tools=self.tools,
            memory=self.memory
        )
        
        # Initialize monitoring
        self.mlflow_tracker = get_mlflow_tracker()
        self.metrics_collector = get_metrics_collector()

    async def process(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Process a query using the BeeAI agent.

        Args:
            query: User's question
            context: Optional context information

        Returns:
            Response dictionary
        """
        logger.info(f"QueryAgent (BeeAI) processing: {query}")
        
        start_time = time.time()
        success = True
        error_message = None
        response_text = ""

        try:
            # Track with MLflow
            with self.mlflow_tracker.track_operation(
                operation_name="query_agent_process",
                params={
                    "agent": self.name,
                    "query_length": len(query),
                    "has_context": context is not None
                },
                track_resources=True,
                track_accuracy=False
            ) as tracker:
                response = await self.agent.run(prompt=query)
                response_text = response.output.text
                
                # Log metrics
                tracker.log_metrics({
                    "response_length": len(response_text),
                    "processing_time_ms": (time.time() - start_time) * 1000
                })
                
                result = {
                    "agent": self.name,
                    "response": response_text,
                    "confidence": 1.0  # Placeholder
                }
                
                return result
                
        except Exception as e:
            success = False
            error_message = str(e)
            logger.error(f"QueryAgent failed: {e}")
            
            result = {
                "agent": self.name,
                "response": "I encountered an error processing your request.",
                "error": error_message
            }
            
            return result
            
        finally:
            # Metrics recording done at RAGSystem layer
            pass
