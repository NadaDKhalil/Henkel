"""
Metadata Ingestion Pipeline for DataHub
Reads metadata from CSV and emits to DataHub
"""

import csv
import logging
import os
import subprocess
import tempfile
import json
from typing import Dict, List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
DATAHUB_GMS_URL = os.environ.get("DATAHUB_GMS_URL", "http://localhost:8080")


class CSVIngestionPipeline:
    """Ingests metadata from CSV files into DataHub"""

    def __init__(self, csv_path: str, platform: str = "postgres"):
        self.csv_path = csv_path
        self.platform = platform

    def read_csv(self) -> Dict[str, List[Dict]]:
        """Read CSV and group metadata by table name"""
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

    def create_mce_json(self, table: str, columns: List[Dict]) -> Dict:
        """Create MCE JSON for a dataset"""
        # Build fields
        fields = []
        for col in columns:
            field = {
                "fieldPath": col["name"],
                "nativeDataType": col["type"],
                "description": col.get("description", ""),
                "type": {
                    "type": {
                        "com.linkedin.pegasus2avro.schema.StringType": {}
                    }
                },
                "nullable": True,
                "recursive": False,
            }
            # Adjust type based on data type
            if col["type"] in ["integer", "int"]:
                field["type"] = {
                    "type": {
                        "com.linkedin.pegasus2avro.schema.NumberType": {}
                    }
                }
            elif col["type"] in ["decimal", "float", "double"]:
                field["type"] = {
                    "type": {
                        "com.linkedin.pegasus2avro.schema.NumberType": {}
                    }
                }
            fields.append(field)

        # Create the full MCE
        mce = {
            "proposedSnapshot": {
                "com.linkedin.pegasus2avro.metadata.snapshot.DatasetSnapshot": {
                    "urn": f"urn:li:dataset:(urn:li:dataPlatform:{self.platform},sample_db.{table},PROD)",
                    "aspects": [
                        {
                            "com.linkedin.pegasus2avro.schema.SchemaMetadata": {
                                "schemaName": table,
                                "platform": f"urn:li:dataPlatform:{self.platform}",
                                "version": 0,
                                "created": {
                                    "time": 0,
                                    "actor": "urn:li:corpuser:datahub"
                                },
                                "lastModified": {
                                    "time": 0,
                                    "actor": "urn:li:corpuser:datahub"
                                },
                                "hash": "",
                                "platformSchema": {
                                    "com.linkedin.pegasus2avro.schema.KafkaSchema": {
                                        "documentSchema": ""
                                    }
                                },
                                "fields": fields,
                                "primaryKeys": [],
                                "foreignKeys": []
                            }
                        },
                        {
                            "com.linkedin.pegasus2avro.dataset.DatasetProperties": {
                                "name": table,
                                "description": f"Table {table} from sample data",
                                "customProperties": {}
                            }
                        },
                        {
                            "com.linkedin.pegasus2avro.common.Ownership": {
                                "owners": [
                                    {
                                        "owner": "urn:li:corpuser:data_engineer",
                                        "type": "com.linkedin.pegasus2avro.common.OwnershipType",
                                        "source": {
                                            "type": "com.linkedin.pegasus2avro.common.OwnershipSourceType",
                                            "sourceType": "TECHNICAL_OWNER"
                                        }
                                    }
                                ],
                                "lastModified": {
                                    "time": 0,
                                    "actor": "urn:li:corpuser:datahub"
                                }
                            }
                        }
                    ]
                }
            }
        }
        return mce

    def process_table(self, table: str, columns: List[Dict]) -> None:
        """Process a single table and emit to DataHub"""
        if DRY_RUN:
            logger.info(f"[DRY RUN] Would process: sample_db.{table}")
            logger.info(f"[DRY RUN] Columns: {columns}")
            return

        try:
            # Generate MCE JSON
            mce_data = self.create_mce_json(table, columns)
            
            # Write to temp file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(mce_data, f, indent=2)
                temp_file = f.name

            # Use datahub CLI to ingest - corrected flags
            cmd = [
                "datahub",
                "ingest",
                "run",
                "-c",
                temp_file,
                "--strict-warnings"
            ]
            
            logger.info(f"Running command: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                logger.info(f"✅ Successfully emitted dataset: {table}")
            else:
                logger.error(f"❌ Failed to emit {table}: {result.stderr}")
                logger.error(f"Command output: {result.stdout}")
            
            # Clean up temp file
            os.unlink(temp_file)

        except Exception as e:
            logger.error(f"❌ Failed to process {table}: {e}")
            raise

    def run(self) -> None:
        """Main pipeline execution"""
        logger.info(f"🚀 Starting ingestion from {self.csv_path}")
        logger.info(f"🔍 DRY_RUN mode: {DRY_RUN}")

        tables = self.read_csv()
        logger.info(f"📊 Found {len(tables)} tables")

        for table, columns in tables.items():
            try:
                self.process_table(table, columns)
            except Exception as e:
                logger.error(f"⏭️ Skipping {table} due to error: {e}")
                continue

        logger.info("✅ Ingestion complete")


if __name__ == "__main__":
    pipeline = CSVIngestionPipeline("data/sample.csv")
    pipeline.run()