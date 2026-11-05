const fs = require("fs");
const path = require("path");

const APP = "/home/master/applications/uccukpqmcy/private_html/app";

/**
 * Pass the app's own .env into PM2's env block as well as letting Next load it.
 *
 * Belt-and-braces, not a fix: Next's standalone server already loads .env at
 * boot. It is here because `/proc/<pid>/environ` shows only the environment a
 * process was STARTED with, never what the app loads afterwards — reading it on
 * a sibling site showed no SMTP_HOST and produced a false estate-wide "mail is
 * broken" alarm. Setting these at spawn makes that inspection tell the truth.
 *
 * The file is read HERE, on the server, rather than written into this config:
 * this file is committed, and a key in it would be a key in git.
 */
function envFromFile(cwd) {
  try {
    const out = {};
    for (const line of fs.readFileSync(path.join(cwd, ".env"), "utf8").split("\n")) {
      if (/^\s*#/.test(line)) continue;
      const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
      if (m) out[m[1]] = m[2].trim().replace(/^["']|["']$/g, "");
    }
    return out;
  } catch {
    return {};
  }
}

module.exports = {
  apps: [
    {
      name: "odt",
      cwd: APP,
      script: "server.js",
      interpreter: "/home/master/.nvm/versions/node/v22.23.2/bin/node",
      env: {
        // .env first, so the explicit values below always win on a collision.
        ...envFromFile(APP),
        NODE_ENV: "production",
        PORT: "3100",
        HOSTNAME: "127.0.0.1",
        /**
         * The content store, and the reason this app no longer needs Neon.
         *
         * It lives under `data/`, which the deploy script explicitly preserves
         * — every other path in the app directory is deleted and replaced on
         * each release. If this ever pointed outside `data/`, a deploy would
         * silently destroy every page published since the last one.
         */
        CONTENT_SQLITE_PATH: `${APP}/data/site.db`,
      },
      // 900M: 400M was the setting that restarted a sibling twelve times under
      // a crawl and served 502s each time. These apps sit at 120-170MB, but
      // this box has 2GB total and two other sites on it, so the cap matters
      // more here than it does on the estate server.
      max_memory_restart: "900M",
      autorestart: true,
      time: true,
    },
  ],
};
