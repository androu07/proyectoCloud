FROM python:3.12-slim

WORKDIR /app

# Copiar requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código
COPY main.py .

EXPOSE 5900

# Usar 2 workers
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5900", "--workers", "2"]
