FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
RUN python -m pip install --no-cache-dir --no-deps \
    pytest==9.1.1 iniconfig==2.3.0 packaging==26.3 pluggy==1.6.0 pygments==2.21.0
COPY collector.py pytest.ini /opt/delivery/
RUN chmod 0555 /opt/delivery && chmod 0444 /opt/delivery/collector.py /opt/delivery/pytest.ini
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
USER 65532:65532
WORKDIR /workspace
CMD ["python", "-c", "import time; time.sleep(7200)"]
