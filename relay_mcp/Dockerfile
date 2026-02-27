FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

# Data directory for SQLite DB (mount a volume here for persistence)
RUN mkdir -p /app/data

EXPOSE 8765

CMD ["python", "server.py", "--host", "0.0.0.0", "--db", "/app/data/relay.db"]
