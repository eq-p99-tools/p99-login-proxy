import { execSync } from "node:child_process";
import fs from "node:fs";

const version = process.argv[2] ?? process.env.RELEASE_VERSION;
if (!version) {
  console.error("Usage: node scripts/stamp-release-version.mjs <version>");
  process.exit(1);
}

execSync(`npm version ${version} --no-git-tag-version --allow-same-version`, {
  stdio: "inherit",
});

let cargo = fs.readFileSync("Cargo.toml", "utf8");
cargo = cargo.replace(/(\[workspace\.package\][\s\S]*?version\s*=\s*")[^"]+/, `$1${version}`);
fs.writeFileSync("Cargo.toml", cargo);

const tauriPath = "src-tauri/tauri.conf.json";
const tauri = JSON.parse(fs.readFileSync(tauriPath, "utf8"));
tauri.version = version;
fs.writeFileSync(tauriPath, `${JSON.stringify(tauri, null, 2)}\n`);

console.log(`Stamped release version ${version}`);
