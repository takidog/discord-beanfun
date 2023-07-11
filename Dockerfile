FROM python:3.10-slim-buster

COPY . /usr/src/app

WORKDIR /usr/src/app/src

RUN pip install -r ../requirements.txt


CMD [ "python","-u", "./main.py" ]