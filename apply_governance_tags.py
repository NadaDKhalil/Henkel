#!/usr/bin/env python3
"""
Apply Governance Tags to Your Datasets in DataHub
==================================================
This script will:
1. Check your actual datasets in DataHub
2. Evaluate governance rules
3. Apply real tags that you can see in the UI
"""

import logging
import sys
import time
import requests
from typing import List, Dict, Any

from datahub.emitter.mce_builder import make_dataset_urn, make_tag_urn
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import (
    GlobalTagsClass,
    TagAssociationClass,
    ChangeTypeClass,
    AuditStampClass,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================
# YOUR ACTUAL DATASETS (from your CSV ingestion)
# ============================================================
YOUR_DATASETS = [
    {
        'name': 'user_profiles',
        'platform': 'postgres',
        'description': 'Contains user profile information for the application',
        'owners': ['john.doe@company.com'],
        'fields': [
            {'name': 'id', 'type': 'integer'},
            {'name': 'name', 'type': 'varchar(100)'},
            {'name': 'email', 'type': 'varchar(255)'},
            {'name': 'created_at', 'type': 'timestamp'},
            {'name': 'status', 'type': 'varchar(20)'},
        ]
    },
    {
        'name': 'sales_transactions',
        'platform': 'snowflake',
        'description': 'Daily sales transaction records from all stores',
        'owners': ['analytics.team@company.com'],
        'fields': [
            {'name': 'transaction_id', 'type': 'integer'},
            {'name': 'amount', 'type': 'decimal(10,2)'},
            {'name': 'transaction_date', 'type': 'date'},
            {'name': 'customer_id', 'type': 'integer'},
            {'name': 'store_id', 'type': 'integer'},
            {'name': 'payment_method', 'type': 'varchar(50)'},
        ]
    },
    {
        'name': 'product_catalog',
        'platform': 'bigquery',
        'description': 'Master product catalog with pricing and supplier info',
        'owners': ['engineering@company.com'],
        'fields': [
            {'name': 'product_id', 'type': 'integer'},
            {'name': 'product_name', 'type': 'varchar(200)'},
            {'name': 'price', 'type': 'decimal(8,2)'},
            {'name': 'category', 'type': 'varchar(100)'},
            {'name': 'supplier_id', 'type': 'integer'},
            {'name': 'stock_quantity', 'type': 'integer'},
        ]
    },
    {
        'name': 'customer_orders',
        'platform': 'mysql',
        'description': 'Customer order management system data',
        'owners': ['ops.team@company.com'],
        'fields': [
            {'name': 'order_id', 'type': 'integer'},
            {'name': 'customer_id', 'type': 'integer'},
            {'name': 'order_date', 'type': 'timestamp'},
            {'name': 'status', 'type': 'varchar(20)'},
            {'name': 'total_amount', 'type': 'decimal(12,2)'},
            {'name': 'shipping_address', 'type': 'text'},
        ]
    },
    {
        'name': 'inventory_log',
        'platform': 'snowflake',
        'description': 'Real-time inventory tracking across warehouses',
        'owners': ['warehouse@company.com'],
        'fields': [
            {'name': 'sku', 'type': 'varchar(50)'},
            {'name': 'warehouse_id', 'type': 'integer'},
            {'name': 'quantity', 'type': 'integer'},
            {'name': 'last_updated', 'type': 'timestamp'},
            {'name': 'reorder_point', 'type': 'integer'},
            {'name': 'reorder_quantity', 'type': 'integer'},
        ]
    },
]


# ============================================================
# GOVERNANCE RULES (same logic as before)
# ============================================================
def evaluate_dataset(dataset):
    """Evaluate a dataset and return tags to apply."""
    tags = []
    
    # Rule 1: Has owner?
    if len(dataset.get('owners', [])) > 0:
        tags.append('Compliant')
        logger.info(f"  ✅ {dataset['name']}: Has owners → Compliant")
    else:
        tags.append('NeedsOwner')
        logger.info(f"  ❌ {dataset['name']}: No owners → NeedsOwner")
    
    # Rule 2: Has description?
    if dataset.get('description', '').strip():
        tags.append('HasDescription')
        logger.info(f"  ✅ {dataset['name']}: Has description → HasDescription")
    else:
        tags.append('NeedsDescription')
        logger.info(f"  ❌ {dataset['name']}: No description → NeedsDescription")
    
    # Rule 3: Minimum fields?
    if len(dataset.get('fields', [])) >= 3:
        tags.append('ValidSchema')
        logger.info(f"  ✅ {dataset['name']}: {len(dataset['fields'])} fields → ValidSchema")
    else:
        tags.append('InsufficientSchema')
        logger.info(f"  ❌ {dataset['name']}: Only {len(dataset['fields'])} fields → InsufficientSchema")
    
    # Rule 4: Snowflake check
    if dataset['platform'] == 'snowflake':
        tags.append('NeedsPIIReview')
        logger.info(f"  ⚠️  {dataset['name']}: Snowflake → NeedsPIIReview")
    
    # Rule 5: Production ready? (all checks pass)
    has_owner = len(dataset.get('owners', [])) > 0
    has_desc = bool(dataset.get('description', '').strip())
    has_fields = len(dataset.get('fields', [])) >= 3
    
    if has_owner and has_desc and has_fields:
        tags.append('ProductionReady')
        logger.info(f"  🏆 {dataset['name']}: All checks pass → ProductionReady!")
    else:
        tags.append('NeedsImprovement')
        logger.info(f"  📋 {dataset['name']}: Some checks fail → NeedsImprovement")
    
    return tags


# ============================================================
# APPLY TAGS TO DATAHUB
# ============================================================
def apply_tags_to_datahub(datasets, dry_run=True):
    """Apply governance tags to datasets in DataHub."""
    
    if dry_run:
        logger.info("\n🔍 DRY RUN MODE - Showing what would happen\n")
    else:
        # Connect to DataHub
        emitter = DatahubRestEmitter(gms_server="http://localhost:8080")
        logger.info("✅ Connected to DataHub\n")
    
    results = []
    
    for dataset in datasets:
        logger.info(f"\n{'='*50}")
        logger.info(f"📊 Dataset: {dataset['name']} ({dataset['platform']})")
        logger.info(f"{'='*50}")
        
        # Evaluate rules
        tags = evaluate_dataset(dataset)
        
        if not dry_run:
            # Create dataset URN
            dataset_urn = make_dataset_urn(
                platform=dataset['platform'],
                name=dataset['name']
            )
            
            # Create tag associations
            tag_associations = []
            for tag_name in tags:
                tag_urn = f"urn:li:tag:{tag_name}"
                tag_associations.append(TagAssociationClass(tag=tag_urn))
            
            # Create GlobalTags aspect
            global_tags = GlobalTagsClass(tags=tag_associations)
            
            # Emit to DataHub
            mcp = MetadataChangeProposalWrapper(
                entityType="dataset",
                changeType=ChangeTypeClass.UPSERT,
                entityUrn=dataset_urn,
                aspectName="globalTags",
                aspect=global_tags
            )
            
            try:
                emitter.emit(mcp)
                logger.info(f"  ✅ Tags applied: {', '.join(tags)}")
            except Exception as e:
                logger.error(f"  ❌ Failed to apply tags: {e}")
        else:
            logger.info(f"  [DRY RUN] Would apply tags: {', '.join(tags)}")
        
        results.append({
            'dataset': dataset['name'],
            'tags': tags
        })
    
    return results


# ============================================================
# CHECK EXISTING DATASETS IN DATAHUB
# ============================================================
def check_datasets_in_datahub():
    """Check if datasets exist in DataHub."""
    logger.info("\n🔍 Checking if datasets exist in DataHub...\n")
    
    for dataset in YOUR_DATASETS:
        dataset_urn = make_dataset_urn(
            platform=dataset['platform'],
            name=dataset['name']
        )
        
        # Try to fetch the dataset from DataHub
        url = f"http://localhost:8080/entities/{dataset_urn}"
        try:
            response = requests.get(url)
            if response.status_code == 200:
                logger.info(f"  ✅ {dataset['name']} exists in DataHub")
            else:
                logger.warning(f"  ⚠️  {dataset['name']} not found in DataHub (status: {response.status_code})")
                logger.warning(f"     Run your CSV ingestion pipeline first!")
        except Exception as e:
            logger.error(f"  ❌ Cannot check {dataset['name']}: {e}")


# ============================================================
# MAIN
# ============================================================
def main():
    print("\n" + "=" * 70)
    print("  GOVERNANCE TAGS - APPLY TO DATAHUB")
    print("=" * 70 + "\n")
    
    # Ask user what to do
    print("What would you like to do?")
    print("  1. Dry run (see what tags would be applied)")
    print("  2. Apply tags for real (will modify DataHub)")
    print("  3. Check if datasets exist in DataHub")
    print()
    
    choice = input("Enter 1, 2, or 3: ").strip()
    
    if choice == "1":
        # Dry run
        print("\n" + "=" * 70)
        apply_tags_to_datahub(YOUR_DATASETS, dry_run=True)
        print("\n" + "=" * 70)
        print("  🔍 DRY RUN COMPLETE - No changes made")
        print("  Run again and select option 2 to apply tags")
        print("=" * 70 + "\n")
        
    elif choice == "2":
        # Real run
        print("\n⚠️  WARNING: This will modify datasets in DataHub!")
        confirm = input("Are you sure? Type 'yes' to continue: ").strip()
        
        if confirm.lower() == 'yes':
            print("\n" + "=" * 70)
            apply_tags_to_datahub(YOUR_DATASETS, dry_run=False)
            print("\n" + "=" * 70)
            print("  ✅ TAGS APPLIED SUCCESSFULLY!")
            print("  Check http://localhost:9002 to see the tags")
            print("=" * 70 + "\n")
        else:
            print("Cancelled.")
            
    elif choice == "3":
        # Check DataHub
        check_datasets_in_datahub()
        
    else:
        print("Invalid choice!")


if __name__ == "__main__":
    main()
