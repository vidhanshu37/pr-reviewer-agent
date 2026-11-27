FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY pr_reviewer_agent ./pr_reviewer_agent
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app

RUN useradd --system --create-home appuser
USER appuser
EXPOSE 8000
CMD ["uvicorn", "pr_reviewer_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]