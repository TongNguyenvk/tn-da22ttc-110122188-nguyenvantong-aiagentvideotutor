# Base image: Official Playwright Python with all browser dependencies
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

# Set working directory
WORKDIR /app

# Install Node.js 20 LTS
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    npm install -g pnpm

# Install FFmpeg and other system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-noto-cjk \
    fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Copy webreel packages first (for caching)
COPY packages/ /app/packages/
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml turbo.json /app/

# Install Node.js dependencies and build webreel
RUN pnpm install --frozen-lockfile && \
    pnpm --filter @webreel/core build && \
    pnpm --filter webreel build

# Copy Python requirements
COPY webreel-ai-agent/requirements.txt /app/webreel-ai-agent/

# Install Python dependencies
RUN pip install --no-cache-dir -r /app/webreel-ai-agent/requirements.txt

# Pre-download EasyOCR models (English + Vietnamese)
RUN python -c "import easyocr; easyocr.Reader(['en', 'vi'], gpu=False, verbose=True)"

# Copy the rest of the Python application
COPY webreel-ai-agent/ /app/webreel-ai-agent/

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/webreel-ai-agent
ENV NODE_ENV=production
# Playwright will use the pre-installed browsers in the image
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Expose Streamlit port
EXPOSE 8501

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# Default command: run Streamlit UI
CMD ["streamlit", "run", "webreel-ai-agent/src/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
