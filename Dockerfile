FROM python:3.13-slim

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY app.py baze_models.py key_store.py project_store.py ./
COPY web/ ./web/

ENV PYTHONUNBUFFERED=1
CMD ["python", "app.py", "--cloud", "--no-browser"]

