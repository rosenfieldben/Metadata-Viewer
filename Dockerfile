# Container build for easy sharing: the recipient needs Docker and nothing
# else (Python, ExifTool, and all libraries ship inside the image).
#
#   docker build -t metadata-inspector .
#   docker run --rm -p 8000:8000 metadata-inspector
#
# Then open http://127.0.0.1:8000. Files are still processed locally, inside
# the container on your machine, and are deleted after each request.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends libimage-exiftool-perl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/metadata-inspector

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static

EXPOSE 8000

# 0.0.0.0 is required inside a container so the published port is reachable;
# the docker run -p mapping above still binds only to localhost by default.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
