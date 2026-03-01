# Optional containerized runtime for the Automaton Auditor (Week 2)
# Build: docker build -t automaton-auditor .
# Run:   docker run --env-file .env -v $(pwd)/audit:/app/audit automaton-auditor --repo-url <url> [--pdf-path <path>]

FROM python:3.11-slim

WORKDIR /app

# Install git for clone_repo
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Install uv and sync dependencies
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --no-dev --no-install-project

# Copy project and install
COPY . .
RUN uv sync --no-dev

# Run: docker run --env-file .env -v $(pwd)/audit:/app/audit automaton-auditor --repo-url <url> [--pdf-path <path>]
ENTRYPOINT ["uv", "run", "python", "main.py"]
CMD ["--repo-url", "https://github.com/owner/repo"]
