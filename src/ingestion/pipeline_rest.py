"""
Metadata Ingestion Pipeline using DataHub REST API
"""

import csv
import logging
import os
import json
import requests
from typing import Dict, List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
DATAHUB_GMS_URL = os.environ.get("DATAHUB_GMS_URL", "http://localhost:8080")


class RESTIngestionPipeline:
    def __init__(self, csv_path: str, platform: str = "postgres"):
        self.csv_path = csv_path
        self.platform = platform
        self.base_url = DATAHUB_GMS_URL

    def read_csv(self) -> Dict[str, List[Dict]]:
        tables = {}
        with open(self.csv_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                table = row["table_name"]
                if table not in tables:
                    tables[table] = []
                tables[table].append({
                    "name": row["column_name"],
                    "type": row["data_type"],
                    "description": row.get("description", ""),
                })
        return tables

    def emit_mce(self, mce_json: Dict) -> bool:
        """Emit MCE to DataHub GMS"""
        url = f"{self.base_url}/entities?action=ingest"
        headers = {"Content-Type": "application/json"}
        
        if DRY_RUN:
            logger.info(f"[DRY RUN] Would emit: {json.dumps(mce_json, indent=2)[:500]}...")
            return True

        try:
            response = requests.post(url, headers=headers, json=mce_json)
            if response.status_code == 200:
                logger.info(f"✅ Successfully emitted: {mce_json.get('urn', 'unknown')}")
                return True
            else:
                logger.error(f"❌ Failed to emit: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logger.error(f"❌ Error emitting: {e}")
            return False

    def create_mce(self, table: str, columns: List[Dict]) -> Dict:
        """Create MCE for a dataset"""
        # Build schema fields
        fields = []
        for col in columns:
            field = {
                "fieldPath": col["name"],
                "nativeDataType": col["type"],
                "description": col.get("description", ""),
                "nullable": True,
                "recursive": False,
            }
            # Add type info
            if col["type"] in ["integer", "int", "bigint"]:
                field["type"] = {"type": "number"}
            elif col["type"] in ["decimal", "float", "double"]:
                field["type"] = {"type": "number"}
            elif col["type"] in ["boolean", "bool"]:
                field["type"] = {"type": "boolean"}
            else:
                field["type"] = {"type": "string"}
            fields.append(field)

        # Create the MCE
        mce = {
            "entity": {
                "type": "dataset",
                "urn": f"urn:li:dataset:(urn:li:dataPlatform:{self.platform},sample_db.{table},PROD)",
                "aspects": {
                    "schemaMetadata": {
                        "schemaName": table,
                        "platform": f"urn:li:dataPlatform:{self.platform}",
                        "version": 0,
                        "created": {"time": 0, "actor": "urn:li:corpuser:datahub"},
                        "lastModified": {"time": 0, "actor": "urn:li:corpuser:datahub"},
                        "hash": "",
                        "fields": fields,
                    },
                    "datasetProperties": {
                        "name": table,
                        "description": f"Table {table} from sample data",
                    },
                    "ownership": {
                        "owners": [
                            {
                                "owner": "urn:li:corpuser:data_engineer",
                                "type": "TECHNICAL_OWNER",
                            }
                        ],
                        "lastModified": {"time": 0, "actor": "urn:li:corpuser:datahub"},
                    }
                }
            }
        }
        return mce

    def run(self):
        logger.info(f"🚀 Starting REST ingestion from {self.csv_path}")
        logger.info(f"🔍 DRY_RUN mode: {DRY_RUN}")
        logger.info(f"📡 DataHub GMS URL: {self.base_url}")

        tables = self.read_csv()
        logger.info(f"📊 Found {len(tables)} tables")

        for table, columns in tables.items():
            mce = self.create_mce(table, columns)
            self.emit_mce(mce)

        logger.info("✅ Ingestion complete")


if __name__ == "__main__":
    pipeline = RESTIngestionPipeline("data/sample.csv")
    pipeline.run()
