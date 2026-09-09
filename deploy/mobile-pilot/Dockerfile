FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        libgl1 \
        tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-private.txt ./requirements-private.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements-private.txt

COPY backend ./backend
COPY frontend ./frontend
COPY scripts/mobile_pilot_entrypoint.py ./scripts/mobile_pilot_entrypoint.py

RUN useradd --create-home --uid 10001 apex \
    && mkdir -p /var/lib/apex \
    && chown -R apex:apex /app /var/lib/apex

USER apex
EXPOSE 8000

CMD ["python", "scripts/mobile_pilot_entrypoint.py"]
