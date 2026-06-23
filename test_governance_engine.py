#!/usr/bin/env python3
"""
Unit Tests for Governance Rules Engine
=======================================
Tests the rules engine WITHOUT needing a live DataHub instance.
Uses mock data and dependency injection.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))

from governance_engine import (
    ConditionEvaluator,
    Condition,
    Operator,
    GovernanceRuleEngine,
    Rule,
    Action,
)


class TestConditionEvaluator(unittest.TestCase):
    """Test individual condition evaluators."""
    
    def setUp(self):
        self.evaluator = ConditionEvaluator()
        
        # Sample dataset for testing
        self.dataset = {
            'name': 'test_table',
            'platform': 'postgres',
            'description': 'A test dataset with description',
            'owners': ['user@company.com'],
            'fields': [
                {'name': 'id', 'type': 'integer'},
                {'name': 'name', 'type': 'string'},
                {'name': 'email', 'type': 'string'},
            ],
            'tags': ['test-tag']
        }
        
        # Dataset with missing data
        self.incomplete_dataset = {
            'name': 'bad_table',
            'platform': 'snowflake',
            'description': '',
            'owners': [],
            'fields': [],
            'tags': []
        }
    
    def test_hasOwner_true(self):
        """Test hasOwner condition when dataset has owners."""
        condition = Condition('hasOwner', 'equals', True)
        result = self.evaluator.evaluate(condition, self.dataset)
        self.assertTrue(result)
    
    def test_hasOwner_false(self):
        """Test hasOwner condition when dataset has no owners."""
        condition = Condition('hasOwner', 'equals', True)
        result = self.evaluator.evaluate(condition, self.incomplete_dataset)
        self.assertFalse(result)
    
    def test_hasDescription_true(self):
        """Test hasDescription condition when description exists."""
        condition = Condition('hasDescription', 'equals', True)
        result = self.evaluator.evaluate(condition, self.dataset)
        self.assertTrue(result)
    
    def test_hasDescription_false(self):
        """Test hasDescription when description is empty."""
        condition = Condition('hasDescription', 'equals', True)
        result = self.evaluator.evaluate(condition, self.incomplete_dataset)
        self.assertFalse(result)
    
    def test_fieldCount_greater_than(self):
        """Test fieldCount with greater_than operator."""
        condition = Condition('fieldCount', 'greater_than', 2)
        result = self.evaluator.evaluate(condition, self.dataset)
        self.assertTrue(result)
    
    def test_fieldCount_less_than(self):
        """Test fieldCount with less_than operator."""
        condition = Condition('fieldCount', 'less_than', 1)
        result = self.evaluator.evaluate(condition, self.incomplete_dataset)
        self.assertTrue(result)
    
    def test_platform_equals(self):
        """Test platform equality check."""
        condition = Condition('platform', 'equals', 'postgres')
        result = self.evaluator.evaluate(condition, self.dataset)
        self.assertTrue(result)
    
    def test_platform_not_equals(self):
        """Test platform not equals check."""
        condition = Condition('platform', 'not_equals', 'mysql')
        result = self.evaluator.evaluate(condition, self.dataset)
        self.assertTrue(result)
    
    def test_hasTag_contains(self):
        """Test tag contains check."""
        condition = Condition('hasTag', 'contains', 'test-tag')
        result = self.evaluator.evaluate(condition, self.dataset)
        self.assertTrue(result)
    
    def test_nameContains(self):
        """Test name contains substring."""
        condition = Condition('nameContains', 'contains', 'test')
        result = self.evaluator.evaluate(condition, self.dataset)
        self.assertTrue(result)
    
    def test_compare_operators(self):
        """Test all comparison operators."""
        # Test equals
        self.assertTrue(self.evaluator._compare(5, 'equals', 5))
        self.assertFalse(self.evaluator._compare(5, 'equals', 3))
        
        # Test not_equals
        self.assertTrue(self.evaluator._compare(5, 'not_equals', 3))
        
        # Test greater_than
        self.assertTrue(self.evaluator._compare(5, 'greater_than', 3))
        self.assertFalse(self.evaluator._compare(3, 'greater_than', 5))
        
        # Test less_than
        self.assertTrue(self.evaluator._compare(3, 'less_than', 5))
        
        # Test contains
        self.assertTrue(self.evaluator._compare('hello world', 'contains', 'world'))
        
        # Test exists
        self.assertTrue(self.evaluator._compare('something', 'exists', None))
    
    def test_extensibility_new_evaluator(self):
        """Test that new evaluators can be added dynamically."""
        # Add a new evaluator dynamically
        def evaluate_customCheck(self, condition, dataset):
            return True  # Always passes
        
        # Bind it to the evaluator
        import types
        self.evaluator.evaluate_customCheck = types.MethodType(
            evaluate_customCheck, self.evaluator
        )
        self.evaluator._register_evaluators()
        
        # Test it
        condition = Condition('customCheck', 'equals', True)
        result = self.evaluator.evaluate(condition, self.dataset)
        self.assertTrue(result)


class TestGovernanceRuleEngine(unittest.TestCase):
    """Test the full rules engine with mock DataHub."""
    
    def setUp(self):
        # Sample datasets
        self.datasets = [
            {
                'name': 'good_dataset',
                'platform': 'postgres',
                'description': 'Well documented dataset',
                'owners': ['data.team@company.com'],
                'fields': [
                    {'name': 'id', 'type': 'integer'},
                    {'name': 'name', 'type': 'string'},
                    {'name': 'date', 'type': 'date'},
                ],
                'tags': []
            },
            {
                'name': 'bad_dataset',
                'platform': 'snowflake',
                'description': '',
                'owners': [],
                'fields': [],
                'tags': []
            }
        ]
        
        # Create a sample rule
        self.sample_rules = [
            Rule(
                name="Test Rule",
                description="Rule for testing",
                enabled=True,
                filter={},
                conditions=[
                    Condition('hasOwner', 'equals', True),
                    Condition('hasDescription', 'equals', True),
                ],
                on_pass=[Action('add_tag', 'urn:li:tag:Passed')],
                on_fail=[Action('add_tag', 'urn:li:tag:Failed')]
            )
        ]
    
    def test_rule_evaluation_pass(self):
        """Test that a compliant dataset passes the rule."""
        evaluator = ConditionEvaluator()
        
        # Manually evaluate
        dataset = self.datasets[0]  # good_dataset
        conditions = [
            Condition('hasOwner', 'equals', True),
            Condition('hasDescription', 'equals', True),
        ]
        
        results = [evaluator.evaluate(c, dataset) for c in conditions]
        self.assertTrue(all(results))
    
    def test_rule_evaluation_fail(self):
        """Test that a non-compliant dataset fails the rule."""
        evaluator = ConditionEvaluator()
        
        # Manually evaluate
        dataset = self.datasets[1]  # bad_dataset
        conditions = [
            Condition('hasOwner', 'equals', True),
            Condition('hasDescription', 'equals', True),
        ]
        
        results = [evaluator.evaluate(c, dataset) for c in conditions]
        self.assertFalse(all(results))
    
    @patch('governance_engine.DatahubRestEmitter')
    @patch('governance_engine.GovernanceRuleEngine._load_rules')
    def test_engine_with_mock_datahub(self, mock_load_rules, mock_emitter):
        """Test full engine with mocked DataHub."""
        # Mock the rules loading
        mock_load_rules.return_value = self.sample_rules
        
        # Create engine in dry-run mode
        engine = GovernanceRuleEngine(
            rules_file="dummy.yaml",
            datahub_server="http://localhost:8080",
            dry_run=True
        )
        
        # Run engine
        results = engine.run(self.datasets)
        
        # Verify results
        self.assertEqual(results['total_datasets'], 2)
        self.assertGreater(results['evaluations'], 0)
        
        # Good dataset should pass
        self.assertGreater(results['passed'], 0)
        
        # Bad dataset should fail
        self.assertGreater(results['failed'], 0)
    
    @patch('governance_engine.GovernanceRuleEngine._load_rules')
    def test_filter_matching(self, mock_load_rules):
        """Test that filters work correctly."""
        # Create a rule with a platform filter
        filtered_rule = Rule(
            name="Filtered Rule",
            description="Only for snowflake",
            enabled=True,
            filter={'platform': 'snowflake'},
            conditions=[Condition('hasOwner', 'equals', True)],
            on_pass=[Action('add_tag', 'urn:li:tag:Passed')],
            on_fail=[Action('add_tag', 'urn:li:tag:Failed')]
        )
        
        mock_load_rules.return_value = [filtered_rule]
        
        engine = GovernanceRuleEngine(
            rules_file="dummy.yaml",
            datahub_server="http://localhost:8080",
            dry_run=True
        )
        
        # Test filter matching
        self.assertTrue(engine._matches_filter(
            self.datasets[1],  # snowflake dataset
            {'platform': 'snowflake'}
        ))
        
        self.assertFalse(engine._matches_filter(
            self.datasets[0],  # postgres dataset
            {'platform': 'snowflake'}
        ))
    
    def test_comparison_operators_edge_cases(self):
        """Test edge cases for comparison operators."""
        evaluator = ConditionEvaluator()
        
        # Test with None values
        condition = Condition('nonExistent', 'equals', True)
        result = evaluator.evaluate(condition, {})
        self.assertFalse(result)
        
        # Test with empty strings
        condition = Condition('description', 'equals', '')
        result = evaluator.evaluate(condition, {'description': ''})
        self.assertTrue(result)
        
        # Test with zero
        condition = Condition('fieldCount', 'equals', 0)
        result = evaluator.evaluate(condition, {'fields': []})
        self.assertTrue(result)


class TestExtensibility(unittest.TestCase):
    """Demonstrate how to add new rule types without modifying the engine."""
    
    def test_adding_new_evaluator(self):
        """Show how to add a new condition evaluator dynamically."""
        evaluator = ConditionEvaluator()
        
        # STEP 1: Define a new evaluator function
        def evaluate_dataQuality(self, condition, dataset):
            """Check data quality score."""
            quality_score = dataset.get('quality_score', 0)
            return quality_score >= condition.expected
        
        # STEP 2: Bind it to the evaluator instance
        import types
        evaluator.evaluate_dataQuality = types.MethodType(
            evaluate_dataQuality, evaluator
        )
        
        # STEP 3: Re-register evaluators
        evaluator._register_evaluators()
        
        # STEP 4: Use the new evaluator
        dataset_with_quality = {
            'name': 'quality_dataset',
            'quality_score': 85
        }
        
        condition = Condition('dataQuality', 'greater_than', 80)
        result = evaluator.evaluate(condition, dataset_with_quality)
        self.assertTrue(result)
        
        # This required NO changes to the core engine code!


if __name__ == '__main__':
    # Run tests
    print("\n" + "=" * 70)
    print("  GOVERNANCE RULES ENGINE - UNIT TESTS")
    print("=" * 70 + "\n")
    
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestConditionEvaluator))
    suite.addTests(loader.loadTestsFromTestCase(TestGovernanceRuleEngine))
    suite.addTests(loader.loadTestsFromTestCase(TestExtensibility))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Summary
    print("\n" + "=" * 70)
    print(f"  Tests run: {result.testsRun}")
    print(f"  Passed: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"  Failed: {len(result.failures)}")
    print(f"  Errors: {len(result.errors)}")
    print("=" * 70 + "\n")