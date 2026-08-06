FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# HF Spaces runs the container as UID 1000; run as that user so the app can
# write its OCR cache dir at runtime.
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user insurance_rater/ insurance_rater/
COPY --chown=user webapp/ webapp/
COPY --chown=user bundle/raters/ bundle/raters/

# HF routes to app_port (README front-matter) = 7860; hosts that inject $PORT
# (e.g. Render) override this at runtime.
ENV PORT=7860
EXPOSE 7860

CMD ["sh", "-c", "uvicorn webapp.app:app --host 0.0.0.0 --port ${PORT}"]
