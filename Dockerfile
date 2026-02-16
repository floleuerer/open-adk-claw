FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy project files (no uv.lock — let uv resolve fresh for the container platform)
COPY pyproject.toml .

# Install dependencies
RUN uv sync --no-dev

COPY src/ src/

# Workspace is mounted at runtime
VOLUME ["/app/workspace"]

CMD ["uv", "run", "python", "-m", "adk_claw"]
