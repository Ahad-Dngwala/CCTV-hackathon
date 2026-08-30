FROM postgis/postgis:16-3.4

# Install pgvector extension alongside PostGIS
RUN apt-get update && \
    apt-get install -y postgresql-16-pgvector && \
    rm -rf /var/lib/apt/lists/*
