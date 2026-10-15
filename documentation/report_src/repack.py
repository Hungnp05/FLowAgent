import sys
import zipfile
from pathlib import Path

source_dir, output_path = Path(sys.argv[1]), sys.argv[2]
files = sorted(p for p in source_dir.rglob("*") if p.is_file())
files.sort(key=lambda p: p.name != "[Content_Types].xml")
with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in files:
        archive.write(path, path.relative_to(source_dir).as_posix())
