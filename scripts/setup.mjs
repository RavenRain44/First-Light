// One-time setup: dependencies, .env, and the historical library for Replay.
import { execFileSync, execSync } from "node:child_process";
import { copyFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const win = process.platform === "win32";
const sh = (cmd, cwd = process.cwd()) => { console.log(`> ${cmd}`); execSync(cmd, { stdio: "inherit", cwd }); };
const backend = join(process.cwd(), "backend");
const venvPy = join(backend, ".venv", win ? "Scripts" : "bin", win ? "python.exe" : "python");
if (!existsSync(venvPy)) sh(`${win ? "python" : "python3"} -m venv .venv`, backend);
sh(`"${venvPy}" -m pip install -q -r requirements.txt`, backend);
sh("npm install --no-audit --no-fund", join(process.cwd(), "frontend"));
if (!existsSync(".env")) { copyFileSync(".env.example", ".env"); console.log("created .env from .env.example"); }
console.log("Building historical library from the committed cache (Replay, analogs, backtest)…");
execFileSync(venvPy, ["-m", "scripts.build_history"], {
  cwd: backend,
  stdio: "inherit",
  env: { ...process.env, DEMO_MODE: "true" },
});
console.log("\nSetup done. Run `npm run dev` -> API on :8000, dashboard on http://localhost:5173");
