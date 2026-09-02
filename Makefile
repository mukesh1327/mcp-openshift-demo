BINARY := mcp-openshift-server
IMAGE  := mcp-openshift-server
VERSION := $(shell git describe --tags --always --dirty 2>/dev/null || echo dev)
COMMIT  := $(shell git rev-parse --short HEAD 2>/dev/null || echo none)
BUILD_DATE := $(shell date -u +%Y-%m-%dT%H:%M:%SZ)

LDFLAGS := -s -w \
	-X mcp-openshift-server/internal/version.Version=$(VERSION) \
	-X mcp-openshift-server/internal/version.Commit=$(COMMIT) \
	-X mcp-openshift-server/internal/version.BuildDate=$(BUILD_DATE)

.PHONY: build
build:
	go build -ldflags "$(LDFLAGS)" -o bin/$(BINARY) ./cmd/mcp-openshift-server

.PHONY: test
test:
	go test ./... -race -count=1

.PHONY: lint
lint:
	golangci-lint run

.PHONY: fmt
fmt:
	gofmt -l -w .

.PHONY: run
run: build
	./bin/$(BINARY) -transport=stdio

.PHONY: run-http
run-http: build
	./bin/$(BINARY) -transport=http -http-addr=:8080

.PHONY: docker-build
docker-build:
	docker build \
		--build-arg VERSION=$(VERSION) \
		--build-arg COMMIT=$(COMMIT) \
		--build-arg BUILD_DATE=$(BUILD_DATE) \
		-t $(IMAGE):$(VERSION) .

.PHONY: clean
clean:
	rm -rf bin/
