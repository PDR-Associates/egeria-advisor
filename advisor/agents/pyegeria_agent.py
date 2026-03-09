"""
PyEgeria Agent - Specialized agent for PyEgeria Python library queries.

This agent provides intelligent responses about PyEgeria classes, methods,
modules, and usage patterns by leveraging the pyegeria collection in Milvus.
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from advisor.vector_store import VectorStoreManager
from advisor.llm_client import OllamaClient, get_ollama_client
from advisor.config import settings

logger = logging.getLogger(__name__)


@dataclass
class PyEgeriaQueryResult:
    """Result from PyEgeria query classification and search."""
    query_type: str  # 'class', 'method', 'module', 'usage', 'example', 'general'
    search_results: List[Dict[str, Any]]
    confidence: float
    

class PyEgeriaAgent:
    """
    Specialized agent for answering PyEgeria-related questions.
    
    Handles queries about:
    - PyEgeria classes (e.g., "What is GlossaryManager?")
    - Methods and functions (e.g., "How do I create a glossary?")
    - Modules and packages (e.g., "What's in pyegeria.admin?")
    - Usage patterns (e.g., "How to connect to OMAG server?")
    - Code examples (e.g., "Show me asset creation example")
    """
    
    def __init__(
        self,
        vector_store: Optional[VectorStoreManager] = None,
        llm_client: Optional[OllamaClient] = None
    ):
        """
        Initialize PyEgeria agent.
        
        Args:
            vector_store: Vector store manager for semantic search
            llm_client: LLM client for generating responses
        """
        self.vector_store = vector_store or VectorStoreManager()
        self.llm_client = llm_client or get_ollama_client()
        self.collection_name = "pyegeria"
        
        # Query type patterns
        self.query_patterns = {
            'class': [
                'class', 'what is', 'tell me about', 'explain',
                'manager', 'client', 'handler', 'widget'
            ],
            'method': [
                'how do i', 'how to', 'method', 'function',
                'create', 'get', 'update', 'delete', 'list',
                'connect', 'configure', 'setup'
            ],
            'module': [
                'module', 'package', 'what\'s in', 'contains',
                'pyegeria.', 'admin', 'glossary', 'asset'
            ],
            'usage': [
                'use', 'using', 'usage', 'work with',
                'integrate', 'implement'
            ],
            'example': [
                'example', 'sample', 'demo', 'show me',
                'code', 'snippet'
            ]
        }
        
        logger.info("PyEgeria Agent initialized")
    
    def classify_query(self, query: str) -> str:
        """
        Classify the type of PyEgeria query.
        
        Args:
            query: User's query
            
        Returns:
            Query type: 'class', 'method', 'module', 'usage', 'example', or 'general'
        """
        query_lower = query.lower()
        
        # Count pattern matches for each type
        scores = {}
        for query_type, patterns in self.query_patterns.items():
            score = sum(1 for pattern in patterns if pattern in query_lower)
            if score > 0:
                scores[query_type] = score
        
        # Return type with highest score, or 'general' if no matches
        if scores:
            return max(scores.items(), key=lambda x: x[1])[0]
        return 'general'
    
    def is_pyegeria_query(self, query: str) -> bool:
        """
        Determine if query is about PyEgeria.
        
        Uses a two-stage approach:
        1. Check for explicit PyEgeria indicators
        2. If asking about a class/methods, do a quick search to see if it's in pyegeria collection
        
        Args:
            query: User's query
            
        Returns:
            True if query is about PyEgeria
        """
        query_lower = query.lower()
        logger.info(f"PyEgeria detection for query: {query[:100]}")
        
        # Stage 1: Explicit PyEgeria indicators
        pyegeria_indicators = [
            'pyegeria', 'py-egeria', 'python client', 'python api',
            'python library', 'rest client', 'async client',
            'widget', 'egeria client', 'python sdk',
            # Common PyEgeria classes (lowercase for matching)
            'glossarymanager', 'assetmanager', 'egeriaclient',
            'egeriatech', 'serverops', 'platformservices',
            'projectmanager', 'communitymanager', 'validvaluesmanager',
            'collectionmanager', 'datamanager', 'governancemanager',
            # Common modules
            'pyegeria.admin', 'pyegeria.glossary', 'pyegeria.asset',
            'pyegeria.core', 'pyegeria.utils'
        ]
        
        if any(indicator in query_lower for indicator in pyegeria_indicators):
            logger.info(f"✓ Detected via explicit indicator")
            return True
        
        # Stage 2: Check if asking about a class/methods and if it exists in pyegeria
        class_query_patterns = [
            'what methods', 'methods does', 'methods in', 'methods of',
            'tell me about', 'what is', 'how do i use',
            'class', 'manager', 'officer', 'handler', 'service'
        ]
        
        matching_patterns = [p for p in class_query_patterns if p in query_lower]
        if matching_patterns:
            logger.info(f"Query matches class patterns: {matching_patterns}")
            # Do a quick search in pyegeria collection
            try:
                logger.info(f"Searching pyegeria collection for: {query[:50]}")
                results = self.vector_store.search(
                    collection_name=self.collection_name,
                    query_text=query,
                    top_k=3
                )
                logger.info(f"Search returned {len(results)} results")
                if results and len(results) > 0:
                    logger.info(f"Top result score: {results[0].score:.3f}")
                    # If we get good results (score >= 0.25), it's likely a PyEgeria query
                    # Lowered threshold to catch edge cases like ProjectManager
                    if results[0].score >= 0.25:
                        logger.info(f"✓ Detected PyEgeria query via search (score: {results[0].score:.2f})")
                        return True
                    else:
                        logger.info(f"✗ Score too low ({results[0].score:.3f} < 0.25)")
            except Exception as e:
                logger.warning(f"Error in PyEgeria query detection search: {e}")
                import traceback
                logger.warning(traceback.format_exc())
        else:
            logger.info(f"No class query patterns matched")
        
        logger.info(f"✗ Not detected as PyEgeria query")
        return False
    
    def search_pyegeria(
        self,
        query: str,
        top_k: int = 10,
        min_score: float = 0.35
    ) -> List[Dict[str, Any]]:
        """
        Search PyEgeria collection for relevant content.
        
        Args:
            query: Search query
            top_k: Number of results to return
            min_score: Minimum similarity score
            
        Returns:
            List of search results as dictionaries with metadata
        """
        try:
            # Search without min_score filter (will filter after)
            search_results = self.vector_store.search(
                collection_name=self.collection_name,
                query_text=query,
                top_k=top_k * 2  # Get more results to filter
            )
            
            # Convert SearchResult objects to dictionaries and filter by score
            results = []
            for result in search_results:
                if result.score >= min_score:
                    results.append({
                        'id': result.id,
                        'score': result.score,
                        'text': result.text,
                        'metadata': result.metadata
                    })
                    if len(results) >= top_k:
                        break
            
            logger.info(f"Found {len(results)} PyEgeria results for query: {query[:50]}...")
            return results
            
        except Exception as e:
            logger.error(f"Error searching PyEgeria collection: {e}")
            return []
    
    def get_all_class_methods(self, class_name: str) -> List[Dict[str, Any]]:
        """
        Get ALL methods for a specific class by searching the file and filtering.
        
        Args:
            class_name: Name of the class
            
        Returns:
            List of method dictionaries
        """
        try:
            # Step 1: Find the class to get its file path
            class_results = self.vector_store.search(
                collection_name=self.collection_name,
                query_text=f"class {class_name}",
                top_k=10
            )
            
            class_file = None
            for result in class_results:
                metadata = result.metadata
                if metadata.get('element_type') == 'class' and metadata.get('name') == class_name:
                    class_file = metadata.get('file_path')
                    logger.info(f"Found class {class_name} in {class_file}")
                    break
            
            if not class_file:
                logger.warning(f"Could not find file for class {class_name}")
                return []
            
            # Step 2: Search for ALL content from that file with high top_k
            # Use the file path as part of the query to get relevant results
            file_results = self.vector_store.search(
                collection_name=self.collection_name,
                query_text=f"{class_name} {class_file}",
                top_k=200  # Get many results to capture all methods
            )
            
            # Step 3: Filter for methods belonging to this class
            methods = []
            seen_methods = set()
            
            for result in file_results:
                metadata = result.metadata
                # Check if it's a function in the same file and belongs to our class
                if (metadata.get('element_type') == 'function' and
                    metadata.get('file_path') == class_file and
                    metadata.get('class_name') == class_name):
                    
                    method_name = metadata.get('name', '')
                    if method_name and method_name not in seen_methods:
                        seen_methods.add(method_name)
                        methods.append({
                            'name': method_name,
                            'docstring': metadata.get('docstring', ''),
                            'signature': metadata.get('signature', ''),
                            'file_path': metadata.get('file_path', ''),
                            'score': result.score
                        })
            
            # Sort by name for consistent ordering
            methods.sort(key=lambda x: x['name'])
            
            logger.info(f"Found {len(methods)} methods for class {class_name} in {class_file}")
            return methods
            
        except Exception as e:
            logger.error(f"Error getting methods for class {class_name}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []
    
    def extract_class_info(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Extract class information from search results.
        
        Args:
            results: Search results
            
        Returns:
            Dictionary with class information
        """
        classes = {}
        
        for result in results:
            metadata = result.get('metadata', {})
            element_type = metadata.get('element_type', '')
            
            if element_type == 'class':
                class_name = metadata.get('name', '')
                if class_name and class_name not in classes:
                    classes[class_name] = {
                        'name': class_name,
                        'file_path': metadata.get('file_path', ''),
                        'docstring': metadata.get('docstring', ''),
                        'methods': [],
                        'score': result.get('score', 0.0)
                    }
            elif element_type == 'function' and 'class_name' in metadata:
                class_name = metadata.get('class_name', '')
                method_name = metadata.get('name', '')
                if class_name in classes:
                    classes[class_name]['methods'].append({
                        'name': method_name,
                        'docstring': metadata.get('docstring', ''),
                        'signature': metadata.get('signature', '')
                    })
        
        return classes
    
    def extract_module_info(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Extract module information from search results.
        
        Args:
            results: Search results
            
        Returns:
            Dictionary with module information
        """
        modules = {}
        
        for result in results:
            metadata = result.get('metadata', {})
            file_path = metadata.get('file_path', '')
            
            if file_path:
                # Extract module path from file path
                if 'pyegeria/' in file_path:
                    module_path = file_path.split('pyegeria/')[1].replace('.py', '').replace('/', '.')
                    module_path = f"pyegeria.{module_path}"
                    
                    if module_path not in modules:
                        modules[module_path] = {
                            'path': module_path,
                            'file_path': file_path,
                            'elements': [],
                            'score': result.get('score', 0.0)
                        }
                    
                    element_type = metadata.get('element_type', '')
                    element_name = metadata.get('name', '')
                    if element_name:
                        modules[module_path]['elements'].append({
                            'type': element_type,
                            'name': element_name,
                            'docstring': metadata.get('docstring', '')[:100]
                        })
        
        return modules
    
    def generate_response(
        self,
        query: str,
        query_result: PyEgeriaQueryResult
    ) -> Dict[str, Any]:
        """
        Generate intelligent response based on query type and search results.
        
        Args:
            query: Original user query
            query_result: Classified query with search results
            
        Returns:
            Response dictionary with answer and metadata
        """
        query_type = query_result.query_type
        results = query_result.search_results
        
        if not results:
            return {
                'answer': (
                    "I couldn't find specific information about that in the PyEgeria collection. "
                    "Could you rephrase your question or ask about a specific PyEgeria class, "
                    "method, or module?"
                ),
                'sources': [],
                'query_type': query_type,
                'confidence': 0.0
            }
        
        # Build context from search results
        context = self._build_context(results, query_type)
        
        # Generate response using LLM
        prompt = self._build_prompt(query, query_type, context)
        
        try:
            response = self.llm_client.generate(
                prompt=prompt,
                temperature=0.3,  # Lower temperature for more factual responses
                max_tokens=800
            )
            
            # Extract sources
            sources = self._extract_sources(results)
            
            # Add helpful suggestions based on query type
            suggestions = self._generate_suggestions(query_type, results)
            
            return {
                'answer': response,
                'sources': sources,
                'query_type': query_type,
                'confidence': query_result.confidence,
                'suggestions': suggestions
            }
            
        except Exception as e:
            logger.error(f"Error generating PyEgeria response: {e}")
            return {
                'answer': f"Error generating response: {str(e)}",
                'sources': [],
                'query_type': query_type,
                'confidence': 0.0
            }
    
    def _build_context(self, results: List[Dict[str, Any]], query_type: str) -> str:
        """Build context string from search results based on query type."""
        context_parts = []
        
        if query_type == 'class':
            classes = self.extract_class_info(results)
            for class_name, class_info in list(classes.items())[:3]:  # Top 3 classes
                context_parts.append(f"\nClass: {class_name}")
                context_parts.append(f"File: {class_info['file_path']}")
                if class_info['docstring']:
                    context_parts.append(f"Description: {class_info['docstring'][:200]}")
                
                # Get ALL methods for this class using comprehensive search
                all_methods = self.get_all_class_methods(class_name)
                if all_methods:
                    method_names = [m['name'] for m in all_methods]
                    context_parts.append(f"Methods ({len(method_names)}): {', '.join(method_names)}")
                    # Include details for top methods
                    for method in all_methods[:10]:  # Show details for first 10
                        if method.get('docstring'):
                            context_parts.append(f"  - {method['name']}: {method['docstring'][:100]}")
                elif class_info['methods']:
                    # Fallback to methods from initial search
                    methods = [m['name'] for m in class_info['methods'][:5]]
                    context_parts.append(f"Key methods: {', '.join(methods)}")
        
        elif query_type == 'module':
            modules = self.extract_module_info(results)
            for module_path, module_info in list(modules.items())[:3]:  # Top 3 modules
                context_parts.append(f"\nModule: {module_path}")
                context_parts.append(f"File: {module_info['file_path']}")
                if module_info['elements']:
                    elements = [f"{e['type']}: {e['name']}" for e in module_info['elements'][:5]]
                    context_parts.append(f"Contains: {', '.join(elements)}")
        
        else:
            # For other query types, include relevant code snippets and documentation
            for i, result in enumerate(results[:5], 1):
                metadata = result.get('metadata', {})
                context_parts.append(f"\n[Result {i}]")
                context_parts.append(f"Type: {metadata.get('element_type', 'unknown')}")
                context_parts.append(f"Name: {metadata.get('name', 'N/A')}")
                context_parts.append(f"File: {metadata.get('file_path', 'N/A')}")
                
                if metadata.get('docstring'):
                    context_parts.append(f"Documentation: {metadata['docstring'][:150]}")
                
                if metadata.get('code'):
                    context_parts.append(f"Code:\n{metadata['code'][:200]}")
        
        return '\n'.join(context_parts)
    
    def _build_prompt(self, query: str, query_type: str, context: str) -> str:
        """Build prompt for LLM based on query type."""
        
        # Special instructions for class queries
        if query_type == 'class':
            base_prompt = f"""You are an expert on the PyEgeria Python library for Egeria.

User Query: {query}
Query Type: {query_type}

Relevant PyEgeria Information:
{context}

Instructions for Class Method Queries:
1. FIRST: Create a complete table listing ALL methods shown in the context above
   - Use markdown table format: | Method Name | Description |
   - List EVERY method mentioned in the "Methods" section
   - Keep descriptions brief (one line each)

2. THEN: Provide detailed examples for 2-3 key methods
   - Show method signatures
   - Explain parameters
   - Include usage examples if helpful

3. FINALLY: Note that PyEgeria provides both sync and async versions
   - Mention hey_egeria CLI and Dr. Egeria alternatives

Format:
## All Methods in [ClassName]

| Method | Description |
|--------|-------------|
| method1 | Brief description |
| method2 | Brief description |
...

## Detailed Examples

[Show 2-3 detailed method examples]

Answer:"""
        else:
            base_prompt = f"""You are an expert on the PyEgeria Python library for Egeria.

User Query: {query}
Query Type: {query_type}

Relevant PyEgeria Information:
{context}

Instructions:
- Provide a clear, accurate answer based on the PyEgeria information above
- Include specific class names, method names, and file paths when relevant
- If showing code, use proper Python syntax
- Mention that PyEgeria provides both synchronous and asynchronous clients
- Note that operations may also be available via hey_egeria CLI or Dr. Egeria
- Be concise but complete

Answer:"""
        
        return base_prompt
    
    def _extract_sources(self, results: List[Dict[str, Any]]) -> List[str]:
        """Extract unique source file paths from results."""
        sources = []
        seen = set()
        
        for result in results[:5]:  # Top 5 sources
            metadata = result.get('metadata', {})
            file_path = metadata.get('file_path', '')
            element_name = metadata.get('name', '')
            
            if file_path and file_path not in seen:
                source = file_path
                if element_name:
                    source = f"{file_path} ({element_name})"
                sources.append(source)
                seen.add(file_path)
        
        return sources
    
    def _generate_suggestions(self, query_type: str, results: List[Dict[str, Any]]) -> List[str]:
        """Generate helpful suggestions based on query type and results."""
        suggestions = []
        
        if query_type == 'class':
            classes = self.extract_class_info(results)
            if len(classes) > 1:
                other_classes = [name for name in list(classes.keys())[1:4]]
                if other_classes:
                    suggestions.append(f"Related classes: {', '.join(other_classes)}")
        
        elif query_type == 'method':
            suggestions.append("Would you like to see a complete code example?")
            suggestions.append("Ask about error handling or best practices")
        
        elif query_type == 'usage':
            suggestions.append("Would you like to see test examples from the tests/ directory?")
            suggestions.append("Ask about async vs sync client usage")
        
        elif query_type == 'example':
            suggestions.append("Check the tests/ directory for more examples")
            suggestions.append("Ask about specific use cases or scenarios")
        
        return suggestions
    
    def answer(self, query: str) -> Dict[str, Any]:
        """
        Answer a PyEgeria-related query.
        
        Args:
            query: User's question about PyEgeria
            
        Returns:
            Response dictionary with answer, sources, and metadata
        """
        logger.info(f"PyEgeria Agent processing query: {query[:100]}...")
        
        # Classify query type
        query_type = self.classify_query(query)
        logger.info(f"Classified as: {query_type}")
        
        # Search PyEgeria collection
        results = self.search_pyegeria(query)
        
        # Calculate confidence based on results
        confidence = 0.0
        if results:
            # Average of top 3 scores
            top_scores = [r.get('score', 0.0) for r in results[:3]]
            confidence = sum(top_scores) / len(top_scores) if top_scores else 0.0
        
        # Create query result
        query_result = PyEgeriaQueryResult(
            query_type=query_type,
            search_results=results,
            confidence=confidence
        )
        
        # Generate response
        response = self.generate_response(query, query_result)
        
        logger.info(f"Generated PyEgeria response with confidence: {confidence:.2f}")
        return response


# Singleton instance
_pyegeria_agent: Optional[PyEgeriaAgent] = None


def get_pyegeria_agent() -> PyEgeriaAgent:
    """Get or create singleton PyEgeria agent instance."""
    global _pyegeria_agent
    if _pyegeria_agent is None:
        _pyegeria_agent = PyEgeriaAgent()
    return _pyegeria_agent