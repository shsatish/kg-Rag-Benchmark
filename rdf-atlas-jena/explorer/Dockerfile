FROM python:3.12-alpine
WORKDIR /app
COPY server.py index.html ./
USER nobody
EXPOSE 8080
CMD ["python", "server.py"]
