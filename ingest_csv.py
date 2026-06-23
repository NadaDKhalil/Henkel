import csv
import logging
import sys
import time
from pathlib import Path

import yaml
from datahub.emitter.mce_builder import make_dataset_urn, make_user_urn, make_data_platform_urn
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import (
    DatasetPropertiesClass,
    SchemaMetadataClass,
    SchemaFieldClass,
    SchemaFieldDataTypeClass,
    StringTypeClass,
    OwnerClass,
    OwnershipTypeClass,
    OwnershipClass,
    ChangeTypeClass,
    AuditStampClass,
)
def load_config(config_path="config.yaml"):
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    return config
def setup_logging(config):
    log_level = getattr(logging, config['logging'].get('level', 'INFO'))

    logging.basicConfig(level=log_level, format='%(levelname)s - %(message)s', handlers=[
            logging.StreamHandler(sys.stdout)
        ])
    return logging.getLogger(__name__)
class CSVDatasetReader:
    def __init__(self, file_path, delimiter=','):
        self.file_path = file_path
        self.delimiter = delimiter
    def read_datasets(self):
        datasets = []        
        with open(self.file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=self.delimiter)
            for row in reader:
                name = row.get('dataset_name', '').strip()
                fields = []
                for f in row.get('fields', '').split(','):
                    if ':' in f:
                        field_name, field_type = f.strip().split(':', 1)
                        fields.append({'name': field_name.strip(), 'type': field_type.strip()})
                owner = row.get('owner', 'default@company.com')
                dataset = {
                    'name': name,
                    'platform': row.get('platform', 'custom'),
                    'description': row.get('description', ''),
                    'fields': fields,
                    'owner': owner,
                }
                datasets.append(dataset)
        
        return datasets
def main():
    config = load_config()
    logger = setup_logging(config)
    csv_path = config['source']['csv']['file_path']
    reader = CSVDatasetReader(csv_path)
    datasets = reader.read_datasets()
    logger.info(f"Found {len(datasets)} datasets")
    server = config['datahub']['server']
    dry_run = config['ingestion']['dry_run']
    if dry_run:
        logger.info("DRY RUN")
        emitter = None
    else:
        emitter = DatahubRestEmitter(gms_server=server)
        logger.info(f"Connected to {server}")
    success = 0
    failed = 0
    for dataset in datasets:
        try:
            dataset_urn = make_dataset_urn(
                platform=dataset['platform'],
                name=dataset['name']
            )
            platform_urn = make_data_platform_urn(dataset['platform'])
            if dry_run:
                logger.info(f"   [DRY RUN] Would emit dataset properties")
                logger.info(f"   [DRY RUN] Would emit schema with {len(dataset['fields'])} fields")
                logger.info(f"   [DRY RUN] Would emit ownership")
            else: 
                emitter.emit(
                    MetadataChangeProposalWrapper(
                        entityType="dataset",
                        changeType=ChangeTypeClass.UPSERT,
                        entityUrn=dataset_urn,
                        aspectName="datasetProperties",
                        aspect=DatasetPropertiesClass(
                            description=dataset['description'],
                            customProperties={
                                'source': 'csv_ingestion',
                                'platform': dataset['platform']
                            }
                        )
                    )
                )
                fields = []
                for field in dataset['fields']:
                    fields.append(
                        SchemaFieldClass(
                            fieldPath=field['name'],
                            nativeDataType=field['type'],
                            type=SchemaFieldDataTypeClass(type=StringTypeClass()),
                        )
                    )
                
                schema_metadata = SchemaMetadataClass(
                    schemaName=dataset['name'],
                    platform=platform_urn,  # FIXED: Use platform URN, not dataset URN
                    version=0,
                    hash="",
                    platformSchema=SchemaFieldDataTypeClass(type=StringTypeClass()),
                    fields=fields,
                )                
                emitter.emit(
                    MetadataChangeProposalWrapper(
                        entityType="dataset",
                        changeType=ChangeTypeClass.UPSERT,
                        entityUrn=dataset_urn,
                        aspectName="schemaMetadata",
                        aspect=schema_metadata
                    )
                )   
                username = dataset['owner'].split('@')[0]
                ownership = OwnershipClass(
                    owners=[
                        OwnerClass(
                        owner=make_user_urn(username),
                        type=OwnershipTypeClass.DATAOWNER,
                        )
                    ]
                )
                emitter.emit(
                    MetadataChangeProposalWrapper(
                    entityType="dataset",
                    changeType=ChangeTypeClass.UPSERT,
                    entityUrn=dataset_urn,
                    aspectName="ownership",
                    aspect=ownership
                    )
                )
            logger.info(f"   ✅ Successfully ingested!")
            success += 1   
        except ConnectionError as e:
            logger.error(f"  Network error: {e}")
            failed += 1
        except KeyError as e:
            logger.error(f"  Missing field: {e}")
            failed += 1
        except Exception as e:
            logger.error(f"  Other error: {e}")
            failed += 1
    print(f"PASS : {success}")
    print(f"FAIL: {failed}")

    



if __name__ == "__main__":
    sys.exit(main())