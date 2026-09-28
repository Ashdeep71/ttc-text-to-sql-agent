FROM postgres:16

COPY db/init/ /docker-entrypoint-initdb.d/

COPY data/processed/*.csv.gz /data/