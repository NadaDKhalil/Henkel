#!/usr/bin/env python3

import yaml
import logging
from typing import Dict, List, Any, Optional

from datahub.emitter.mce_builder import make_tag_urn, make_user_urn
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.ingestion.graph.client import DataHubGraph, DatahubClientConfig
from datahub.metadata.schema_classes import (
    TagPropertiesClass,
    ChangeTypeClass,
    AuditStampClass,
)
from datahub.specific.dataset import DatasetPatchBuilder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TagManager:
    def __init__(self, emitter: DatahubRestEmitter, dry_run: bool = False):
        self.emitter = emitter
        self.dry_run = dry_run

    def ensure_tag_exists(self, tag_name: str) -> bool:
        tag_urn = make_tag_urn(tag_name)
        
        if self.dry_run:
            logger.info(f"[DRY RUN] create tag: {tag_name}")
            return True
        try:
            tag_properties = TagPropertiesClass(
                name=tag_name,
                description=f"Governance tag: {tag_name}",
                created=AuditStampClass(
                    time=0,
                    actor=make_user_urn("governance_engine"),
                )
            )
            
            mcp = MetadataChangeProposalWrapper(
                entityType="tag",
                changeType=ChangeTypeClass.UPSERT,
                entityUrn=tag_urn,
                aspectName="tagProperties",
                aspect=tag_properties,
            )
            
            self.emitter.emit(mcp)
            logger.debug(f"Created tag: {tag_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create tag {tag_name}: {e}")
            return False

    def apply_tag_to_dataset(self, dataset_urn: str, tag_name: str) -> bool:
        tag_urn = make_tag_urn(tag_name)
        
        if self.dry_run:
            logger.info(f"[DRY RUN] Would apply '{tag_name}' to {dataset_urn}")
            return True
        try:
            self.ensure_tag_exists(tag_name)          
            patch_builder = DatasetPatchBuilder(dataset_urn)
            patch_builder.add_tag(tag_urn)
            
            for patch in patch_builder.build():
                self.emitter.emit(patch)
            
            logger.info(f"Applied '{tag_name}' to {dataset_urn}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to apply '{tag_name}' to {dataset_urn}: {e}")
            return False


class ConditionEvaluator:
    def __init__(self, graph_client: DataHubGraph):
        self.graph_client = graph_client

    def evaluate(self, condition: Dict[str, Any], dataset_urn: str) -> bool:
        property_name = condition.get('property')
        expected = condition.get('expected', True)        
        evaluator_method = getattr(self, f'_evaluate_{property_name}', None)       
        if evaluator_method is None:
            logger.warning(f"Unknown condition: {property_name}")
            return False
        
        try:
            actual = evaluator_method(dataset_urn)
            result = (actual == expected)
            logger.debug(f"{property_name}: expected={expected}, actual={actual}, result={result}")
            return result
        except Exception as e:
            logger.error(f"Error evaluating {property_name}: {e}")
            return False

    def _evaluate_hasOwner(self, dataset_urn: str) -> bool:

        query = """
        query GetDataset($urn: String!) {
            dataset(urn: $urn) {
                ownership { owners { owner { ... on CorpUser { username } } } }
            }
        }
        """
        result = self.graph_client.execute_graphql(query, variables={"urn": dataset_urn})
        dataset_data = result.get("data", {}).get("dataset", {})
        owners = dataset_data.get("ownership", {}).get("owners", [])
        return len(owners) > 0

    def _evaluate_hasDescription(self, dataset_urn: str) -> bool:
        query = """
        query GetDataset($urn: String!) {
            dataset(urn: $urn) { properties { description } }
        }
        """
        result = self.graph_client.execute_graphql(query, variables={"urn": dataset_urn})
        dataset_data = result.get("data", {}).get("dataset", {})
        description = dataset_data.get("properties", {}).get("description", "")
        return bool(description and description.strip())

    def _evaluate_hasTag(self, dataset_urn: str) -> bool:
        query = """
        query GetDataset($urn: String!) {
            dataset(urn: $urn) { tags { tags { tag { name } } } }
        }
        """
        result = self.graph_client.execute_graphql(query, variables={"urn": dataset_urn})
        dataset_data = result.get("data", {}).get("dataset", {})
        tags = dataset_data.get("tags", {}).get("tags", [])
        return len(tags) > 0


