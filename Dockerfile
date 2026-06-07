FROM python:3.14-bookworm

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
ffmpeg curl wget cups nano \
&& rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir numpy pandas matplotlib requests beautifulsoup4

COPY ./requirements.txt .
RUN pip install --no-cache-dir -r ./requirements.txt

COPY . .

CMD ["python3", "./main.py"]
