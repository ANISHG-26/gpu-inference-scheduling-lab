FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app
COPY src/inference_lab/expiry.py /app/expiry.py
RUN pip install --no-cache-dir google-auth==2.62.0 requests==2.34.2

USER 65532:65532
EXPOSE 8080
CMD ["python", "/app/expiry.py"]
