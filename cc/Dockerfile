FROM amazonlinux:2023

# Install Python 3.12
RUN dnf install which -y
RUN dnf -y install python3.12
RUN dnf install python3.12-pip -y
RUN dnf clean all

# Set WORKDIR
WORKDIR /usr/src/app

# Copy files to install Python packages
COPY stormhub/pyproject.toml .
COPY stormhub/stormhub ./stormhub
COPY hec-dss-python/pyproject.toml ./hec-dss-python/pyproject.toml
COPY hec-dss-python/setup.cfg ./hec-dss-python/setup.cfg
COPY hec-dss-python/src ./hec-dss-python/src
COPY cc/cc_py_sdk/cc_py_sdk-0.1.0-py3-none-any.whl ./cc/cc_py_sdk/cc_py_sdk-0.1.0-py3-none-any.whl
COPY cc/requirements.txt ./cc/requirements.txt

# Copy HEC-DSS native library for Linux
COPY cc/hec-dss-lib/libhecdss.so ./hec-dss-python/src/hecdss/lib/libhecdss.so

# Install Python packages
WORKDIR /usr/src/app/cc
RUN python3.12 -m pip install --upgrade pip setuptools wheel
RUN python3.12 -m pip install -r requirements.txt

# Copy main script
COPY cc/main.py .

# Set entry point (Optional, uncomment if needed)
# ENTRYPOINT ["python3.12", "main.py"]