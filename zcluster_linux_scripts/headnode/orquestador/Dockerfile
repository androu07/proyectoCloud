# Imagen base de Python
FROM python:3.11-slim

# Establecer directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copiar archivos de requisitos
COPY requirements_api.txt .

# Instalar dependencias de Python
RUN pip install --no-cache-dir -r requirements_api.txt

# Copiar código de la aplicación
COPY orquestador_api.py .
COPY vnc_manager.py .

# Exponer puerto
EXPOSE 5805

# Comando para ejecutar la aplicación
CMD ["python", "orquestador_api.py"]
