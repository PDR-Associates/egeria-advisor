#!/usr/bin/env python3
"""
Test script for Phase 1 feedback system enhancements.

Tests star ratings, categories, MLflow integration, and dashboard display.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.feedback_collector import get_feedback_collector
from loguru import logger

def test_feedback_enhancements():
    """Test Phase 1 feedback enhancements."""
    
    logger.info("Testing Phase 1 Feedback System Enhancements")
    logger.info("=" * 60)
    
    collector = get_feedback_collector()
    
    # Test 1: Record feedback with star rating
    logger.info("\n1. Testing star rating feedback...")
    success = collector.record_feedback(
        query="How do I configure Egeria?",
        query_type="HOW_TO",
        collections_searched=["egeria_docs"],
        response_length=500,
        rating="positive",
        star_rating=5,
        category="accuracy",
        feedback_text="Very helpful and accurate response!"
    )
    logger.info(f"   Star rating feedback recorded: {success}")
    
    # Test 2: Record feedback with different category
    logger.info("\n2. Testing category-based feedback...")
    success = collector.record_feedback(
        query="What is a repository connector?",
        query_type="CONCEPT",
        collections_searched=["egeria_docs"],
        response_length=300,
        rating="positive",
        star_rating=4,
        category="completeness",
        feedback_text="Good explanation but could use more examples"
    )
    logger.info(f"   Category feedback recorded: {success}")
    
    # Test 3: Record negative feedback
    logger.info("\n3. Testing negative feedback...")
    success = collector.record_feedback(
        query="How to deploy Egeria on Kubernetes?",
        query_type="HOW_TO",
        collections_searched=["egeria_docs"],
        response_length=200,
        rating="negative",
        star_rating=2,
        category="clarity",
        feedback_text="Response was confusing and lacked clear steps"
    )
    logger.info(f"   Negative feedback recorded: {success}")
    
    # Test 4: Record neutral feedback without star rating
    logger.info("\n4. Testing neutral feedback (no star rating)...")
    success = collector.record_feedback(
        query="What is metadata?",
        query_type="CONCEPT",
        collections_searched=["egeria_docs"],
        response_length=250,
        rating="neutral",
        feedback_text="Okay response, nothing special"
    )
    logger.info(f"   Neutral feedback recorded: {success}")
    
    # Test 5: Get feedback statistics
    logger.info("\n5. Testing feedback statistics...")
    stats = collector.get_feedback_stats()
    
    logger.info(f"\n   Total feedback entries: {stats['total']}")
    logger.info(f"   Positive: {stats['positive']}")
    logger.info(f"   Negative: {stats['negative']}")
    logger.info(f"   Neutral: {stats['neutral']}")
    logger.info(f"   Satisfaction rate: {stats['satisfaction_rate']:.1%}")
    
    if stats['avg_star_rating'] > 0:
        logger.info(f"   Average star rating: {stats['avg_star_rating']:.2f}/5.0")
        stars = "⭐" * int(round(stats['avg_star_rating']))
        logger.info(f"   Visual rating: {stars}")
    
    # Test 6: Category statistics
    if stats['by_category']:
        logger.info("\n6. Category-specific statistics:")
        for category, data in stats['by_category'].items():
            logger.info(f"   {category.upper()}:")
            logger.info(f"     Total: {data['total']}")
            logger.info(f"     Positive: {data.get('positive', 0)}")
            if category in stats['category_star_ratings']:
                logger.info(f"     Avg stars: {stats['category_star_ratings'][category]:.2f}/5.0")
    
    # Test 7: Validation
    logger.info("\n7. Testing validation...")
    
    # Invalid star rating
    success = collector.record_feedback(
        query="Test query",
        query_type="GENERAL",
        collections_searched=["test"],
        response_length=100,
        rating="positive",
        star_rating=10,  # Invalid - should be 1-5
        category="accuracy"
    )
    logger.info(f"   Invalid star rating handled: {success}")
    
    # Invalid category
    success = collector.record_feedback(
        query="Test query 2",
        query_type="GENERAL",
        collections_searched=["test"],
        response_length=100,
        rating="positive",
        star_rating=3,
        category="invalid_category"  # Invalid
    )
    logger.info(f"   Invalid category handled: {success}")
    
    logger.info("\n" + "=" * 60)
    logger.info("✅ Phase 1 Feedback System Tests Complete!")
    logger.info("\nNext steps:")
    logger.info("1. Run the dashboard to see feedback stats: ./scripts/run_dashboard.sh")
    logger.info("2. Check MLflow UI for logged feedback metrics")
    logger.info("3. Review feedback file: data/feedback/user_feedback.jsonl")

if __name__ == "__main__":
    test_feedback_enhancements()