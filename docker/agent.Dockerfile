FROM python:3.11-slim

# Install system utilities, compilation headers, and browser libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    locales \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libasound2t64 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Force strict UTF-8 system mapping to render TUI layouts cleanly without border artifacts
RUN sed -i -e 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen && locale-gen
ENV LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8 \
    PYTHONIOENCODING=utf-8 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Clone the targeted package code base cleanly into the /app workspace
RUN git clone https://github.com/theflakes/deep-research-agent.git .

# Dynamically trigger the inline package setup directly inside the repository directory
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -e .

# Pre-fetch and bake in the required browser engines
RUN if pip show playwright > /dev/null 2>&1; then \
        python -m playwright install chromium --with-deps; \
    fi

# Fire up the application's core TUI script automatically at run time
CMD ["python", "main.py"]
