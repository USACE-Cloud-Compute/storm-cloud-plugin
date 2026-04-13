FROM amazonlinux:2023

RUN dnf install -y --setopt=install_weak_deps=False \
        python3.12 python3.12-pip libgfortran shadow-utils && \
    useradd -m -u 1000 stormhub && \
    dnf remove -y shadow-utils && \
    dnf clean all && rm -rf /var/cache/dnf

WORKDIR /usr/src/app

# StormHub submodule (editable install from lib/stormhub)
# Fail early with a clear message if the submodule wasn't initialized
COPY lib/stormhub/pyproject.toml ./lib/stormhub/pyproject.toml
RUN test -s lib/stormhub/pyproject.toml || \
    (echo "ERROR: lib/stormhub is empty. Run: git submodule update --init" >&2 && exit 1)
COPY lib/stormhub/stormhub ./lib/stormhub/stormhub
COPY requirements.txt .
COPY constraints.txt .

# Install Python packages
RUN python3.12 -m pip install --no-cache-dir --upgrade pip setuptools wheel && \
    python3.12 -m pip install --no-cache-dir -c constraints.txt -r requirements.txt

# Plugin source
COPY src src

RUN chown -R stormhub:stormhub /usr/src/app
USER stormhub

ENTRYPOINT ["python3.12", "-u"]
CMD ["src/plugin.py"]
