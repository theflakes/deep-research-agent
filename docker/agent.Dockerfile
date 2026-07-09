FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Clone targeted deep-research-agent repository dynamically
RUN git clone https://github.com/theflakes/deep-research-agent.git .

# Install dependencies if present
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

# Fallback bash launcher if executed outside explicit container calls
CMD ["/bin/bash"]