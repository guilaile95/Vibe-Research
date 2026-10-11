import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { noRemoteImages } from "../src/lib/noRemoteImages.ts";

// Server rendering is deliberately network-free: these reserved synthetic URLs
// are inspected as markup, never loaded in a browser or sent to a provider.
function render(markdown: string, guarded = true) {
  return renderToStaticMarkup(createElement(ReactMarkdown, {
    remarkPlugins: [remarkGfm],
    ...(guarded ? { components: noRemoteImages } : {}),
  }, markdown));
}

test("baseline Markdown emits an automatic-load image element; guard removes it", () => {
  const input = "![synthetic chart](https://example.invalid/pixel.gif?fixture=only)";
  assert.match(render(input, false), /<img[^>]+src="https:\/\/example.invalid\/pixel.gif\?fixture=only"/);
  assert.equal(render(input), '<p><span class="text-muted-foreground">[图片未加载：synthetic chart]</span></p>');
});

for (const url of [
  "https://example.invalid/pixel.gif?fixture=only", "http://example.invalid/i.png",
  "//example.invalid/i.png", "/api/synthetic-image", "./synthetic.png",
  "data:image/png;base64,AA==", "blob:https://example.invalid/synthetic",
]) {
  test(`untrusted image cannot create a resource element: ${url}`, () => {
    const html = render(`![说明](${url} "hidden title")`);
    assert.match(html, /\[图片未加载：说明\]/);
    assert.doesNotMatch(html, /<(?:img|link|source|iframe)\b|\b(?:src|srcset|title)=/);
    assert.ok(!html.includes(url));
  });
}

test("reference images, empty alt, and linked images retain readable placeholders", () => {
  const html = render('![报告][chart]\n\n[chart]: https://example.invalid/chart\n\n![](https://example.invalid/empty)\n\n[![来源](https://example.invalid/image)](https://example.invalid/source)');
  assert.match(html, /图片未加载：报告/);
  assert.match(html, /图片未加载：图片/);
  assert.match(html, /<a href="https:\/\/example.invalid\/source"><span[^>]*>\[图片未加载：来源\]<\/span><\/a>/);
  assert.doesNotMatch(html, /<img\b/);
});

test("links, code, math text, tables, and escaped raw HTML retain existing semantics", () => {
  const input = '## Risk\n\n[Source](https://example.invalid/source "Source title")\n\n- **Bold**\n\n> Quote\n\n| A | B |\n| - | - |\n| 1 | 2 |\n\n`![code](https://example.invalid/code)`\n\n```md\n![fenced](https://example.invalid/fence)\n```\n\n$x^2$\n\n<img src="https://example.invalid/raw" alt="raw">';
  assert.equal(render(input), render(input, false));
  assert.match(render(input), /<table>/);
  assert.doesNotMatch(render(input), /<img\b/);
});

test("alt text is escaped and trusted app-owned images are unaffected", () => {
  const html = render('![<script>alert(1)</script>](https://example.invalid/x)');
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(renderToStaticMarkup(createElement("img", { src: "/trusted-logo.svg", alt: "App logo" })), /<img[^>]+src="\/trusted-logo.svg"[^>]+alt="App logo"/);
});

test("every untrusted Markdown render site uses the shared guard", () => {
  const root = new URL("../src/", import.meta.url);
  const sites: string[] = [];
  function inspect(dir: string) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) inspect(path);
      else if (/\.tsx?$/.test(entry.name)) {
        const source = readFileSync(path, "utf8");
        const renders = [...source.matchAll(/<ReactMarkdown\b[^>]*>/g)];
        if (!renders.length) continue;
        sites.push(path);
        assert.match(source, /import \{ noRemoteImages \} from "@\/lib\/noRemoteImages";/);
        for (const [opening] of renders) assert.match(opening, /components=\{noRemoteImages\}/, path);
      }
    }
  }
  inspect(root.pathname);
  assert.equal(sites.length, 6);
});
