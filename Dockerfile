FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml settings.toml ./
COPY src/ src/
COPY client/ client/
COPY proto/ proto/

RUN pip install --no-cache-dir -e ".[dev]"

# Generate gRPC stubs (if proto files present)
# RUN python -m grpc_tools.protoc ...

EXPOSE 50051 9000

CMD ["python", "-m", "memory_service.main"]
