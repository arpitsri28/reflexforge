FROM python:3.11-slim-bookworm
RUN useradd --uid 1000 --create-home worker && mkdir /workspace /evaluation
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1000:1000
WORKDIR /workspace
CMD ["sleep", "infinity"]
