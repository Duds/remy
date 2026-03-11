# Phase B Python sandbox for run_python (US-python-code-execution).
# Build: docker build -t remy-python-sandbox:latest .
# Image includes common data-science packages; no network at runtime.

FROM python:3.11-slim

RUN pip install --no-cache-dir \
    numpy==1.26.* \
    pandas==2.1.* \
    matplotlib==3.8.* \
    scipy==1.11.* \
    python-dateutil==2.8.* \
    pytz==2024.*

RUN useradd -m -u 1000 sandbox
USER sandbox
WORKDIR /workspace

ENTRYPOINT ["python"]
