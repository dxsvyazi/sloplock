# syntax=docker.io/docker/dockerfile:1.7-labs

FROM python:3.13-trixie AS base

ENV \
  PYTHONUNBUFFERED=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  PYSETUP_PATH="/base"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR $PYSETUP_PATH

COPY . .

RUN chmod +x "$PYSETUP_PATH/bootstrap.sh"

FROM base AS dev

RUN --mount=type=ssh uv sync --locked --no-dev

CMD ["/bin/bash", "bootstrap.sh"]

FROM base AS prod

CMD ["/bin/bash", "bootstrap.sh"]