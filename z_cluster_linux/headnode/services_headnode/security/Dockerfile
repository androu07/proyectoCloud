FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código
COPY security_api.py .

# Exponer puerto
EXPOSE 5811

# Comando de inicio
CMD ["uvicorn", "security_api:app", "--host", "0.0.0.0", "--port", "5811", "--reload"]
