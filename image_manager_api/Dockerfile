FROM python:3.12-slim

# Instalar dependencias del sistema en una sola capa optimizada
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    libguestfs-tools \
    qemu-utils \
    zstd \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

WORKDIR /app

# Copiar solo requirements primero (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código
COPY main.py .

# Crear directorio para imágenes
RUN mkdir -p /var/lib/images

EXPOSE 5700

# Usar solo 2 workers para reducir overhead
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5700", "--workers", "2"]
