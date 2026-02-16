FROM python:3.12-slim

RUN pip install --no-cache-dir fastapi uvicorn

# Pre-install commonly useful packages for code execution
RUN pip install --no-cache-dir \
    pypdf \
    pandas \
    openpyxl \
    matplotlib \
    numpy \
    requests \
    beautifulsoup4 \
    Pillow

RUN useradd --create-home --shell /bin/bash sandbox
RUN mkdir -p /data/files /data/skills && chown sandbox:sandbox /data/files /data/skills
USER sandbox
WORKDIR /home/sandbox

# Enable user-level pip installs at runtime (into tmpfs)
ENV PIP_TARGET=/tmp/pip-packages
ENV PYTHONPATH=/tmp/pip-packages

COPY main.py .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
