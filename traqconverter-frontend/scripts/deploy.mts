// Build locally, ship the standalone bundle over SFTP, rebuild the native
// SQLite binding on the server, reload PM2. Static assets are copied into
// public_html so Apache serves them without touching Node.
//   SSH_HOST=… SSH_USER=… SSH_PASS=… npx tsx scripts/deploy.mts [--skip-build]
import { Client } from "ssh2";
import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const HOST = process.env.SSH_HOST!, USER = process.env.SSH_USER!, PASS = process.env.SSH_PASS!;
if (!HOST || !USER || !PASS) throw new Error("SSH_HOST / SSH_USER / SSH_PASS required");
const APP = "/home/master/applications/uccukpqmcy/private_html/app";
const HTML = "/home/master/applications/uccukpqmcy/public_html";
// SFTP is chrooted to /home/master; shell commands are not.
const sftpPath = (p: string) => p.replace(/^\/home\/master/, "");
const NODE_BIN = "/home/master/.nvm/versions/node/v22.23.2/bin";
const root = path.resolve(import.meta.dirname, "..");
const run = (cmd: string, env?: Record<string, string>) =>
  execSync(cmd, { cwd: root, stdio: "inherit", env: { ...process.env, ...env } });

// robots.txt is PRERENDERED, so it freezes whatever SITE_URL the build saw —
// and the build runs here, where .env.local points at localhost:3000 for dev.
// Production shipped "Sitemap: http://localhost:3000/sitemap.xml" for days:
// the server's own .env is correct but a prerendered file never reads it.
const PROD_URL = "https://www.onlinedoctranslator.ai";

/**
 * Build-time environment, read from `.env.deploy` (gitignored).
 *
 * EVERY `NEXT_PUBLIC_*` VALUE IS BAKED INTO THE CLIENT BUNDLE, so a wrong one
 * is not a server misconfiguration to be corrected later — it ships to every
 * visitor until the next release. `.env.local` here holds an EMPTY
 * NEXT_PUBLIC_API_URL for local work, and building with that would point the
 * production front end at nothing.
 *
 * So this refuses to build rather than guess. The values belong to the Vercel
 * project; copy them from there.
 */
const buildEnv: Record<string, string> = { SITE_URL: PROD_URL, NEXT_PUBLIC_SITE_URL: PROD_URL };
const envDeploy = path.join(root, ".env.deploy");
if (fs.existsSync(envDeploy)) {
  for (const line of fs.readFileSync(envDeploy, "utf8").split("\n")) {
    if (/^\s*#/.test(line)) continue;
    const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
    if (m) buildEnv[m[1]] = m[2].trim().replace(/^["']|["']$/g, "");
  }
}
if (!process.argv.includes("--skip-build")) {
  if (!buildEnv.NEXT_PUBLIC_API_URL) {
    console.error(
      `NEXT_PUBLIC_API_URL is not set.\n\n` +
        `It is compiled INTO the client bundle, so building without it ships a\n` +
        `front end that calls nothing. Put the production value in\n` +
        `  ${envDeploy}\n` +
        `(copy it from the Vercel project's environment variables), then re-run.`,
    );
    process.exit(1);
  }
  run("npm run build", buildEnv);
}

fs.rmSync(path.join(root, ".deploy"), { recursive: true, force: true });
fs.mkdirSync(path.join(root, ".deploy"));
run("cp -R .next/standalone/. .deploy/ && mkdir -p .deploy/.next/static .deploy/public && cp -R .next/static/. .deploy/.next/static/ && cp -R public/. .deploy/public/ && cp deploy/ecosystem.config.js .deploy/");
run("rm -rf .deploy/node_modules/better-sqlite3/build .deploy/data .deploy/.env .deploy/.env.local");
run("COPYFILE_DISABLE=1 tar --no-xattrs -czf .deploy.tgz -C .deploy . 2>/dev/null || COPYFILE_DISABLE=1 tar -czf .deploy.tgz -C .deploy .");
const size = fs.statSync(path.join(root, ".deploy.tgz")).size;
console.log(`bundle ${(size / 1e6).toFixed(1)} MB`);

const conn = new Client();
await new Promise<void>((res, rej) => conn.on("ready", res).on("error", rej).connect({ host: HOST, username: USER, password: PASS, readyTimeout: 20000 }));

function exec(cmd: string): Promise<{ code: number; out: string }> {
  return new Promise((res, rej) => {
    conn.exec(cmd, (err, stream) => {
      if (err) return rej(err);
      let out = "";
      stream.on("data", (d: Buffer) => { out += d.toString(); process.stdout.write(d); });
      stream.stderr.on("data", (d: Buffer) => { out += d.toString(); process.stderr.write(d); });
      stream.on("close", (code: number) => res({ code, out }));
    });
  });
}
async function put(local: string, remote: string): Promise<void> {
  await new Promise<void>((res, rej) => conn.sftp((err, sftp) => (err ? rej(err) : sftp.fastPut(local, remote, (e) => (e ? rej(e) : res())))));
}

await exec(`mkdir -p ${APP} ${APP}/data ${HTML}`);
await put(path.join(root, ".deploy.tgz"), sftpPath(`${APP}/.deploy.tgz`));
await put(path.join(root, "deploy/proxy.php"), sftpPath(`${HTML}/proxy.php`));
await put(path.join(root, "deploy/htaccess"), sftpPath(`${HTML}/.htaccess.next`));
await put(path.join(root, "deploy/user.ini"), sftpPath(`${HTML}/.user.ini`));

const script = `
set -e
export PATH=${NODE_BIN}:$PATH
cd ${APP}
find . -mindepth 1 -maxdepth 1 ! -name data ! -name .env ! -name .deploy.tgz -exec rm -rf {} +
tar -xzf .deploy.tgz && rm .deploy.tgz
# The standalone trace drops the SQLite sources, and no prebuilt binary exists
# for this Node ABI, so the binding is built on the server once and reused.
if [ -f data/better-sqlite3.tgz ]; then rm -rf node_modules/better-sqlite3 && tar -xzf data/better-sqlite3.tgz -C node_modules; fi
if ! node -e "require('better-sqlite3')(':memory:')" >/dev/null 2>&1; then
  rm -rf node_modules/better-sqlite3 && npm install --no-save --no-audit --no-fund better-sqlite3@13.0.3 >/dev/null 2>&1
  tar -czf data/better-sqlite3.tgz -C node_modules better-sqlite3
fi
node -e "require('better-sqlite3')(':memory:'); console.log('sqlite ok')"
mkdir -p ${HTML}/_next && rm -rf ${HTML}/_next/static && cp -R .next/static ${HTML}/_next/static
cp -R public/. ${HTML}/
[ -f .env ] || echo "missing ${APP}/.env"
pm2 startOrReload ecosystem.config.js --update-env >/dev/null && pm2 save >/dev/null
sleep 2
curl -s -o /dev/null -w "node app: %{http_code}\\n" -H "Host: www.onlinedoctranslator.ai" http://127.0.0.1:3100/
`;
const r = await exec(`bash -lc '${script.replace(/'/g, `'\\''`)}'`);
conn.end();
fs.rmSync(path.join(root, ".deploy.tgz"), { force: true });
if (r.code !== 0) { console.error("deploy failed"); process.exit(1); }
console.log("deployed; .htaccess staged as .htaccess.next (activate with the cutover step)");
