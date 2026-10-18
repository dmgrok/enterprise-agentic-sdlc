import { mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '../..');
const sources = join(root, 'docs/diagrams');
const check = process.argv.includes('--check');
const temporary = mkdtempSync(join(tmpdir(), 'sdlc-diagrams-'));
const candidates = [process.env.PUPPETEER_EXECUTABLE_PATH,
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser'];
const browser = candidates.find(path => path && existsSync(path));
if (!browser) throw new Error('Set PUPPETEER_EXECUTABLE_PATH to a Chrome or Chromium executable');
const config = join(temporary, 'browser.json');
writeFileSync(config, JSON.stringify({ executablePath: browser, args: ['--no-sandbox'] }));

try {
  const files = readdirSync(sources).filter(name => name.endsWith('.mmd')).sort();
  for (const name of files) {
    const output = join(check ? temporary : sources, name.replace(/\.mmd$/, '.svg'));
    const result = spawnSync(process.execPath, [join(here, 'node_modules/@mermaid-js/mermaid-cli/src/cli.js'),
      '-i', join(sources, name), '-o', output, '-p', config,
      '-c', join(sources, 'mermaid-config.json'), '-b', 'white'], { stdio: 'inherit' });
    if (result.status !== 0) throw new Error(`Diagram failed to render: ${name}`);
    let svg = readFileSync(output, 'utf8');
    if (!svg.includes('<svg') || !svg.includes('<text')) throw new Error(`Diagram has no visible text: ${name}`);
    // Give image embeds an intrinsic size instead of the SVG's default 300x150 viewport.
    svg = svg.replace(/<svg\b[^>]*>/, tag => {
      const bounds = tag.match(/viewBox="([^"]+)"/)[1].split(/\s+/).map(Number);
      const width = Math.ceil(bounds[2]);
      const height = Math.ceil(bounds[3]);
      tag = tag.replace(/\swidth="[^"]*"/, '').replace(/\sheight="[^"]*"/, '');
      return tag.replace('<svg', `<svg width="${width}" height="${height}"`);
    });
    const fingerprint = createHash('sha256')
      .update(readFileSync(join(sources, name)))
      .update(readFileSync(join(sources, 'mermaid-config.json')))
      .update(readFileSync(join(here, 'package-lock.json')))
      .update(readFileSync(fileURLToPath(import.meta.url)))
      .digest('hex');
    const marker = `<!-- diagram-source-sha256: ${fingerprint} -->`;
    svg = marker + '\n' + svg;
    writeFileSync(output, svg);
    if (check) {
      const published = join(sources, name.replace(/\.mmd$/, '.svg'));
      if (!existsSync(published) || !readFileSync(published, 'utf8').includes(marker)) {
        throw new Error(`Stale SVG: ${name}. Run npm run diagrams and commit the generated SVGs.`);
      }
    }
  }
  const readme = readFileSync(join(root, 'README.md'), 'utf8');
  if (readme.includes('```mermaid')) throw new Error('README should embed validated SVGs, not untested inline Mermaid');
  for (const match of readme.matchAll(/!\[[^\]]*\]\((docs\/diagrams\/[^)]+\.svg)\)/g)) {
    if (!files.includes(match[1].split('/').at(-1).replace(/\.svg$/, '.mmd'))) {
      throw new Error(`README diagram has no editable source: ${match[1]}`);
    }
    if (!existsSync(join(root, match[1]))) throw new Error(`Missing README diagram: ${match[1]}`);
  }
  console.log(`${files.length} diagrams rendered successfully${check ? ' in a temporary directory' : ''}`);
} finally {
  rmSync(temporary, { recursive: true, force: true });
}
