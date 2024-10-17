FROM python:3.9-slim-buster

COPY kiirkirjutaja/site-packages /usr/local/lib/python3.9/

RUN apt-get update && apt-get install  -y --no-install-recommends git ffmpeg

COPY models /opt/models

RUN git clone https://github.com/alumae/online_speaker_change_detector.git /opt/OnlineSpeakerChangeDetector

RUN mkdir /opt/kiirkirjutaja \
    && cd /opt/kiirkirjutaja && ln -s ../models
    
COPY kiirkirjutaja/*.py /opt/kiirkirjutaja/

COPY kiirkirjutaja/logging.ini /opt/kiirkirjutaja/

ENV PYTHONPATH="/opt/OnlineSpeakerChangeDetector"

WORKDIR /opt

EXPOSE 8000

ENTRYPOINT ["python", "-m", "uvicorn", "kiirkirjutaja.main:app", "--proxy-headers", "--host", "0.0.0.0", "--port", "8000",  "--log-config", "/opt/kiirkirjutaja/logging.ini"]
