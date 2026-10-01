"""Run model-authored programs with corpus access, excluding host/oracle access."""

from pathlib import Path
import subprocess
import time

import markdown_it
import mdurl


class Sandbox:
    def __init__(self, corpus: Path, scratch: Path, *, interface: bool, provider: Path | None = None):
        self.corpus = corpus.resolve()
        self.scratch = scratch.resolve()
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.interface = interface
        self.provider = (provider or Path(__file__).with_name("access.py")).resolve()

    def run(self, command: str, *, max_chars: int = 24000):
        if not isinstance(command, str):
            raise ValueError("command must be a string")
        if not isinstance(max_chars, int) or not 1000 <= max_chars <= 100000:
            raise ValueError("max_chars must be an integer between 1000 and 100000")
        args = ["bwrap", "--die-with-parent", "--new-session", "--unshare-net", "--unshare-pid",
                "--clearenv", "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "HOME", "/tmp",
                "--setenv", "PYTHONPATH", "/opt:/opt/deps", "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
                "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin",
                "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
                "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
                "--ro-bind", str(self.corpus), "/work", "--bind", str(self.scratch), "/scratch",
                "--dir", "/opt/deps", "--chdir", "/work"]
        for module in (markdown_it, mdurl):
            args += ["--ro-bind", str(Path(module.__file__).parent), f"/opt/deps/{module.__name__}"]
        if self.interface:
            args += ["--ro-bind", str(self.provider), "/opt/access.py"]
        args += ["/bin/bash", "--noprofile", "--norc", "-c", command]
        started = time.monotonic()
        try:
            process = subprocess.run(args, text=True, capture_output=True, stdin=subprocess.DEVNULL, timeout=30)
            output = process.stdout + process.stderr
            code = process.returncode
        except subprocess.TimeoutExpired as error:
            output = "Command exceeded 30 seconds.\n"
            for value in (error.stdout, error.stderr):
                if value:
                    output += value.decode(errors="replace") if isinstance(value, bytes) else value
            code = 124
        return {"exit_code": code, "output": output[:max_chars],
                "truncated": len(output) > max_chars, "output_chars": len(output),
                "wall_seconds": round(time.monotonic() - started, 4)}


TOOL = {
    "name": "run", "description": "Run bash/Python programs against the local corpus at /work. "
        "Read-only corpus; persistent writable /scratch. Available: rg, bash, python3, "
        "Python sqlite3 and markdown_it. Batch reads, filters, loops and joins freely in one call. "
        "No network or host files. Output limit 24000 characters by default; optional max_chars up to 100000. "
        "No need to print intermediate data that your program can process.",
    "inputSchema": {"type": "object", "properties": {
        "command": {"type": "string"}, "max_chars": {"type": "integer", "minimum": 1000, "maximum": 100000}},
        "required": ["command"], "additionalProperties": False},
}