class GovernanceEngine:
    def __init__(self, config_file: str = "engine_config.yaml"):
        # Load config
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
        
        # Extract configs with proper structure
        datahub_config = config.get('datahub', {})
        engine_config = config.get('engine', {})
        logging_config = config.get('logging', {})
        
        server = datahub_config.get('server', 'http://localhost:8080')
        # token = datahub_config.get('token')  # if needed later
        self.dry_run = engine_config.get('dry_run', False)
        
        # Setup logging from config
        log_level = logging_config.get('level', 'INFO')
        log_file = logging_config.get('file')
        if log_file:
            logging.basicConfig(
                level=getattr(logging, log_level),
                filename=log_file,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
        
        # Initialize clients
        self.graph_client = DataHubGraph(DatahubClientConfig(server=server))
        self.emitter = DatahubRestEmitter(gms_server=server)
        self.tag_manager = TagManager(self.emitter, self.dry_run)
        self.evaluator = ConditionEvaluator(self.graph_client)
        self.stats = {'processed': 0, 'tags_applied': 0, 'errors': 0}

    def load_rules(self, rules_file: str) -> List[Dict[str, Any]]:
        with open(rules_file, 'r') as f:
            config = yaml.safe_load(f)
            return config.get('rules', [])

    def get_datasets(self, platform_filter: Optional[str] = None) -> List[str]:
        query = """
        query ScrollDatasets($input: ScrollAcrossEntitiesInput!) {
            scrollAcrossEntities(input: $input) {
                searchResults { entity { ... on Dataset { urn platform { name } } } }
                nextScrollId
            }
        }
        """
    
        all_urns = []
        next_scroll_id = None
    
        while True:
            variables = {
                "input": {
                    "types": ["DATASET"],
                    "query": "*",  # <-- ADD THIS LINE
                    "scrollId": next_scroll_id,
                    "keepAlive": True,
                    "count": 100,
                }
            }
        
            result = self.graph_client.execute_graphql(query, variables=variables)
            data = result.get("data", {}).get("scrollAcrossEntities", {})
        
            for item in data.get("searchResults", []):
                entity = item.get("entity", {})
                platform = entity.get("platform", {}).get("name", "")
            
                if platform_filter and platform != platform_filter:
                    continue
            
                urn = entity.get("urn")
                if urn:
                    all_urns.append(urn)
        
            next_scroll_id = data.get("nextScrollId")
            if not next_scroll_id:
                break
    
        logger.info(f"Found {len(all_urns)} datasets")
        return all_urns

    def evaluate_rule(self, rule: Dict[str, Any], dataset_urn: str) -> None:
        rule_name = rule.get('name', 'Unnamed')
        
  
        platform_filter = rule.get('filter', {}).get('platform')
        if platform_filter:
            platform = dataset_urn.split(':')[3].split(',')[0] if ':' in dataset_urn else ''
            if platform != platform_filter:
                return

        all_pass = all(
            self.evaluator.evaluate(cond, dataset_urn) 
            for cond in rule.get('conditions', [])
        )
        

        actions = rule.get('on_pass' if all_pass else 'on_fail', [])
        for action in actions:
            if action.get('action') == 'add_tag':
                tag_name = action.get('tag', '').replace('urn:li:tag:', '')
                if self.tag_manager.apply_tag_to_dataset(dataset_urn, tag_name):
                    self.stats['tags_applied'] += 1

    def run(self, rules_file: str) -> None:
        logger.info(f"Governance Engine (dry_run={self.dry_run})")
        rules = self.load_rules(rules_file)
        logger.info(f"Loaded {len(rules)} rules")

        dataset_urns = self.get_datasets()
        if not dataset_urns:
            logger.warning("No datasets found")
            return
        
        # Evaluate each dataset against each rule
        for dataset_urn in dataset_urns:
            self.stats['processed'] += 1
            for rule in rules:
                try:
                    self.evaluate_rule(rule, dataset_urn)
                except Exception as e:
                    logger.error(f"Error: {e}")
                    self.stats['errors'] += 1

        print(f"processed: {self.stats['processed']}")
        print(f"Tags: {self.stats['tags_applied']}")
        print(f" Errors: {self.stats['errors']}")



if __name__ == "__main__":
    import sys
    
    rules_file = sys.argv[1] if len(sys.argv) > 1 else "config/rules.yml"
    
    engine = GovernanceEngine("engine_config.yaml")
    engine.run(rules_file)
