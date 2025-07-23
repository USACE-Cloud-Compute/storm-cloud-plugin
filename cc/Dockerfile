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
COPY cc/cc_py_sdk/cc_py_sdk-0.1.1-py3-none-any.whl ./cc/cc_py_sdk/cc_py_sdk-0.1.1-py3-none-any.whl
COPY cc/requirements.txt ./cc/requirements.txt

# Install Python packages
WORKDIR /usr/src/app/cc
RUN python3.12 -m pip install --upgrade pip setuptools wheel
RUN python3.12 -m pip install -r requirements.txt

# Copy main script
COPY cc/main.py .

# Set entry point
ENTRYPOINT ["python3.12", "main.py"]