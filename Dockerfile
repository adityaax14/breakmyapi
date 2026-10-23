# The backend image: used by BOTH the api and the worker services (they differ only in their start command).

FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1
# UV_NO_CACHE: don't keep uv's download cache inside the image (it was 1.2 GB of wasted space).

RUN pip install --no-cache-dir uv==0.11.19

WORKDIR /app

# 1. Install the dependencies first, from the lock file only. Docker caches this layer, so
#    changing our own code later does not re-download torch and friends.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

# 2. Then copy our code and data, and install the project itself (a quick step).
COPY src ./src
COPY corpus ./corpus
RUN uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000

# The api runs this; the worker service overrides it with `python -m breakmyapi.worker`.
CMD ["uvicorn", "breakmyapi.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
