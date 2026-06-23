FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy governance files
COPY engine.py .
COPY engine_config.yaml .
COPY governance_rules.yaml .
COPY datasets.csv .

CMD ["python", "engine.py", "governance_rules.yaml"]