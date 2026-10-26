FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 JZ_DATA_DIR=/data
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd -u 10001 -m reviewer && mkdir /data && chown reviewer:reviewer /data
COPY --chown=reviewer:reviewer *.py *.md ./
COPY --chown=reviewer:reviewer frontend ./frontend
COPY --chown=reviewer:reviewer data ./data
USER reviewer
EXPOSE 8765
HEALTHCHECK --interval=20s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health',timeout=2)"
CMD ["python","entrypoint.py","--host","0.0.0.0","--no-open"]
