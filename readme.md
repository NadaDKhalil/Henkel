## Deployment


```bash
docker build -t governance-engine .
docker run -v $(pwd):/app governance-engine

# Install DataHub CLI
pip install acryl-datahub

# Start DataHub 
datahub docker quickstart


##INstalls

# Clone the repository
git clone https://github.com/NadaDKhalil/Henkel.git
cd governance-engine
# Create virtual environment & Install dependencies
python3 -m venv venv
source venv/bin/activate  
pip install -r requirements.txt
# Install dependencies
pip install -r requirements.txt
#Locally
datahub docker quickstart
python ingest_csv.py config.yaml
python engine.py governance_rules.yaml

# Build  image
docker build -f Dockerfile.ingestion -t data-ingestion .
docker build -f Dockerfile -t governance-engine .
