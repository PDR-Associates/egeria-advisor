"""
User feedback collection system for continuous improvement.

This module captures user feedback on query responses to improve
routing accuracy and response quality over time.
"""

from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
import json
from loguru import logger


@dataclass
class FeedbackEntry:
    """Single feedback entry."""
    timestamp: str
    query: str
    query_type: str
    collections_searched: List[str]
    response_length: int
    rating: str  # "positive", "negative", "neutral"
    feedback_text: Optional[str] = None  # User's free-text comment
    suggested_collection: Optional[str] = None  # Better collection suggestion
    session_id: Optional[str] = None
    user_comment: Optional[str] = None  # Additional user comment/explanation
    # Phase 1 enhancements
    star_rating: Optional[int] = None  # 1-5 star rating
    category: Optional[str] = None  # accuracy, completeness, clarity, relevance
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    def get_normalized_rating(self) -> float:
        """
        Get normalized rating score (0-1).
        
        Returns:
            Normalized rating between 0 and 1
        """
        if self.star_rating is not None:
            return self.star_rating / 5.0
        elif self.rating == "positive":
            return 1.0
        elif self.rating == "negative":
            return 0.0
        else:  # neutral
            return 0.5


class FeedbackCollector:
    """Collects and stores user feedback."""
    
    def __init__(self, feedback_file: Optional[Path] = None):
        """
        Initialize feedback collector.
        
        Args:
            feedback_file: Path to feedback JSON file
        """
        if feedback_file is None:
            feedback_file = Path("data/feedback/user_feedback.jsonl")
        
        self.feedback_file = feedback_file
        self.feedback_file.parent.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Initialized feedback collector: {self.feedback_file}")
    
    def record_feedback(
        self,
        query: str,
        query_type: str,
        collections_searched: List[str],
        response_length: int,
        rating: str,
        feedback_text: Optional[str] = None,
        suggested_collection: Optional[str] = None,
        session_id: Optional[str] = None,
        user_comment: Optional[str] = None,
        star_rating: Optional[int] = None,
        category: Optional[str] = None
    ) -> bool:
        """
        Record user feedback.
        
        Args:
            query: User's query
            query_type: Detected query type
            collections_searched: Collections that were searched
            response_length: Length of response in characters
            rating: "positive", "negative", or "neutral"
            feedback_text: Optional free-text feedback
            suggested_collection: User's suggested collection (if routing was wrong)
            session_id: Optional session identifier
            user_comment: Optional user comment
            star_rating: Optional 1-5 star rating
            category: Optional category (accuracy, completeness, clarity, relevance)
            
        Returns:
            True if feedback was recorded successfully
        """
        try:
            # Validate star rating if provided
            if star_rating is not None and not (1 <= star_rating <= 5):
                logger.warning(f"Invalid star rating {star_rating}, must be 1-5")
                star_rating = None
            
            # Validate category if provided
            valid_categories = {"accuracy", "completeness", "clarity", "relevance"}
            if category is not None and category not in valid_categories:
                logger.warning(f"Invalid category {category}, must be one of {valid_categories}")
                category = None
            
            entry = FeedbackEntry(
                timestamp=datetime.utcnow().isoformat(),
                query=query,
                query_type=query_type,
                collections_searched=collections_searched,
                response_length=response_length,
                rating=rating,
                feedback_text=feedback_text,
                suggested_collection=suggested_collection,
                session_id=session_id,
                user_comment=user_comment,
                star_rating=star_rating,
                category=category
            )
            
            # Append to JSONL file
            with open(self.feedback_file, 'a') as f:
                f.write(json.dumps(entry.to_dict()) + '\n')
            
            # Log to MLflow if available
            self.log_feedback_to_mlflow(entry)
            
            logger.info(f"Recorded {rating} feedback for query: {query[:50]}...")
            return True
            
        except Exception as e:
            logger.error(f"Failed to record feedback: {e}")
            return False
    
    def get_feedback_stats(self) -> Dict[str, Any]:
        """
        Get feedback statistics.
        
        Returns:
            Dictionary with feedback statistics
        """
        if not self.feedback_file.exists():
            return {
                "total": 0,
                "positive": 0,
                "negative": 0,
                "neutral": 0,
                "satisfaction_rate": 0.0
            }
        
        stats = {
            "total": 0,
            "positive": 0,
            "negative": 0,
            "neutral": 0,
            "by_query_type": {},
            "by_collection": {},
            "routing_corrections": [],
            # Phase 1 enhancements
            "star_ratings": [],
            "avg_star_rating": 0.0,
            "by_category": {},
            "category_star_ratings": {}
        }
        
        try:
            with open(self.feedback_file, 'r') as f:
                for line in f:
                    entry = json.loads(line)
                    stats["total"] += 1
                    
                    # Count by rating
                    rating = entry.get("rating", "neutral")
                    stats[rating] = stats.get(rating, 0) + 1
                    
                    # Track star ratings
                    star_rating = entry.get("star_rating")
                    if star_rating is not None:
                        stats["star_ratings"].append(star_rating)
                    
                    # Track by category
                    category = entry.get("category")
                    if category:
                        if category not in stats["by_category"]:
                            stats["by_category"][category] = {
                                "total": 0, "positive": 0, "negative": 0, "star_ratings": []
                            }
                        stats["by_category"][category]["total"] += 1
                        stats["by_category"][category][rating] = \
                            stats["by_category"][category].get(rating, 0) + 1
                        if star_rating is not None:
                            stats["by_category"][category]["star_ratings"].append(star_rating)
                    
                    # Count by query type
                    query_type = entry.get("query_type", "unknown")
                    if query_type not in stats["by_query_type"]:
                        stats["by_query_type"][query_type] = {
                            "total": 0, "positive": 0, "negative": 0
                        }
                    stats["by_query_type"][query_type]["total"] += 1
                    stats["by_query_type"][query_type][rating] = \
                        stats["by_query_type"][query_type].get(rating, 0) + 1
                    
                    # Count by collection
                    for collection in entry.get("collections_searched", []):
                        if collection not in stats["by_collection"]:
                            stats["by_collection"][collection] = {
                                "total": 0, "positive": 0, "negative": 0
                            }
                        stats["by_collection"][collection]["total"] += 1
                        stats["by_collection"][collection][rating] = \
                            stats["by_collection"][collection].get(rating, 0) + 1
                    
                    # Track routing corrections
                    if entry.get("suggested_collection"):
                        stats["routing_corrections"].append({
                            "query": entry["query"],
                            "searched": entry["collections_searched"],
                            "suggested": entry["suggested_collection"]
                        })
            
            # Calculate satisfaction rate
            if stats["total"] > 0:
                stats["satisfaction_rate"] = stats["positive"] / stats["total"]
            else:
                stats["satisfaction_rate"] = 0.0
            
            # Calculate average star rating
            if stats["star_ratings"]:
                stats["avg_star_rating"] = sum(stats["star_ratings"]) / len(stats["star_ratings"])
            
            # Calculate average star rating by category
            for category, data in stats["by_category"].items():
                if data["star_ratings"]:
                    stats["category_star_ratings"][category] = \
                        sum(data["star_ratings"]) / len(data["star_ratings"])
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get feedback stats: {e}")
            return stats
    
    def get_routing_improvements(self) -> List[Dict[str, Any]]:
        """
        Analyze feedback to suggest routing improvements.
        
        Returns:
            List of suggested routing improvements
        """
        improvements = []
        stats = self.get_feedback_stats()
        
        # Analyze routing corrections
        for correction in stats.get("routing_corrections", []):
            improvements.append({
                "type": "routing_correction",
                "query": correction["query"],
                "current_routing": correction["searched"],
                "suggested_routing": correction["suggested"],
                "action": f"Add domain term or boost {correction['suggested']} for similar queries"
            })
        
        # Analyze low-satisfaction collections
        for collection, data in stats.get("by_collection", {}).items():
            if data["total"] >= 5:  # Minimum sample size
                satisfaction = data.get("positive", 0) / data["total"]
                if satisfaction < 0.5:
                    improvements.append({
                        "type": "low_satisfaction",
                        "collection": collection,
                        "satisfaction_rate": satisfaction,
                        "total_queries": data["total"],
                        "action": f"Review prompt template for {collection} collection"
                    })
        
        # Analyze low-satisfaction query types
        for query_type, data in stats.get("by_query_type", {}).items():
            if data["total"] >= 5:
                satisfaction = data.get("positive", 0) / data["total"]
                if satisfaction < 0.5:
                    improvements.append({
                        "type": "low_satisfaction_query_type",
                        "query_type": query_type,
                        "satisfaction_rate": satisfaction,
                        "total_queries": data["total"],
                        "action": f"Review query-type instructions for {query_type}"
                    })
        
        return improvements
    
    def export_feedback(self, output_file: Path) -> bool:
        """
        Export feedback to a different format.
        
        Args:
            output_file: Path to output file (JSON or CSV)
            
        Returns:
            True if export was successful
        """
        try:
            if not self.feedback_file.exists():
                logger.warning("No feedback file to export")
                return False
            
            feedback_entries = []
            with open(self.feedback_file, 'r') as f:
                for line in f:
                    feedback_entries.append(json.loads(line))
            
            if output_file.suffix == '.json':
                with open(output_file, 'w') as f:
                    json.dump(feedback_entries, f, indent=2)
            elif output_file.suffix == '.csv':
                import csv
                if feedback_entries:
                    keys = feedback_entries[0].keys()
                    with open(output_file, 'w', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=keys)
                        writer.writeheader()
                        writer.writerows(feedback_entries)
            else:
                logger.error(f"Unsupported export format: {output_file.suffix}")
                return False
            
            logger.info(f"Exported {len(feedback_entries)} feedback entries to {output_file}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to export feedback: {e}")
    
    def log_feedback_to_mlflow(
        self,
        entry: FeedbackEntry,
        mlflow_tracker=None
    ) -> bool:
        """
        Log feedback entry to MLflow for correlation with query metrics.
        
        Args:
            entry: Feedback entry to log
            mlflow_tracker: Optional MLflow tracker instance
            
        Returns:
            True if logged successfully
        """
        try:
            if mlflow_tracker is None:
                from advisor.mlflow_tracking import get_mlflow_tracker
                mlflow_tracker = get_mlflow_tracker()
            
            if not mlflow_tracker.enabled:
                return False
            
            # Create metrics dict
            metrics = {
                "feedback_normalized_score": entry.get_normalized_rating(),
            }
            
            if entry.star_rating is not None:
                metrics["feedback_star_rating"] = float(entry.star_rating)
            
            # Log metrics
            mlflow_tracker.log_metrics(metrics)
            
            # Log feedback details as artifact
            feedback_dict = {
                "timestamp": entry.timestamp,
                "query": entry.query,
                "query_type": entry.query_type,
                "collections_searched": entry.collections_searched,
                "rating": entry.rating,
                "star_rating": entry.star_rating,
                "category": entry.category,
                "feedback_text": entry.feedback_text,
                "user_comment": entry.user_comment,
                "suggested_collection": entry.suggested_collection,
            }
            mlflow_tracker.log_dict(feedback_dict, "user_feedback.json")
            
            logger.debug(f"Logged feedback to MLflow: {entry.rating}")
            return True
            
        except Exception as e:
            logger.warning(f"Failed to log feedback to MLflow: {e}")
            return False
            return False


