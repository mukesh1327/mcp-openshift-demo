# syntax=docker/dockerfile:1
#
# Red Hat UBI-based image. Builds with `docker build` or `podman build`:
#   podman build -f Containerfile -t openshift-mcp-server:dev .

# --- build stage: install into a self-contained venv -----------------------
FROM registry.access.redhat.com/ubi9/python-312:latest AS builder
USER 0

WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src

RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/venv/bin/pip install --no-cache-dir .

# --- runtime stage --------------------------------------------------------
FROM registry.access.redhat.com/ubi9/python-312-minimal:latest

LABEL name="openshift-mcp-server" \
      summary="MCP server exposing OpenShift/Kubernetes cluster operations as tools" \
      description="MCP server exposing OpenShift/Kubernetes cluster operations as tools" \
      io.k8s.description="MCP server exposing OpenShift/Kubernetes cluster operations as tools" \
      io.openshift.tags="mcp,openshift,kubernetes"

COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    MCP_TRANSPORT=http \
    MCP_HOST=0.0.0.0

# Non-root; OpenShift's restricted SCC still overrides with an arbitrary UID.
USER 1001
EXPOSE 8080
ENTRYPOINT ["openshift-mcp-server"]
