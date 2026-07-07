# Steppy
FROM python:3.11-slim

# cadquery-ocp ships manylinux wheels for x86_64 and arm64, so this image
# builds fine both on typical amd64 servers and on Apple Silicon / arm64
# boards -- no GPU or special hardware needed anywhere in this pipeline.

WORKDIR /app

# cadquery-ocp's compiled OCCT library links against its old visualization
# stack's runtime libraries even though we only use the geometry kernel, so
# these need to be present or Python fails at `import OCP` with a missing
# shared-object error (libXrender.so.1, libSM.so.6, etc).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglu1-mesa \
    libgomp1 \
    libxrender1 \
    libxext6 \
    libsm6 \
    libice6 \
    libx11-6 \
    libxi6 \
    libxft2 \
    libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV DATA_DIR=/data
RUN mkdir -p /data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
