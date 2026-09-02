# syntax=docker/dockerfile:1

FROM golang:1.26 AS builder
WORKDIR /src

COPY go.mod go.sum ./
RUN go mod download

COPY cmd ./cmd
COPY internal ./internal

ARG VERSION=dev
ARG COMMIT=none
ARG BUILD_DATE=unknown

RUN CGO_ENABLED=0 GOOS=linux go build \
    -ldflags "-s -w \
      -X mcp-openshift-server/internal/version.Version=${VERSION} \
      -X mcp-openshift-server/internal/version.Commit=${COMMIT} \
      -X mcp-openshift-server/internal/version.BuildDate=${BUILD_DATE}" \
    -o /out/mcp-openshift-server \
    ./cmd/mcp-openshift-server

FROM gcr.io/distroless/static-debian12:nonroot
WORKDIR /
COPY --from=builder /out/mcp-openshift-server /mcp-openshift-server

USER nonroot:nonroot
EXPOSE 8080

ENTRYPOINT ["/mcp-openshift-server"]
