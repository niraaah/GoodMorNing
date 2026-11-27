FROM python:3.12-slim-bookworm@sha256:44cf1793efa7c7a476bb0f2cff81443f4a072c90c1cb127e2924933daa3e8c64 AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

FROM base AS guard
RUN apt-get update && apt-get install -y --no-install-recommends iptables util-linux && rm -rf /var/lib/apt/lists/*
COPY containers/search/guard.sh /app/guard.sh
RUN chmod 555 /app/guard.sh
ENTRYPOINT ["/bin/sh","/app/guard.sh"]

FROM base AS gateway
COPY containers/search/gateway.py /app/gateway.py
USER 10003:10003
CMD ["python","/app/gateway.py"]

FROM base AS crawler
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 && rm -rf /var/lib/apt/lists/*
COPY containers/search/crawler-requirements.txt /app/requirements.txt
RUN pip install -r requirements.txt && PLAYWRIGHT_BROWSERS_PATH=/opt/browsers python -m playwright install --with-deps chromium && chmod -R a+rX /opt/browsers
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/browsers HOME=/tmp XDG_CACHE_HOME=/tmp/cache
COPY server /app/server
USER 10002:10002
CMD ["python","-m","uvicorn","server.goods.crawler_service:app","--host","0.0.0.0","--port","8790","--no-access-log"]

FROM base AS search
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.15.0 torchvision==0.29.2
COPY containers/search/search-requirements.txt /app/requirements.txt
RUN pip install -r requirements.txt && mkdir -p /data/models /data/catalog-images /data/goods-cache && chown -R 10001:10001 /data
ENV HOME=/tmp HF_HOME=/tmp/huggingface HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
COPY server /app/server
USER 10001:10001
CMD ["python","-m","uvicorn","server.goods.worker:app","--host","0.0.0.0","--port","8788","--no-access-log"]
