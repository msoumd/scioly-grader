import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";

/** Make the fake sheet photos / PDF / camera video once (deterministic, git-ignored). */
export default function globalSetup() {
  const assets = path.resolve(import.meta.dirname, ".assets");
  if (existsSync(path.join(assets, "camera_team11.y4m"))) return;
  execFileSync("uv", ["run", "python", "scripts/e2e_assets.py", assets], {
    cwd: path.resolve(import.meta.dirname, "../../backend"),
    stdio: "inherit",
  });
}
