## Deployment

# Clone the repo
git clone https://github.com/NadaDKhalil/Henkel.git
cd Henkel

# Install req
pip install -r requirements.txt

# Start DataHub 
pip install acryl-datahub
export DATAHUB_TOKEN_SERVICE_SIGNING_KEY=$(openssl rand -base64 32)
export DATAHUB_TOKEN_SERVICE_SALT=$(openssl rand -base64 32)
datahub docker quickstart


# run local
python ingest_csv.py config.yaml
python engine.py governance_rules.yaml
# run with docker 
docker build -f Dockerfile.ingestion -t data-ingestion .
docker run -v $(pwd):/app data-ingestion

docker build -f Dockerfile -t governance-engine .
docker run -v $(pwd):/app governance-engine
# Install pytest 
pip install pytest
# Run  tests
pytest tests/
---------------------------------
##Q&A
Q: How do you handle schema evolution?
Data hub is versioned aspect based meaning that the aspect have version fieald that changes with every change to aspect itself and that can be used in historical tracking for lineage also changes are handles with an upsert operation so no dupplicates ever exist.

Q: What happens if the source has 10,000 datasets?
Data will be processed in batches size of which is spacified in config.yaml file to not overwhelm data resources when sending the metadata.

Q: How would you add a new rule type without changing the core engine?
The way the script is set up extensible meaning i can strech ip with more methods to fill the new rules 
i have a condition evaluater class where i define the way i evaluate each condition so if i have a new condition i just add to that class an _evaluate method that applies the condition then i can simply use it as a condition in my rules file.

Q: How do you test the rules engine without a live DataHub instance?
we use mock test which is kinda like a dry run howeever it doesnt actually connect to datahub it uses fake clients and tests that the logic works correctly






