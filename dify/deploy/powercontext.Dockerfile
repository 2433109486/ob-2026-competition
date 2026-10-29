FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POWERCONTEXT_HOME=/data \
    POWERCONTEXT_SERVER_HTTP_HOST=0.0.0.0 \
    POWERCONTEXT_SERVER_HTTP_PORT=8000 \
    POWERCONTEXT_SERVER_ACCESS_MODE=disabled

RUN pip install --no-cache-dir "powercontext[cli,server]==1.4.1"

VOLUME ["/data"]
EXPOSE 8000

CMD ["powercontext", "server", "run"]
