// Cross-platform launcher for the backend (Windows venv uses Scripts/, POSIX uses bin/).
import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd();
const backend = join(root, "backend");
const win = process.platform === "win32";
const py = join(backend, ".venv", win ? "Scripts" : "bin", win ? "python.exe" : "python");
if (!existsSync(py)) {
  console.error("backend/.venv not found. Run `npm run setup` (or `make setup`) first.");
  process.exit(1);
}

const getApiPort = () => {
  let value = process.env.API_PORT;
  const envPath = join(root, ".env");
  if (!value && existsSync(envPath)) {
    const match = readFileSync(envPath, "utf8").match(/^\s*API_PORT\s*=\s*(?:"([^"]*)"|'([^']*)'|([^#\s]+))/m);
    value = match?.slice(1).find((candidate) => candidate !== undefined);
  }
  const port = Number(value ?? 8000);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    console.error(`Invalid API_PORT: ${value}`);
    process.exit(1);
  }
  return String(port);
};

const arg = process.argv[2];
const args = arg === "--test" ? ["-m", "pytest", "-q"]
  : arg === "--history" ? ["-m", "scripts.build_history"]
  : arg === "--cameras" ? ["-m", "scripts.cache_cameras"]
  : arg === "--examples" ? ["-m", "scripts.seed_example_decisions"]
  : ["-m", "uvicorn", "app.main:app", "--reload", "--port", getApiPort(), "--timeout-graceful-shutdown", "5"];
const child = spawn(py, args, { cwd: backend, stdio: "inherit" });
child.on("exit", (code) => process.exit(code ?? 0));
