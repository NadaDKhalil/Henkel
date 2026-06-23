import pytest
from unittest.mock import Mock
import sys
sys.path.append('.')

from engine import ConditionEvaluator

class TestConditionEvaluator:
    def setup_method(self):
        self.mock_client = Mock()
        self.evaluator = ConditionEvaluator(self.mock_client)

    def test_hasOwner_with_owners(self):
        """Test hasOwner returns True when dataset has owners"""
        self.mock_client.execute_graphql.return_value = {
            "data": {
                "dataset": {
                    "ownership": {
                        "owners": [{"owner": {"username": "test_user"}}]
                    }
                }
            }
        }
        result = self.evaluator._evaluate_hasOwner("urn:li:dataset:test")
        assert result == True

    def test_hasOwner_without_owners(self):

        self.mock_client.execute_graphql.return_value = {
            "data": {
                "dataset": {
                    "ownership": {"owners": []}
                }
            }
        }
        result = self.evaluator._evaluate_hasOwner("urn:li:dataset:test")
        assert result == False

    def test_hasDescription_with_description(self):

        self.mock_client.execute_graphql.return_value = {
            "data": {
                "dataset": {
                    "properties": {"description": "Test description"}
                }
            }
        }
        result = self.evaluator._evaluate_hasDescription("urn:li:dataset:test")
        assert result == True

    def test_hasDescription_without_description(self):

        self.mock_client.execute_graphql.return_value = {
            "data": {
                "dataset": {
                    "properties": {"description": ""}
                }
            }
        }
        result = self.evaluator._evaluate_hasDescription("urn:li:dataset:test")
        assert result == False

    def test_hasTag_with_tags(self):

        self.mock_client.execute_graphql.return_value = {
            "data": {
                "dataset": {
                    "tags": {
                        "tags": [{"tag": {"name": "test_tag"}}]
                    }
                }
            }
        }
        result = self.evaluator._evaluate_hasTag("urn:li:dataset:test")
        assert result == True

    def test_hasTag_without_tags(self):

        self.mock_client.execute_graphql.return_value = {
            "data": {
                "dataset": {
                    "tags": {"tags": []}
                }
            }
        }
        result = self.evaluator._evaluate_hasTag("urn:li:dataset:test")
        assert result == False
