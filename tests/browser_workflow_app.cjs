/* Browser checks against browser_app_fixture.py, never against a real deployment. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

(async () => {
  const info = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
  const artifacts = process.argv[3] || path.resolve("..", "artifacts", "workflow-app");
  fs.mkdirSync(artifacts, { recursive: true });
  const settingsPath = path.join(info.home, "plugins", "workflow", "config.json");
  const settings = JSON.parse(fs.readFileSync(settingsPath, "utf8"));
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || "/usr/bin/chromium", headless: true, args: ["--no-sandbox"] });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1180 }, colorScheme: "dark", timezoneId: "Asia/Taipei" });
  const errors = [], actions = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => { if (request.method() === "POST" && request.url().includes("/api/plugins/workflow/")) actions.push(request.url()); });
  try {
    await page.goto(`http://127.0.0.1:${info.port}/workflow`);
    const app = page.locator(".workflow-app");
    await app.locator("h1").waitFor({ timeout: 30000 });
    assert.equal(await app.locator("h1").textContent(), "研发工作台");
    assert.equal(await app.getByRole("button", { name: /新建目标/ }).isDisabled(), true);
    await app.locator(".wf-execution").filter({ hasText: info.goal }).click();
    await app.locator(".wf-dag").waitFor();
    assert.equal(await app.locator(".wf-node").count(), 4);
    assert.match(await app.locator(".wf-title-line").textContent(), /已验收/);
    assert.match(await app.locator(".wf-task-info").textContent(), /成功完成/);
    await page.screenshot({ path: path.join(artifacts, "desktop.png"), fullPage: true });
    console.log("PASS: native Dashboard SDK, authenticated plugin, four-stage view, default read-only mode");

    await app.getByRole("button", { name: "验收证据", exact: true }).click();
    await app.locator(".wf-proof").nth(1).waitFor();
    assert.equal(await app.locator(".wf-proof").count(), 2);
    assert.equal(await app.locator(".wf-proof .wf-badge").first().textContent(), "通过");
    await app.locator(".wf-proof summary").first().click();
    assert.match(await app.locator(".wf-proof .wf-log").first().textContent(), /fixture checks: OK/);
    console.log("PASS: independent receipt/log viewing");

    await app.getByRole("textbox", { name: "搜索研发目标" }).fill("no-matching-execution");
    await app.getByText("没有匹配的目标", { exact: true }).waitFor();
    await app.getByRole("textbox", { name: "搜索研发目标" }).fill("");
    await app.locator(".wf-filters").getByRole("button", { name: "需要关注", exact: true }).click();
    assert.equal(await app.locator(".wf-execution").count(), 1);
    await app.locator(".wf-filters").getByRole("button", { name: "全部", exact: true }).click();
    await app.locator(".wf-execution").filter({ hasText: info.goal }).click();
    await app.getByRole("button", { name: "执行概览", exact: true }).click();
    console.log("PASS: search and blocked-task filtering");

    await page.setViewportSize({ width: 390, height: 844 });
    await app.locator(".wf-dag").scrollIntoViewIfNeeded();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "mobile horizontal overflow");
    await page.screenshot({ path: path.join(artifacts, "mobile.png"), fullPage: true });
    console.log("PASS: mobile layout without horizontal overflow");

    // Enable only this disposable fixture's operator-side switch, never via HTTP.
    settings.allow_actions = true;
    fs.writeFileSync(settingsPath, JSON.stringify(settings));
    await page.setViewportSize({ width: 1600, height: 1180 });
    await app.getByRole("button", { name: "刷新工作流" }).click();
    await page.waitForFunction(() => !Array.from(document.querySelectorAll(".workflow-app button")).find(button => button.textContent.includes("新建目标"))?.disabled);
    await app.getByRole("button", { name: /新建目标/ }).click();
    const dialog = page.getByRole("dialog", { name: "新建研发目标" });
    const objective = "离线浏览器测试 <img src=x onerror=window.__workflow_xss=1>";
    await dialog.getByLabel("研发目标", { exact: true }).fill(objective);
    await dialog.getByRole("button", { name: "创建待审批目标", exact: true }).click();
    await app.locator(".wf-title-line h2").filter({ hasText: objective }).waitFor({ timeout: 60000 });
    assert.equal(await page.evaluate(() => window.__workflow_xss), undefined);
    assert.equal(await app.locator(".wf-title-line img").count(), 0);
    assert.match(await app.locator(".wf-dag").textContent(), /待审批/);
    console.log("PASS: confirmed HTTP submission through existing core, XSS text escaping, triage default");

    await app.getByRole("button", { name: /授权执行/ }).click();
    const confirmation = page.getByRole("dialog", { name: "授权执行" });
    assert.equal(await confirmation.getByRole("button", { name: "确认操作", exact: true }).isDisabled(), true);
    await confirmation.getByRole("checkbox").check();
    await confirmation.press("Escape");
    await confirmation.waitFor({ state: "hidden" });
    assert.equal(actions.filter(url => url.includes("/actions/")).length, 0);
    assert.deepEqual(errors, []);
    console.log("PASS: explicit approval checkbox, keyboard cancellation, no action dispatched, no browser errors");
  } finally {
    settings.allow_actions = false;
    fs.writeFileSync(settingsPath, JSON.stringify(settings));
    await browser.close();
  }
})().catch(error => { console.error(error.stack); process.exit(1); });
