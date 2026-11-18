"""Import the licensed Ontosphere source snapshot; omit recordings and benchmarks.

Download the pinned archive into tmp/ontosphere-reference/upstream.tar.gz first.
Local integration changes live beside the upstream source and are documented in
frontend/ontosphere/ASSESSMENT-INTEGRATION.md.
"""
from pathlib import Path, PurePosixPath
import hashlib
import json
import tarfile

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "frontend/ontosphere"
REVISION = "6bdcb78b531b2300d047fbcdd10246fc62611cb9"
ARCHIVE = ROOT / "tmp/ontosphere-reference/upstream.tar.gz"
ROOT_FILES = {
    "LICENSE", "ACKNOWLEDGEMENTS.md", "README.md", "AGENTS.md", "package.json",
    "package-lock.json", "index.html", "vite.config.ts", "tailwind.config.ts",
    "tsconfig.json", "tsconfig.app.json", "tsconfig.node.json", "components.json",
    "vite-plugin-bookmarklet.ts", "vite-plugin-mcp-manifest.ts", "vite-plugin-worker-comunica.ts",
}

def main():
    count = 0
    total = 0
    with tarfile.open(ARCHIVE, "r:gz") as archive:
        for member in archive:
            if not member.isfile():
                continue
            relative = PurePosixPath(member.name).relative_to("ontosphere-" + REVISION)
            name = relative.as_posix()
            if not (name in ROOT_FILES or name.startswith(("src/", "scripts/", "patches/", "public/"))):
                continue
            if name.endswith((".mp4", ".webm")) or name.startswith("public/bench-"):
                continue
            target = DESTINATION.joinpath(*relative.parts)
            if not target.resolve().is_relative_to(DESTINATION.resolve()):
                raise RuntimeError("Archive path escapes the vendor directory")
            content = archive.extractfile(member).read()
            if target.exists() and target.read_bytes() != content:
                raise RuntimeError(f"Existing vendor file has local changes: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            count += 1
            total += len(content)
    provenance = {"project":"Ontosphere", "version":"1.8.1", "repository":"https://github.com/ThHanke/ontosphere", "revision":REVISION, "license":"Apache-2.0", "archive_sha256":hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()}
    (DESTINATION / "upstream.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"files":count,"bytes":total,**provenance}))

if __name__ == "__main__":
    main()
