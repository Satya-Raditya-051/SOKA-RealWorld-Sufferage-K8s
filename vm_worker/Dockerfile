FROM python:3.11-slim
WORKDIR /app
COPY worker_server.py /app/worker_server.py
EXPOSE 8000
ENV PYTHONUNBUFFERED=1
CMD ["python3", "/app/worker_server.py"]
