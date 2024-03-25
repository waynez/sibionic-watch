FROM python:3.12
WORKDIR /app
COPY . /app
RUN pip install --progress-bar off -r requirements.txt
CMD ["python", "./process.py"]
