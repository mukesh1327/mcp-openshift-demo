IMAGE ?= openshift-mcp-server
TAG   ?= dev
CONTAINER_ENGINE ?= $(shell command -v podman 2>/dev/null || echo docker)
PY ?= python

.PHONY: install
install:
	$(PY) -m pip install -e ".[dev]"

.PHONY: test
test:
	$(PY) -m pytest -q

.PHONY: lint
lint:
	$(PY) -m ruff check src/ tests/
	$(PY) -m ruff format --check src/ tests/

.PHONY: fmt
fmt:
	$(PY) -m ruff check --fix src/ tests/
	$(PY) -m ruff format src/ tests/

.PHONY: run
run:
	$(PY) -m openshift_mcp --transport stdio

.PHONY: run-http
run-http:
	$(PY) -m openshift_mcp --transport http --host 127.0.0.1 --port 8080

.PHONY: image
image:
	$(CONTAINER_ENGINE) build -f Containerfile -t $(IMAGE):$(TAG) .
