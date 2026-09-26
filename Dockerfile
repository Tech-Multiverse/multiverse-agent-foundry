FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY configs ./configs

ENTRYPOINT ["python"]
CMD ["-m", "src", "--config", "configs/example-tasks/research.yaml"]
