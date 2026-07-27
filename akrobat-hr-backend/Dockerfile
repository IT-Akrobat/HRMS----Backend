FROM python:3.12-slim

WORKDIR /app

# System deps needed to build some wheels (kept minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud platforms provide $PORT; default to 8000 for local `docker run`.
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:${PORT} --timeout 120"]
