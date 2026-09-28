# ---- Stage 1: "builder" -------------------------------------------------------
# A full Python image with compilers and build tools, used only to install packages.
FROM python:3.11-bookworm AS builder

# Put all packages in one folder we can copy out later.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy ONLY requirements first, so Docker can reuse this slow step when just code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# ---- Stage 2: the final image --------------------------------------------------
# A slim Python image: no compilers, much smaller. This is what actually runs.
FROM python:3.11-slim-bookworm

# Take the finished packages from the builder stage; everything else there is thrown away.
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Run as an ordinary user, not root (the all-powerful admin), in case anything goes wrong.
RUN useradd --create-home app
WORKDIR /app
COPY --chown=app:app *.py schema.sql ./
COPY --chown=app:app static ./static
RUN mkdir data && chown app:app data
USER app

# The same image runs both services; docker-compose.yml picks which script with `command:`.
CMD ["python", "processor.py"]
