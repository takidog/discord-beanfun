# The released innoextract builds cannot parse the Inno Setup 6.3 installer the
# GGM launcher ships as, so build a current one and copy just the binary over.
# Static Boost.iostreams pulls in libz and libbz2, which the build requires to be
# present as static libraries.
FROM debian:bookworm-slim AS innoextract

ARG INNOEXTRACT_REF=master

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        git \
        libboost-all-dev \
        libbz2-dev \
        liblzma-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch "${INNOEXTRACT_REF}" \
        https://github.com/dscharrer/innoextract.git /usr/src/innoextract \
    && cmake -S /usr/src/innoextract -B /usr/src/innoextract/build \
        -DCMAKE_BUILD_TYPE=Release \
        -DUSE_STATIC_LIBS=ON \
    && cmake --build /usr/src/innoextract/build --parallel \
    && strip /usr/src/innoextract/build/innoextract


FROM python:3.10-slim-bookworm

COPY --from=innoextract /usr/src/innoextract/build/innoextract /usr/local/bin/innoextract

# Fails the build if the static link left anything behind.
RUN innoextract --version

COPY . /usr/src/app

WORKDIR /usr/src/app/src

RUN pip install -r ../requirements.txt

EXPOSE 8080

CMD [ "python","-u", "./main.py" ]
