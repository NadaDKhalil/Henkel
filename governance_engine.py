#!/usr/bin/env python3

import logging
import sys
import time
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

import yaml
import requests
from datahub.emitter.mce_builder import make_dataset_urn, make_tag_urn
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import (
    GlobalTagsClass,
    TagAssociationClass,
    ChangeTypeClass,
    AuditStampClass,
)


class Operator(Enum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"



@dataclass
class Condition:
    property: str
    operator: str
    expected: Any = None


@dataclass
class Action:
    action: str
    tag: str
    description: str = ""


@dataclass
class Rule:  
    name: str   
    enabled: bool
    filter: Dict[str, Any]
    conditions: List[Condition]
    on_pass: List[Action]
    on_fail: List[Action]


class ConditionEvaluator:

    
    def __init__(self):
        self._evaluators: Dict[str, Callable] = {}
        self._register_evaluators()
    
    def _register_evaluators(self):
        for method_name in dir(self):
            if method_name.startswith('evaluate_'):
                property_name = method_name.replace('evaluate_', '')
                self._evaluators[property_name] = getattr(self, method_name)
    
    def evaluate(self, condition: Condition, dataset: Dict[str, Any]) -> bool:
        evaluator = self._evaluators.get(condition.property)
        if not evaluator:
            actual_value = dataset.get(condition.property)
            if actual_value is None:
                return False
            return self._compare(actual_value, condition.operator, condition.expected)
        
        return evaluator(condition, dataset)
    
    def _compare(self, actual: Any, operator: str, expected: Any) -> bool:
        """Compare actual value against expected using operator."""
        try:
            op = Operator(operator)
        except ValueError:
            raise ValueError(f"Unknown operator: {operator}")
        
        if op == Operator.EQUALS:
            return actual == expected
        elif op == Operator.NOT_EQUALS:
            return actual != expected
        elif op == Operator.GREATER_THAN:
            return actual > expected
        elif op == Operator.LESS_THAN:
            return actual < expected
        return False
    
    
    def evaluate_hasOwner(self, condition: Condition, dataset: Dict) -> bool:
        owners = dataset.get('owners', [])
        return self._compare(
            len(owners) > 0,
            condition.operator,
            condition.expected
        )
    
    def evaluate_hasDescription(self, condition: Condition, dataset: Dict) -> bool:
        description = dataset.get('description', '')
        return self._compare(
            bool(description and description.strip()),
            condition.operator,
            condition.expected
        )
    
    def evaluate_fieldCount(self, condition: Condition, dataset: Dict) -> bool:
        fields = dataset.get('fields', [])
        return self._compare(
            len(fields),
            condition.operator,
            condition.expected
        )
    
    def evaluate_platform(self, condition: Condition, dataset: Dict) -> bool:
        """Check the dataset platform."""
        return self._compare(
            dataset.get('platform', ''),
            condition.operator,
            condition.expected
        )
    

class GovernanceRuleEngine:
    
    def __init__(
        self,
        rules_file: str,
        datahub_server: str,
        dry_run: bool = False,
        token: Optional[str] = None
    ):
        self.rules_file = rules_file
        self.datahub_server = datahub_server
        self.dry_run = dry_run
        self.token = token       
        self.logger = logging.getLogger('GovernanceEngine')
        self.evaluator = ConditionEvaluator()

        if not dry_run:
            self.emitter = DatahubRestEmitter(gms_server=datahub_server, token=token)
        else:
            self.emitter = None
        self.rules = self._load_rules()
    
    def _load_rules(self) -> List[Rule]:
        try:
            with open(self.rules_file, 'r') as f:
                config = yaml.safe_load(f)
            
            rules = []
            for rule_data in config.get('rules', []):
                if not rule_data.get('enabled', True):
                    continue
                conditions = []
                for cond in rule_data.get('conditions', []):
                    conditions.append(Condition(
                        property=cond['property'],
                        operator=cond.get('operator', 'equals'),
                        expected=cond.get('expected')
                    ))
                
                on_pass = []
                for action in rule_data.get('on_pass', []):
                    on_pass.append(Action(
                        action=action['action'],
                        tag=action['tag'],
                        description=action.get('description', '')
                    ))
                
                on_fail = []
                for action in rule_data.get('on_fail', []):
                    on_fail.append(Action(
                        action=action['action'],
                        tag=action['tag'],
                        description=action.get('description', '')
                    ))
                
                rules.append(Rule(
                    name=rule_data['name'],
                    description=rule_data.get('description', ''),
                    enabled=rule_data.get('enabled', True),
                    filter=rule_data.get('filter', {}),
                    conditions=conditions,
                    on_pass=on_pass,
                    on_fail=on_fail
                ))
            
            self.logger.info(f"Loaded {len(rules)} rules")
            return rules
            
        except Exception as e:
            self.logger.error(f"Failed to load rules: {e}")
            raise
    
    def run(self, datasets: List[Dict[str, Any]]) -> Dict[str, Any]:
        self.logger.info(f"Running {len(self.rules)} on {len(datasets)} ")        
        results = {
            'total_rules': len(self.rules),
            'total_datasets': len(datasets),
            'evaluations': 0,
            'passed': 0,
            'failed': 0,
            'actions_applied': 0,
            'errors': 0,
            'details': []
        }
        
        for rule in self.rules:
            self.logger.info(f"\Rule: {rule.name}")

            rule_result = {
                'rule': rule.name,
                'datasets_evaluated': 0,
                'passed': 0,
                'failed': 0,
                'actions': 0
            }
            
            for dataset in datasets:
                if not self._matches_filter(dataset, rule.filter):
                    continue
                
                rule_result['datasets_evaluated'] += 1
                results['evaluations'] += 1
                
                try:
                    passed = self._evaluate_rule(rule, dataset)
                    
                    if passed:
                        results['passed'] += 1
                        rule_result['passed'] += 1
                        actions = rule.on_pass
                        status = "PASS"
                    else:
                        results['failed'] += 1
                        rule_result['failed'] += 1
                        actions = rule.on_fail
                        status = "FAIL"
                    
                    for action in actions:
                        self._apply_action(dataset, action)
                        results['actions_applied'] += 1
                        rule_result['actions'] += 1
                    
                    self.logger.info(
                        f"   [{status}] {dataset['name']} - "
                        f"Applied {len(actions)} action(s)"
                    )
                    
                except Exception as e:
                    self.logger.error(f"Error  {dataset['name']}: {e}")
                    results['errors'] += 1
            
            results['details'].append(rule_result)
        
        return results
    
    def _matches_filter(self, dataset: Dict, rule_filter: Dict) -> bool:

        if not rule_filter:
            return True
        
        for key, value in rule_filter.items():
            if value is not None:  
                if dataset.get(key) != value:
                    return False
        
        return True
    
    def _evaluate_rule(self, rule: Rule, dataset: Dict) -> bool:

        for condition in rule.conditions:
            if not self.evaluator.evaluate(condition, dataset):
                return False
        return True
    
    def _apply_action(self, dataset: Dict, action: Action):

        if action.action == 'add_tag':
            self._add_tag(dataset, action)

    def _add_tag(self, dataset: Dict, action: Action):
    dataset_urn = make_dataset_urn(
        platform=dataset['platform'],
        name=dataset['name']
    )
    tag_urn = action.tag

    if self.dry_run:
        self.logger.info(f"   [DRY RUN] Would add tag '{tag_urn}' to {dataset['name']}")
        return
    
    try:
        from datahub.metadata.schema_classes import (
            ChangeTypeClass,
            GlobalTagsClass,
            TagAssociationClass,
        )
        
        tag_association = TagAssociationClass(tag=tag_urn)
        global_tags = GlobalTagsClass(tags=[tag_association])
        
        mcp = MetadataChangeProposalWrapper(
            entityType="dataset",
            changeType=ChangeTypeClass.UPSERT,
            entityUrn=dataset_urn,
            aspectName="globalTags",
            aspect=global_tags
        )
        
        self.emitter.emit(mcp)
        self.logger.info(f"Added tag '{tag_urn}' to {dataset['name']}")
        
    except Exception as e:
        self.logger.error(f"Failed to add tag to {dataset['name']}: {e}")
        
def _apply_actions(self, actions: List[Action], dataset: Dict, results: Dict):

    for action in actions:
        if action.action == "add_tag":
            self._add_tag(dataset, action)
            results['actions_applied'] += 1


class DataHubClient:
    
    def __init__(self, server: str, token: Optional[str] = None):
        self.server = server
        self.token = token
        self.logger = logging.getLogger('DataHubClient')
    
    def fetch_datasets(self, platform: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Fetch datasets from DataHub.
        
        In production, this would use the DataHub GraphQL API.
        For testing, we can use mock data.
        """
        # This is where you'd query DataHub's search API
        # For now, we'll use a mock implementation
        return self._fetch_mock_datasets()
    
    def _fetch_mock_datasets(self) -> List[Dict[str, Any]]:
        """Mock implementation for testing."""
        return [
            {
                'name': 'user_profiles',
                'platform': 'postgres',
                'description': 'Contains user profile information',
                'owners': ['john.doe@company.com'],
                'fields': [
                    {'name': 'id', 'type': 'integer'},
                    {'name': 'name', 'type': 'string'},
                    {'name': 'email', 'type': 'string'},
                ],
                'tags': []
            },
            {
                'name': 'sales_transactions',
                'platform': 'snowflake',
                'description': 'Daily sales transaction records',
                'owners': ['analytics@company.com'],
                'fields': [
                    {'name': 'transaction_id', 'type': 'integer'},
                    {'name': 'amount', 'type': 'decimal'},
                    {'name': 'date', 'type': 'date'},
                ],
                'tags': []
            },
            {
                'name': 'unnamed_table',
                'platform': 'bigquery',
                'description': '',  # No description
                'owners': [],  # No owners
                'fields': [
                    {'name': 'col1', 'type': 'string'},
                ],
                'tags': []
            },
        ]


# ============================================================================
# MAIN
# ============================================================================

def setup_logging():
    """Setup logging."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler('governance_engine.log'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger('GovernanceEngine')


def main():
    """Main entry point."""
    print("\n" + "=" * 70)
    print("  GOVERNANCE RULES ENGINE")
    print("=" * 70 + "\n")
    
    logger = setup_logging()
    
    # Configuration
    RULES_FILE = "governance_rules.yaml"
    DATAHUB_SERVER = "http://localhost:8080"
    DRY_RUN = True  # Set to False for real execution
    
    try:
        # Initialize engine
        engine = GovernanceRuleEngine(
            rules_file=RULES_FILE,
            datahub_server=DATAHUB_SERVER,
            dry_run=DRY_RUN
        )
        
        # Fetch datasets (mock for now)
        client = DataHubClient(DATAHUB_SERVER)
        datasets = client.fetch_datasets()
        logger.info(f"📊 Fetched {len(datasets)} datasets from DataHub")
        
        # Run rules
        start_time = time.time()
        results = engine.run(datasets)
        elapsed = time.time() - start_time
        
        # Print summary
        print("\n" + "=" * 70)
        print("  RESULTS SUMMARY")
        print("=" * 70)
        print(f"  Rules evaluated:    {results['total_rules']}")
        print(f"  Datasets checked:   {results['total_datasets']}")
        print(f"  Total evaluations:  {results['evaluations']}")
        print(f"  Passed:             {results['passed']}")
        print(f"  Failed:             {results['failed']}")
        print(f"  Actions applied:    {results['actions_applied']}")
        print(f"  Errors:             {results['errors']}")
        print(f"  Duration:           {elapsed:.1f}s")
        
        if DRY_RUN:
            print(f"\n  🔍 DRY RUN MODE - No tags were actually applied")
        
        print("\n  Rule Details:")
        for detail in results['details']:
            print(f"    • {detail['rule']}:")
            print(f"      Evaluated: {detail['datasets_evaluated']}, "
                  f"Passed: {detail['passed']}, "
                  f"Failed: {detail['failed']}, "
                  f"Actions: {detail['actions']}")
        
        print("=" * 70 + "\n")
        
    except Exception as e:
        logger.error(f"Engine failed: {e}", exc_info=True)
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
    