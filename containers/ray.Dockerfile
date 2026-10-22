FROM rayproject/ray:2.59.0-py312-cpu@sha256:0ffca209fb4c984d648db550b8dbe7879bdba3bbb5d96ee5894843cf6ac12eb5

WORKDIR /opt/inference-lab
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir '.[serve]'

EXPOSE 8000
CMD ["python", "-m", "inference_lab.ray_app"]
