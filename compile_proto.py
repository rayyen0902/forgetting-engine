"""Host script to generate Python gRPC stubs from the .proto definition.

Usage:
    python compile_proto.py

Output:
    proto/forgetting_engine_pb2.py
    proto/forgetting_engine_pb2_grpc.py
"""

import subprocess
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent
    proto_dir = root / "proto"
    proto_file = proto_dir / "forgetting_engine.proto"

    if not proto_file.exists():
        sys.exit(f"Proto file not found: {proto_file}")

    cmd = [
        sys.executable, "-m", "grpc_tools.protoc",
        f"--proto_path={proto_dir}",
        f"--python_out={proto_dir}",
        f"--grpc_python_out={proto_dir}",
        str(proto_file),
    ]
    subprocess.run(cmd, check=True)

    # Fix the generated import path (protoc defaults to relative imports)
    generated = proto_dir / "forgetting_engine_pb2_grpc.py"
    if generated.exists():
        content = generated.read_text()
        content = content.replace(
            "import forgetting_engine_pb2",
            "from proto import forgetting_engine_pb2",
        )
        generated.write_text(content)

    print("Proto stubs generated.")


if __name__ == "__main__":
    main()
