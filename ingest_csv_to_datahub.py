#!/usr/bin/env python3

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
    log_file = config['logging'].get('file', 'ingestion.log')
    
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)


class CSVDatasetReader:
    def __init__(self, file_path, delimiter=','):
        self.file_path = file_path
        self.delimiter = delimiter
        
    def read_datasets(self):
        datasets = []
        
        if not Path(self.file_path).exists():
            raise FileNotFoundError(f"CSV file not found: {self.file_path}")
        
        with open(self.file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=self.delimiter)
            
            for row in reader:
                if not row.get('dataset_name', '').strip():
                    continue
                
                fields_str = row.get('fields', '')
                fields = self._parse_fields(fields_str)
                
                if not fields:
                    continue
                
                owner_str = row.get('owner', '').strip()
                owners = [o.strip() for o in owner_str.split(';') if o.strip()] if owner_str else ['default@company.com']
                
                dataset = {
                    'name': row['dataset_name'].strip(),
                    'platform': row.get('platform', 'custom').strip().lower(),
                    'description': row.get('description', '').strip(),
                    'schema': {'fields': fields},
                    'owners': owners,
                }
                datasets.append(dataset)
        
        return datasets
    
    def _parse_fields(self, fields_str):
        fields = []
        if not fields_str or not fields_str.strip():
            return fields
        
        for field_def in fields_str.split(','):
            field_def = field_def.strip()
            if ':' in field_def:
                name, dtype = field_def.split(':', 1)
                fields.append({
                    'name': name.strip(),
                    'type': dtype.strip(),
                })
        
        return fields


def main():
    print("=" * 60)
    print("  CSV TO DATAHUB METADATA INGESTION")
    print("=" * 60)
    
    config = load_config()
    logger = setup_logging(config)
    
    # Read CSV
    csv_path = config['source']['csv']['file_path']
    logger.info(f"📄 Reading: {csv_path}")
    
    reader = CSVDatasetReader(csv_path)
    datasets = reader.read_datasets()
    logger.info(f"📊 Found {len(datasets)} datasets")
    
    # Connect to DataHub
    server = config['datahub']['server']
    dry_run = config['ingestion']['dry_run']
    
    if dry_run:
        logger.info("🔍 DRY RUN MODE - No data will be written")
        emitter = None
    else:
        emitter = DatahubRestEmitter(gms_server=server)
        logger.info(f"✅ Connected to DataHub at {server}")
    
    success = 0
    failed = 0
    
    for i, dataset in enumerate(datasets, 1):
        logger.info(f"\n[{i}/{len(datasets)}] Processing {dataset['name']}...")
        
        try:
            # Create dataset URN
            dataset_urn = make_dataset_urn(
                platform=dataset['platform'],
                name=dataset['name']
            )
            
            # Create platform URN (just the platform, not the full dataset URN)
            platform_urn = make_data_platform_urn(dataset['platform'])
            
            logger.info(f"   Dataset URN: {dataset_urn}")
            logger.info(f"   Platform URN: {platform_urn}")
            
            if dry_run:
                logger.info(f"   [DRY RUN] Would emit dataset properties")
                logger.info(f"   [DRY RUN] Would emit schema with {len(dataset['schema']['fields'])} fields")
                logger.info(f"   [DRY RUN] Would emit ownership")
            else:
                # 1. Emit dataset properties
                emitter.emit(
                    MetadataChangeProposalWrapper(
                        entityType="dataset",
                        changeType=ChangeTypeClass.UPSERT,
                        entityUrn=dataset_urn,
                        aspectName="datasetProperties",
                        aspect=DatasetPropertiesClass(
                            description=dataset.get('description', ''),
                            customProperties={
                                'source': 'csv_ingestion',
                                'platform': dataset['platform']
                            }
                        )
                    )
                )
                logger.info(f"   ✅ Emitted properties")
                
                # 2. Emit schema - FIX: Use platform_urn, not dataset_urn
                fields = []
                for field in dataset['schema']['fields']:
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
                logger.info(f"   ✅ Emitted schema ({len(fields)} fields)")
                
                # 3. Emit ownership
                owners = []
                for email in dataset['owners']:
                    username = email.split('@')[0]
                    owners.append(
                        OwnerClass(
                            owner=make_user_urn(username),
                            type=OwnershipTypeClass.DATAOWNER,
                        )
                    )
                
                ownership = OwnershipClass(
                    owners=owners,
                    lastModified=AuditStampClass(
                        time=int(time.time() * 1000),
                        actor=make_user_urn("datahub"),
                    )
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
                logger.info(f"   ✅ Emitted ownership ({len(owners)} owners)")
            
            logger.info(f"   ✅ Successfully ingested!")
            success += 1
            
        except Exception as e:
            logger.error(f"   ❌ Failed: {e}")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"  ✅ Successful: {success}")
    print(f"  ❌ Failed: {failed}")
    print("=" * 60)
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
