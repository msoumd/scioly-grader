import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";

/** Make the fake sheet photos / PDF / camera video once (deterministic, git-ignored). */
export default function globalSetup() {
  const assets = path.resolve(import.meta.dirname, ".assets");
  const needed = [
    "camera_team11.y4m",
    "three_pages.pdf",
    "review_erased_team4.jpg",
    "review_team99.jpg",
  ];
  if (needed.every((f) => existsSync(path.join(assets, f)))) return;
  execFileSync("uv", ["run", "python", "scripts/e2e_assets.py", assets], {
    cwd: path.resolve(import.meta.dirname, "../../backend"),
    stdio: "inherit",
  });
}
