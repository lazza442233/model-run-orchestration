FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ src/
COPY .env.example .env

ENV PYTHONPATH=/app

CMD ["flask", "run", "--host=0.0.0.0"]
