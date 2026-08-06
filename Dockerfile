FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user insurance_rater/ insurance_rater/
COPY --chown=user webapp/ webapp/
COPY --chown=user bundle/raters/ bundle/raters/

ENV OMP_THREAD_LIMIT=1

ENV PORT=7860
EXPOSE 7860

CMD ["sh", "-c", "uvicorn webapp.app:app --host 0.0.0.0 --port ${PORT}"]
