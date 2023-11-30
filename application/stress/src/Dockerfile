FROM alpine:3.18.4

RUN apk add --no-cache stress-ng

# Default timeout value
ENV TIMEOUT=30s

CMD ["sh", "-c", "stress-ng --cpu 1 --timeout $TIMEOUT"]

