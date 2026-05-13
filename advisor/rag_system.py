"""
Complete RAG system integrating retrieval, query processing, and LLM generation.

This module provides the main interface for the RAG-based code advisor.
"""

from typing import Dict, Any, Optional, List
from loguru import logger
import threading
import time

from advisor.llm_client import get_ollama_client
from advisor.rag_retrieval import get_rag_retriever
from advisor.query_processor import get_query_processor
from advisor.mlflow_tracking import get_mlflow_tracker
from advisor.metrics_collector import get_metrics_collector, track_query, CollectionHealth, sync_collection_health
from advisor.analytics import get_analytics_manager
from advisor.relationships import get_relationship_query_handler
from advisor.config import get_full_config
from advisor.prompt_templates import get_prompt_manager
from advisor.query_patterns import QueryType


class RAGSystem:
    """Complete RAG system for code advisory."""

    def __init__(self):
        """Initialize RAG system."""
        self.llm_client = get_ollama_client()
        self.retriever = get_rag_retriever()
        self.query_processor = get_query_processor()
        self.mlflow_tracker = get_mlflow_tracker(
            enable_resource_monitoring=True,
            enable_accuracy_tracking=True
        )
        self.metrics_collector = get_metrics_collector()
        self.analytics = get_analytics_manager()
        self.relationships = get_relationship_query_handler()

        config = get_full_config()
        self.rag_config = config.get("rag")

        logger.info("Initialized RAG system")
        
        # Refresh health on startup
        self._refresh_collection_health()

    def _refresh_collection_health(self):
        """Refresh health metrics for all enabled collections."""
        sync_collection_health(self.retriever, self.metrics_collector)

    def query(
        self,
        user_query: str,
        include_context: bool = True,
        track_metrics: bool = True,
        dry_run: bool = False,
        query_type_override: Optional[str] = None,
        perspective: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process a user query and generate a response.

        Args:
            user_query: User's question or request
            include_context: Whether to include retrieved context
            track_metrics: Whether to track with MLflow
            dry_run: If True, compose Dr.Egeria commands but do not execute them

        Returns:
            Dictionary with response and metadata
        """
        logger.info(f"Processing query: {user_query[:100]}...")

        # Process the query
        result = self._process_query(
            user_query, include_context, dry_run=dry_run,
            query_type_override=query_type_override,
            perspective=perspective,
        )
        
        # Always record metrics in local database (for dashboard)
        try:
            self._record_local_metrics(result)
        except Exception as e:
            logger.warning(f"Failed to record local metrics: {e}")
        
        # Track with MLflow in background so the caller gets the result immediately
        if track_metrics:
            threading.Thread(
                target=self._track_mlflow,
                args=(result, include_context),
                daemon=True
            ).start()

        return result

    def _track_mlflow(self, result: Dict[str, Any], include_context: bool):
        """Log query metrics to MLflow in a background thread (non-blocking)."""
        try:
            with self.mlflow_tracker.track_operation(
                operation_name="rag_query",
                params={
                    "query_length": len(result.get("query", "")),
                    "include_context": include_context
                },
                track_resources=True,
                track_accuracy=True
            ) as tracker:
                sources = result.get("sources") or []
                for source in sources:
                    try:
                        if hasattr(source, 'score') and source.score is not None:
                            tracker.add_relevance(source.score)
                        elif isinstance(source, dict) and source.get('score') is not None:
                            tracker.add_relevance(source['score'])
                    except Exception:
                        pass
                tracker.log_metrics({
                    "response_length": len(result.get("response", "")),
                    "num_sources": result.get("num_sources", 0),
                    "retrieval_time": result.get("retrieval_time", 0.0),
                    "generation_time": result.get("generation_time", 0.0),
                    "avg_relevance_score": result.get("avg_relevance_score", 0.0),
                    "context_length": result.get("context_length", 0)
                })
        except Exception as e:
            logger.warning(f"MLflow tracking failed: {e}")

    # Phrases that signal a definitional/conceptual question, NOT a data retrieval query.
    # These go to RAG even when the semantic score is high.
    _DEFINITIONAL_PREFIXES = (
        "what is ", "what's a ", "what's the ", "what are the ",
        "how does ", "how do ", "explain ", "define ", "describe ",
        "tell me about ", "what does ", "what do you mean by ",
        "can you explain", "give me an overview",
    )

    # Keywords that signal the user wants Python code, not live Egeria data.
    _CODE_EXAMPLE_SIGNALS = (
        "python", "code example", "code sample", "write python",
        "python code", "pyegeria example", "python snippet",
    )

    def _is_report_query(self, query: str) -> bool:
        """
        Return True if the query is a data-retrieval request that the report
        pipeline can answer by running a report spec.

        Semantic similarity against question_spec entries with three guards:
        1. Score must be >= 0.50 (lowered from 0.65 — listing questions now in index).
        2. Query must not start with a definitional phrase (those go to RAG).
        3. Query must not explicitly request Python code / code examples.
        """
        q = query.strip().lower()
        if any(q.startswith(p) for p in self._DEFINITIONAL_PREFIXES):
            return False
        if any(sig in q for sig in self._CODE_EXAMPLE_SIGNALS):
            return False
        try:
            from advisor.report_pipeline import _question_index
            hits = _question_index.search(query, top_k=1, threshold=0.50)
            if hits:
                logger.info(
                    f"Semantic report pre-check: {hits[0]['report_spec']} "
                    f"(score={hits[0]['score']:.2f})"
                )
                return True
        except Exception as exc:
            logger.debug(f"_is_report_query check failed: {exc}")
        return False

    def _report_alternatives(self, query: str) -> Optional[Dict[str, Any]]:
        """
        When semantic similarity is medium (0.35–0.50), return a clarification
        response offering the matched report spec alongside a RAG alternative.
        Returns None if no medium-confidence hit exists.
        """
        q = query.strip().lower()
        if any(q.startswith(p) for p in self._DEFINITIONAL_PREFIXES):
            return None
        if any(sig in q for sig in self._CODE_EXAMPLE_SIGNALS):
            return None
        try:
            from advisor.report_pipeline import _question_index
            hits = _question_index.search(query, top_k=2, threshold=0.35)
            # Only surface alternatives for medium confidence (below the run threshold)
            medium_hits = [h for h in hits if h["score"] < 0.50]
            if not medium_hits:
                return None
            best = medium_hits[0]
            spec = best["report_spec"]
            score = best["score"]
            logger.info(f"Medium-confidence report match: {spec} ({score:.2f}) — offering alternatives")
            return {
                "query": query,
                "response": (
                    f"Your query could be answered in a couple of ways:\n\n"
                    f"**Option 1 — Run the Egeria report** (recommended if you want current live data):\n"
                    f"I found the **{spec}** report that may match your question "
                    f"(confidence: {score:.0%}). "
                    f"To run it, use Dr.Egeria: `[[{spec}]]`  \n"
                    f"Or ask me: *\"run the {spec} report\"*\n\n"
                    f"**Option 2 — Explain or show code examples**:\n"
                    f"I can also explain how to work with this in pyegeria — just ask "
                    f"*\"how do I...\"* or *\"show me an example of...\"*\n\n"
                    f"Which do you want?"
                ),
                "query_type": "clarification",
                "report_name": spec,
                "sources": [],
                "num_sources": 0,
                "retrieval_time": 0.0,
                "generation_time": 0.0,
                "avg_relevance_score": score,
                "context_length": 0,
            }
        except Exception as exc:
            logger.debug(f"_report_alternatives check failed: {exc}")
        return None

    def _process_query(
        self,
        user_query: str,
        include_context: bool,
        dry_run: bool = False,
        query_type_override: Optional[str] = None,
        perspective: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Internal query processing."""
        # Process query to understand intent
        query_analysis = self.query_processor.process(user_query)
        logger.info(f"Query type: {query_analysis['query_type']}")

        # Explicit user intent overrides automatic classification.
        if query_type_override:
            logger.info(f"Intent override from UI: '{query_type_override}'")
            query_analysis = dict(query_analysis)
            query_analysis['query_type'] = query_type_override
        # When pattern matching returns 'general', use the LLM classifier to
        # narrow the intent before committing to RAG retrieval.
        elif query_analysis['query_type'] == 'general':
            from advisor.llm_intent_classifier import get_intent_classifier
            refined = get_intent_classifier().classify(user_query)
            if refined != 'general':
                logger.info(f"LLM intent classifier refined 'general' → '{refined}'")
                query_analysis = dict(query_analysis)
                query_analysis['query_type'] = refined

        # Role-aware routing: apply perspective signals before pipeline dispatch.
        #
        # Developer / Data Engineer + example/code keywords → force ExamplesAgent.
        # This overrides both the pattern classifier and the LLM intent classifier,
        # which frequently mistake "create X in Python" for a WRITE_COMMAND.
        #
        # Data Steward / Governance Officer + ambiguous "show me / example / sample"
        # → return a clarification asking whether they want Python code or Dr.Egeria.
        if not query_type_override:
            query_lower = user_query.lower()
            code_signals = any(sig in query_lower for sig in self._CODE_EXAMPLE_SIGNALS)
            example_signals = any(kw in query_lower for kw in (
                "example", "sample", "show me", "how do i", "how to",
                "what methods", "which methods", "available methods", "list methods",
                "what api", "api for", "methods for", "what functions",
                "what can i do with", "what class", "which class",
            ))
            tech_roles = {"developer", "data_engineer"}
            steward_roles = {"data_steward", "governance_officer"}

            if perspective in tech_roles and (code_signals or example_signals):
                logger.info(
                    f"Role '{perspective}' + code/example signal → routing to ExamplesAgent"
                )
                try:
                    from advisor.agents.examples_agent import get_examples_agent
                    return get_examples_agent().handle(user_query)
                except Exception as exc:
                    logger.warning(f"ExamplesAgent failed ({exc}), continuing normal routing")

            elif perspective in steward_roles and example_signals and not code_signals:
                # Ambiguous: could be Dr.Egeria command or a conceptual/code example.
                logger.info(
                    f"Role '{perspective}' + ambiguous example signal → returning clarification"
                )
                return {
                    "query": user_query,
                    "response": (
                        "Would you like me to:\n\n"
                        "1. **Show a Python (pyegeria) code example** — how to do this "
                        "programmatically using the pyegeria SDK?\n"
                        "2. **Show a Dr.Egeria markdown template** — the notebook command "
                        "you paste into an Egeria Workspaces Jupyter cell and fill in?\n\n"
                        "You can also click **Show me** (Python) or **Act** (Dr.Egeria) "
                        "above to set your intent before asking."
                    ),
                    "query_type": "clarification",
                    "sources": [],
                    "num_sources": 0,
                    "retrieval_time": 0.0,
                    "generation_time": 0.0,
                    "avg_relevance_score": 0.0,
                    "context_length": 0,
                }

        # Handle quantitative queries directly with analytics
        if query_analysis['query_type'] == 'quantitative':
            logger.info("Handling quantitative query with analytics module")
            path_filter = query_analysis.get('path_filter')
            if path_filter:
                logger.info(f"Applying path filter: {path_filter}")
            response = self.analytics.answer_quantitative_query(user_query, path_filter)
            return {
                "query": user_query,
                "response": response,
                "query_type": "quantitative",
                "path_filter": path_filter,
                "sources": [],
                "num_sources": 0,
                "retrieval_time": 0.0,
                "generation_time": 0.0,
                "avg_relevance_score": 0.0,
                "context_length": 0
            }
        
        # Handle relationship queries directly with relationship graph
        if query_analysis['query_type'] == 'relationship':
            logger.info("Handling relationship query with relationship graph")
            response = self.relationships.answer_relationship_query(user_query)
            return {
                "query": user_query,
                "response": response,
                "query_type": "relationship",
                "sources": [],
                "num_sources": 0,
                "retrieval_time": 0.0,
                "generation_time": 0.0,
                "avg_relevance_score": 0.0,
                "context_length": 0
            }

        # Handle report queries via MCP pyegeria server.
        # When the user explicitly overrides intent to a non-report type, skip the
        # semantic pre-check so the override is honoured unconditionally.
        if query_type_override and query_type_override != 'report':
            is_report = False
        else:
            is_report = (
                query_analysis['query_type'] == 'report'
                or self._is_report_query(user_query)
            )
        if is_report:
            logger.info("Handling report query via MCP report pipeline")
            try:
                from advisor.report_pipeline import get_report_pipeline
                return get_report_pipeline().process(user_query, perspective=perspective)
            except Exception as e:
                logger.warning(f"Report pipeline failed ({e}), falling back to RAG")
                # Fall through to RAG below

        # Handle command/action queries.
        # If the query asks for a sample/template, return the Dr.Egeria markdown template.
        # Otherwise execute the command via DrEgeriaActionAgent.
        if query_analysis['query_type'] == 'command':
            _template_signals = ("template", "sample", "example", "show me", "give me")
            wants_template = any(sig in user_query.lower() for sig in _template_signals)
            if wants_template:
                logger.info("Handling Dr.Egeria template request via DrEgeriaTemplateAgent")
                try:
                    from advisor.agents.dre_template_agent import get_dre_template_agent
                    return get_dre_template_agent().handle(user_query)
                except Exception as e:
                    logger.warning(f"DrEgeriaTemplateAgent failed ({e}), falling back to DrEgeriaActionAgent")
            logger.info("Handling command query via DrEgeriaActionAgent")
            try:
                from advisor.agents.dr_egeria_agent import get_dr_egeria_agent
                return get_dr_egeria_agent().handle(user_query, dry_run=dry_run)
            except Exception as e:
                logger.warning(f"DrEgeriaActionAgent failed ({e}), falling back to RAG")

        # Before falling through to RAG, offer alternatives when there is a medium-confidence
        # report match — prevents silent wrong-route responses.
        # Skip when the user has explicitly specified a non-report intent.
        if not query_type_override or query_type_override == 'report':
            alt = self._report_alternatives(user_query)
            if alt is not None:
                return alt

        # Route code/example queries to ExamplesAgent (BeeAI + fallback).
        if query_analysis['query_type'] in ('code_search', 'example'):
            logger.info(f"Routing {query_analysis['query_type']} query to ExamplesAgent")
            try:
                from advisor.agents.examples_agent import get_examples_agent
                return get_examples_agent().handle(user_query)
            except Exception as exc:
                logger.warning(f"ExamplesAgent failed ({exc}), falling back to RAG")

        # Route explanation/conceptual/debugging queries to DocAgent (BeeAI + fallback).
        if query_analysis['query_type'] in ('explanation', 'best_practice', 'comparison', 'debugging', 'general'):
            logger.info(f"Routing {query_analysis['query_type']} query to DocAgent")
            try:
                from advisor.agents.doc_agent import get_doc_agent
                return get_doc_agent().handle(user_query, mode=query_analysis['query_type'])
            except Exception as exc:
                logger.warning(f"DocAgent failed ({exc}), falling back to RAG")

        # Get search strategy
        search_strategy = query_analysis["search_strategy"]
        
        # Check if we should prioritize documentation
        prioritize_docs = query_analysis.get("prioritize_docs", False)
        offer_examples = query_analysis.get("offer_examples", False)

        # Retrieve relevant context with timing
        retrieval_start = time.time()
        if include_context:
            context, sources = self.retriever.retrieve_and_build_context(
                query=query_analysis["enhanced_query"],
                top_k=search_strategy["top_k"],
                min_score=search_strategy["min_score"],
                format_style=search_strategy["format_style"],
                prioritize_docs=prioritize_docs  # NEW: Pass documentation priority flag
            )
        else:
            context = ""
            sources = []
        retrieval_time = time.time() - retrieval_start

        # Get collections that were searched (from retrieval metadata)
        collections_searched = []
        if hasattr(self.retriever, 'multi_store') and self.retriever.multi_store:
            # Try to get from last search (this is a simplification)
            collections_searched = getattr(self.retriever, '_last_collections_searched', [])
        
        # Build prompt using template manager
        prompt_manager = get_prompt_manager()

        # Convert query_type string to QueryType enum if needed
        if isinstance(query_analysis["query_type"], str):
            query_type_enum = QueryType(query_analysis["query_type"])
        else:
            query_type_enum = query_analysis["query_type"]

        # Prepend perspective so the LLM tailors depth and terminology
        effective_query = user_query
        if perspective:
            perspective_labels = {
                "developer": "Software Developer",
                "data_engineer": "Data Engineer",
                "data_steward": "Data Steward",
                "governance_officer": "Governance Officer",
            }
            role_label = perspective_labels.get(perspective, perspective.replace("_", " ").title())
            effective_query = f"[User role: {role_label}]\n{user_query}"

        prompt = prompt_manager.build_prompt(
            user_query=effective_query,
            context=context,
            query_type=query_type_enum,
            collections_searched=collections_searched,
            offer_examples=offer_examples
        )

        # Get appropriate system prompt based on collections, optionally tailored to perspective
        primary_collection = collections_searched[0] if collections_searched else None
        system_prompt = prompt_manager.get_system_prompt(
            primary_collection=primary_collection,
            perspective=perspective,
        )

        # Generate response with timing
        generation_start = time.time()
        response = self.llm_client.generate(
            prompt=prompt,
            system=system_prompt,
            temperature=self.rag_config.generation.temperature,
            max_tokens=self.rag_config.generation.max_tokens
        )
        generation_time = time.time() - generation_start

        # Calculate average relevance score
        avg_relevance_score = 0.0
        if sources:
            # Handle both SearchResult objects and dictionaries
            scores = []
            for s in sources:
                if hasattr(s, 'score'):
                    scores.append(s.score)
                elif isinstance(s, dict):
                    scores.append(s.get("score", 0.0))
            avg_relevance_score = sum(scores) / len(scores) if scores else 0.0

        # Build result with enhanced metrics
        result = {
            "query": user_query,
            "response": response,
            "query_type": query_analysis["query_type"],
            "sources": sources,
            "num_sources": len(sources),
            "retrieval_time": retrieval_time,
            "generation_time": generation_time,
            "avg_relevance_score": avg_relevance_score,
            "context_length": len(context)
        }

        logger.info(f"Generated response: {len(response)} chars from {len(sources)} sources")

        return result

    def _record_local_metrics(self, result: Dict[str, Any]):
        """Record metrics in local terminal dashboard database."""
        try:
            # Extract primary collection name
            collection_name = "N/A"
            if result.get("sources"):
                # Use the actual collection name from the first source
                first_source = result["sources"][0]
                # MultiCollectionStore adds '_collection' to metadata
                if hasattr(first_source, "metadata"):
                    collection_name = first_source.metadata.get("_collection") or first_source.metadata.get("collection", "N/A")
                elif isinstance(first_source, dict):
                    collection_name = first_source.get("_collection") or first_source.get("collection", "N/A")
            
            # Use record_query directly to avoid context manager nesting issues
            from advisor.metrics_collector import QueryMetric
            import json
            
            # Map query_type to string if it's an enum
            query_type = result.get("query_type", "GENERAL")
            if hasattr(query_type, "value"):
                query_type = query_type.value
            
            # Prepare source metadata for storage
            sources_data = []
            for source in result.get("sources", []):
                source_info = {
                    "score": source.score if hasattr(source, "score") else source.get("score", 0.0),
                    "collection": source.metadata.get("_collection") if hasattr(source, "metadata") else source.get("_collection", "unknown"),
                    "file": source.metadata.get("source") if hasattr(source, "metadata") else source.get("source", "unknown")
                }
                sources_data.append(source_info)
            
            metric = QueryMetric(
                timestamp=time.time(),
                query_text=result["query"],
                collection_name=collection_name,
                latency_ms=(result.get("retrieval_time", 0) + result.get("generation_time", 0)) * 1000,
                query_type=str(query_type).upper(),
                cache_hit=result.get("cache_hit", False),
                success=True,
                result_count=result.get("num_sources", 0),
                search_time_ms=result.get("retrieval_time", 0) * 1000,
                llm_time_ms=result.get("generation_time", 0) * 1000,
                avg_relevance_score=result.get("avg_relevance_score", 0.0),
                sources_json=json.dumps(sources_data) if sources_data else None
            )
            
            self.metrics_collector.record_query(metric)
            
            # Log sources to MLflow if enabled
            if sources_data and self.mlflow_tracker:
                try:
                    self.mlflow_tracker.log_query_sources(
                        query_text=result["query"],
                        sources=sources_data,
                        avg_relevance_score=result.get("avg_relevance_score", 0.0),
                        collection_name=collection_name
                    )
                except Exception as e:
                    logger.warning(f"Failed to log sources to MLflow: {e}")
                
            # Update collection health synchronously for visibility
            if collection_name != "N/A":
                from advisor.collection_config import get_collection
                coll_config = get_collection(collection_name)
                if coll_config:
                    self.metrics_collector.record_collection_health(CollectionHealth(
                        collection_name=collection_name,
                        last_check=time.time(),
                        entity_count=result.get("num_sources", 0),
                        health_score=1.0,
                        storage_size_mb=0.0,
                        last_update=time.time(),
                        status="healthy"
                    ))
        except Exception as e:
            logger.warning(f"Failed to record local metrics: {e}")

    def _get_system_prompt(self) -> str:
        """Get system prompt for the LLM."""
        return """You are an expert assistant for the Egeria Python library (pyegeria).

CRITICAL RULES - FOLLOW EXACTLY:

1. ONLY use information from the provided code context
2. If the context doesn't contain the answer, say: "I don't have enough information in the provided context to answer that question accurately."
3. ALWAYS cite specific files, classes, and methods from the context
4. Be technical and specific - include class names, method signatures, and parameters
5. When showing code, make it complete and runnable
6. Do NOT make up or infer information not in the context
7. Do NOT use general knowledge about Python or other libraries

RESPONSE FORMAT:
- Start with a direct answer
- Provide specific code examples from the context
- Cite sources: "From [file_path]: [class/method]"
- If showing usage, include imports and setup

Remember: Your knowledge is LIMITED to the provided context. If it's not in the context, you don't know it."""

    def _build_prompt(
        self,
        user_query: str,
        context: str,
        query_type: str,
        offer_examples: bool = False
    ) -> str:
        """Build the complete prompt for the LLM."""
        if context:
            # Build follow-up suggestion if needed
            followup = ""
            if offer_examples:
                followup = """

---

After answering, ask the user if they would like to see:
- A Python code example using pyegeria
- A Java implementation example
- A REST API call example

Format: "Would you like to see an example? I can show you: [Python/Java/REST API]"
"""
            
            prompt = f"""# CODE CONTEXT FROM EGERIA LIBRARY

{context}

# USER QUESTION

{user_query}

# YOUR TASK

Answer the question using ONLY the code context above. Follow these rules:

1. Use ONLY information from the context - do not add external knowledge
2. Cite specific files, classes, and methods from the context
3. If showing code, make it complete with imports
4. If the context doesn't answer the question, say so explicitly
5. Be specific and technical - include parameter names, types, return values
6. Focus on conceptual explanation first, then offer code examples{followup}

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

Now answer the user's question following this format."""
        else:
            prompt = f"""# USER QUESTION

{user_query}

# IMPORTANT

No code context is available for this question. You should respond:

"I don't have access to the specific code context needed to answer this question accurately. Please try rephrasing your question or asking about a specific Egeria concept, class, or method."

Do NOT attempt to answer from general knowledge."""

        return prompt

    def chat(
        self,
        messages: List[Dict[str, str]],
        include_context: bool = True
    ) -> Dict[str, Any]:
        """
        Multi-turn chat interface.

        Args:
            messages: List of message dicts with 'role' and 'content'
            include_context: Whether to retrieve context for last message

        Returns:
            Dictionary with response and metadata
        """
        if not messages:
            raise ValueError("Messages list cannot be empty")

        # Get last user message
        last_message = messages[-1]["content"]

        # Process like a regular query
        result = self.query(last_message, include_context=include_context)

        return result

    def explain_code(
        self,
        code_snippet: str,
        context: Optional[str] = None,
        track_metrics: bool = True
    ) -> str:
        """
        Explain a code snippet.

        Args:
            code_snippet: Code to explain
            context: Optional additional context
            track_metrics: Whether to track with MLflow

        Returns:
            Explanation text
        """
        if track_metrics:
            with self.mlflow_tracker.track_operation(
                operation_name="explain_code",
                params={
                    "code_length": len(code_snippet),
                    "has_context": context is not None
                }
            ) as tracker:
                generation_start = time.time()

                prompt = f"""Please explain the following code:

```python
{code_snippet}
```
"""

                if context:
                    prompt += f"\n\nAdditional context: {context}"

                response = self.llm_client.generate(
                    prompt=prompt,
                    system=self._get_system_prompt(),
                    temperature=0.3  # Lower temperature for explanations
                )

                generation_time = time.time() - generation_start

                tracker.log_metrics({
                    "response_length": len(response),
                    "generation_time": generation_time
                })

                return response
        else:
            prompt = f"""Please explain the following code:

```python
{code_snippet}
```
"""

            if context:
                prompt += f"\n\nAdditional context: {context}"

            response = self.llm_client.generate(
                prompt=prompt,
                system=self._get_system_prompt(),
                temperature=0.3  # Lower temperature for explanations
            )

            return response

    def find_similar_code(
        self,
        code_snippet: str,
        top_k: int = 5,
        track_metrics: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Find code similar to a given snippet.

        Args:
            code_snippet: Code to find similar examples for
            top_k: Number of results
            track_metrics: Whether to track with MLflow

        Returns:
            List of similar code snippets
        """
        if track_metrics:
            with self.mlflow_tracker.track_operation(
                operation_name="find_similar_code",
                params={
                    "code_length": len(code_snippet),
                    "top_k": top_k
                }
            ) as tracker:
                results = self.retriever.get_similar_code(
                    code_snippet=code_snippet,
                    top_k=top_k
                )

                # Calculate average similarity score (results are now dictionaries)
                avg_similarity_score = 0.0
                if results:
                    avg_similarity_score = sum(r["score"] for r in results) / len(results)

                tracker.log_metrics({
                    "num_results": len(results),
                    "avg_similarity_score": avg_similarity_score
                })

                return results
        else:
            return self.retriever.get_similar_code(
                code_snippet=code_snippet,
                top_k=top_k
            )

    def get_file_summary(
        self,
        file_path: str,
        track_metrics: bool = True
    ) -> str:
        """
        Get a summary of a file's contents.

        Args:
            file_path: Path to file
            track_metrics: Whether to track with MLflow

        Returns:
            Summary text
        """
        if track_metrics:
            with self.mlflow_tracker.track_operation(
                operation_name="get_file_summary",
                params={
                    "file_path": file_path
                }
            ) as tracker:
                generation_start = time.time()

                # Get file context
                context = self.retriever.get_file_context(file_path)

                # Generate summary
                prompt = f"""Please provide a concise summary of this file's purpose and main components:

{context}

Focus on:
1. Main purpose of the file
2. Key classes/functions
3. Important functionality"""

                response = self.llm_client.generate(
                    prompt=prompt,
                    system=self._get_system_prompt(),
                    temperature=0.3,
                    max_tokens=500
                )

                generation_time = time.time() - generation_start

                # Count code elements (classes, functions, etc.)
                num_code_elements = context.count("class ") + context.count("def ")

                tracker.log_metrics({
                    "response_length": len(response),
                    "num_code_elements": num_code_elements,
                    "generation_time": generation_time
                })

                return response
        else:
            # Get file context
            context = self.retriever.get_file_context(file_path)

            # Generate summary
            prompt = f"""Please provide a concise summary of this file's purpose and main components:

{context}

Focus on:
1. Main purpose of the file
2. Key classes/functions
3. Important functionality"""

            response = self.llm_client.generate(
                prompt=prompt,
                system=self._get_system_prompt(),
                temperature=0.3,
                max_tokens=500
            )

            return response

    def health_check(self) -> Dict[str, bool]:
        """
        Check health of all system components.

        Returns:
            Dictionary with component health status
        """
        # Ensure vector store is connected
        if not self.retriever.vector_store.is_connected():
            try:
                self.retriever.vector_store.connect()
            except Exception as e:
                logger.warning(f"Failed to connect to vector store during health check: {e}")

        health = {
            "llm_available": self.llm_client.is_available(),
            "vector_store_connected": self.retriever.vector_store.is_connected(),
            "embedding_model_loaded": self.retriever.embedding_gen.model is not None
        }

        logger.info(f"Health check: {health}")

        return health


# Global RAG system instance
_rag_system: Optional[RAGSystem] = None


def get_rag_system() -> RAGSystem:
    """Get or create the global RAG system instance."""
    global _rag_system

    if _rag_system is None:
        _rag_system = RAGSystem()

    return _rag_system
