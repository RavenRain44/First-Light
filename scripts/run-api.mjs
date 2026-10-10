// Cross-platform launcher for the backend (Windows venv uses Scripts/, POSIX uses bin/).
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

const backend = join(process.cwd(), "backend");
const win = process.platform === "win32";
const py = join(backend, ".venv", win ? "Scripts" : "bin", win ? "python.exe" : "python");
if (!existsSync(py)) {
  console.error("backend/.venv not found. Run `npm run setup` (or `make setup`) first.");
  process.exit(1);
}
const arg = process.argv[2];
const args = arg === "--test" ? ["-m", "pytest", "-q"]
  : arg === "--history" ? ["-m", "scripts.build_history"]
  : arg === "--cameras" ? ["-m", "scripts.cache_cameras"]
  : ["-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"];
const child = spawn(py, args, { cwd: backend, stdio: "inherit" });
child.on("exit", (code) => process.exit(code ?? 0));
