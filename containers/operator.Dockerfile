FROM python:3.12-slim@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    OPERATOR_STATIC_ROOT=/app/operator/static \
    PORT=8080

WORKDIR /app
COPY src/inference_lab /app/src/inference_lab
COPY operator/static /app/operator/static
USER 65532:65532
EXPOSE 8080
CMD ["python", "-m", "inference_lab.operator"]
