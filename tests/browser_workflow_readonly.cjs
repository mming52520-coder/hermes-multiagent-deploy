/* Real native Dashboard fixture; read-only compatibility, no operator actions. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

(async () => {
  const info = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
  const artifacts = process.argv[3];
  if (artifacts) fs.mkdirSync(artifacts, { recursive: true });
  const browser = await chromium.launch({ executablePath: "/usr/bin/chromium", headless: true, args: ["--no-sandbox"] });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1180 } });
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  try {
    // A browser previously using English should enter this Chinese package in Chinese.
    await page.addInitScript(() => {
      if (!localStorage.getItem("hermes-workflow-zh-initialized")) localStorage.setItem("hermes-locale", "en");
    });
    await page.goto(`http://127.0.0.1:${info.port}/workflow`);
    const app = page.locator(".workflow-app");
    await app.locator("h1").waitFor({ timeout: 30000 });
    assert.equal(await app.locator("h1").textContent(), "研发工作台");
    assert.equal(await page.evaluate(() => localStorage.getItem("hermes-locale")), "zh");
    assert.match(await page.locator("html").getAttribute("lang"), /^zh/);
    assert.equal(await page.getByRole("link", { name: "配置", exact: true }).count(), 1);
    for (const name of ["文件", "频道", "事件回调", "设备配对", "系统管理", "任务看板", "成就"]) {
      assert.equal(await page.getByRole("link", { name, exact: true }).count(), 1, name);
    }
    const consent = page.getByTestId("shared-metrics-consent-banner");
    await consent.waitFor();
    assert.match(await consent.textContent(), /帮助改进 Hermes/);
    assert.equal(await consent.getByRole("button", { name: "同意共享", exact: true }).count(), 1);
    assert.equal(await consent.getByRole("button", { name: "不共享", exact: true }).count(), 1);
    assert.equal(await app.getByRole("button", { name: /新建目标/ }).isDisabled(), true);
    await app.locator(".wf-execution").filter({ hasText: info.goal }).click();
    await app.locator(".wf-dag").waitFor();
    assert.equal(await app.locator(".wf-node").count(), 4);
    assert.match(await app.locator(".wf-gate-reason").textContent(), /本次执行尚未获得写入授权/);
    assert.equal(await app.locator(".wf-dag").getAttribute("aria-label"), "调查 → 开发 → 独立审查 → 最终汇总");
    if (artifacts) await page.screenshot({ path: path.join(artifacts, "desktop.png"), fullPage: true });
    const help = app.locator(".wf-help");
    await help.locator("summary").press("Enter");
    assert.notEqual(await help.getAttribute("open"), null);
    assert.match(await help.textContent(), /灰色按钮表示操作未开放/);
    assert.match(await help.textContent(), /Tab \/ Shift \+ Tab/);
    assert.match(await help.textContent(), /Esc/);
    if (artifacts) await help.screenshot({ path: path.join(artifacts, "help.png") });
    await help.locator("summary").press("Space");
    assert.equal(await help.getAttribute("open"), null);
    await app.getByRole("button", { name: "验收证据", exact: true }).click();
    await app.locator(".wf-proof").first().waitFor();
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    if (artifacts) await page.screenshot({ path: path.join(artifacts, "mobile.png"), fullPage: true });
    await help.locator("summary").click();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    await page.evaluate(() => localStorage.setItem("hermes-locale", "en"));
    await page.reload();
    await app.locator("h1").waitFor();
    assert.equal(await page.evaluate(() => localStorage.getItem("hermes-locale")), "en");
    assert.equal(await page.locator("html").getAttribute("lang"), "en");
    assert.deepEqual(errors, []);
    console.log("PASS: packaged native Dashboard/SDK; first visit in Chinese; later language choice preserved; Chinese native navigation and consent banner; Chinese gate reason and controls; help/keyboard; four stages; evidence; mobile layout; read-only; no page errors");
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error.stack); process.exit(1); });
