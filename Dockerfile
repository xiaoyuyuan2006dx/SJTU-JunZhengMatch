FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/src JZ_DATA_DIR=/data JZ_CONFIG_DIR=/data JZ_MANAGED_DATA=1
WORKDIR /app
COPY packaging/requirements.txt packaging/requirements.txt
RUN pip install --no-cache-dir -r packaging/requirements.txt && useradd -u 10001 -m reviewer && mkdir /data && chown reviewer:reviewer /data
COPY --chown=reviewer:reviewer src ./src
COPY --chown=reviewer:reviewer packaging/launcher.py ./packaging/launcher.py
COPY --chown=reviewer:reviewer *.md ./
COPY --chown=reviewer:reviewer data ./data
USER reviewer
EXPOSE 8765
HEALTHCHECK --interval=20s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health',timeout=2)"
CMD ["python","packaging/launcher.py","--host","0.0.0.0","--no-open"]