# Singleton instance
_feedback_collector: Optional[FeedbackCollector] = None


def get_feedback_collector() -> FeedbackCollector:
    """Get singleton feedback collector instance."""
    global _feedback_collector
    if _feedback_collector is None:
        _feedback_collector = FeedbackCollector()
    return _feedback_collector


def record_positive_feedback(
    query: str,
    query_type: str,
    collections_searched: List[str],
    response_length: int,
    feedback_text: Optional[str] = None,
    session_id: Optional[str] = None
) -> bool:
    """Convenience function to record positive feedback."""
    collector = get_feedback_collector()
    return collector.record_feedback(
        query=query,
        query_type=query_type,
        collections_searched=collections_searched,
        response_length=response_length,
        rating="positive",
        feedback_text=feedback_text,
        session_id=session_id
    )


def record_negative_feedback(
    query: str,
    query_type: str,
    collections_searched: List[str],
    response_length: int,
    feedback_text: Optional[str] = None,
    suggested_collection: Optional[str] = None,
    session_id: Optional[str] = None
) -> bool:
    """Convenience function to record negative feedback."""
    collector = get_feedback_collector()
    return collector.record_feedback(
        query=query,
        query_type=query_type,
        collections_searched=collections_searched,
        response_length=response_length,
        rating="negative",
        feedback_text=feedback_text,
        suggested_collection=suggested_collection,
        session_id=session_id
    )