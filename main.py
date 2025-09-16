FROM python:3.11-slim

# Install system dependencies for manim
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libcairo2 \
    libcairo2-dev \
    libpango-1.0-0 \
    libpango1.0-dev \
    libglib2.0-0 \
    texlive-latex-base \
    texlive-latex-extra \
    texlive-fonts-extra \
    texlive-fonts-recommended \
    texlive-science \
    tipa \
    build-essential \
    python3-dev \
    pkg-config \
    libfreetype6-dev \
    libffi-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Use Render's dynamic PORT instead of hardcoding
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port $PORT"]
