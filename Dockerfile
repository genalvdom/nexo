FROM python:3.12-slim
WORKDIR /app
RUN useradd --create-home --uid 10001 app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir ".[postgres]" && mkdir -p /app/.data && chown app /app/.data
USER app
ENTRYPOINT ["nexo"]
