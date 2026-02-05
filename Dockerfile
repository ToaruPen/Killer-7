FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

COPY killer_7 /app/killer_7
COPY killer-7 /usr/local/bin/killer-7

RUN chmod +x /usr/local/bin/killer-7

WORKDIR /work

ENTRYPOINT ["killer-7"]
