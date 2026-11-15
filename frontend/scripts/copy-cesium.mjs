// Copies Cesium's static runtime (workers, assets, widgets CSS, prebuilt Cesium.js) into public/cesium.
// The app loads Cesium from there with a <script> tag, which keeps it out of the bundler entirely.
import { cpSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(root, "node_modules", "cesium", "Build", "Cesium");
const dst = join(root, "public", "cesium");
const version = JSON.parse(readFileSync(join(root, "node_modules", "cesium", "package.json"), "utf8")).version;
const stamp = join(dst, ".version");
if (existsSync(stamp) && readFileSync(stamp, "utf8") === version) {
  console.log(`cesium ${version} already in public/cesium`);
} else {
  mkdirSync(dst, { recursive: true });
  for (const d of ["Assets", "ThirdParty", "Widgets", "Workers", "Cesium.js"]) cpSync(join(src, d), join(dst, d), { recursive: true });
  writeFileSync(stamp, version);
  console.log(`copied cesium ${version} to public/cesium`);
}
